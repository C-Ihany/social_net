"""
account/pola_api.py
───────────────────
La messagerie de Pola (l'assistant de bureau) passe par Vazimba : c'est le relais qui connaît les
comptes, garde les messages quand un ordinateur est éteint, et ne voit que du chiffré (e2ee/).
Ces adresses sont celles que Pola appelle (JSON). Le chat lui-même passe par le même WebSocket
que le site (/chat/<id>/), et le chiffrement par /e2ee/.

  GET  /api/pola/bonjour        jeton CSRF + qui est connecté
  POST /api/pola/code           demander un code (connexion, ou inscription d'un nouveau numéro)
  POST /api/pola/verifier       saisir le code -> connecté (session de 180 jours)
  POST /api/pola/mode           « pola » (Pola seulement, invisible) ou « community »
  POST /api/pola/trouver        trouver un utilisateur de Pola par son numéro -> conversation
  GET  /api/pola/conversations  ses conversations privées
  POST /api/pola/deconnexion

Choix de l'utilisateur, expliqué dans Pola (texte validé le 18/11/2026) :
  « Pola seulement » : invisible sur le réseau social ; seuls les utilisateurs de Pola qui ont
  son numéro peuvent lui écrire. « Pola + communauté » : membre comme les autres.
"""
import logging
import re
import secrets

from django.contrib.auth import login, logout
from django.db.models import Q
from django.http import JsonResponse
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from account import otp as otp_codes
from account.models import Account, UserBlock
from account.sms import format_phone_display

logger = logging.getLogger(__name__)

SESSION_DAYS = 180
_BACKEND = 'account.backends.CaseInsensitiveModelBackend'
_SENT = "Si ce numéro peut recevoir un code, il vient d'être envoyé."


def _json(request):
    import json
    try:
        data = json.loads(request.body or b'{}')
        return data if isinstance(data, dict) else {}
    except (ValueError, UnicodeDecodeError):
        return request.POST.dict()


def _me(user):
    return {'id': user.pk, 'username': user.username, 'mode': user.pola_mode or 'community',
            'phone': format_phone_display(user.phone_number) if user.phone_verified else '',
            'image': user.profile_image.url if user.profile_image else ''}


def _person(user):
    """Ce qu'un utilisateur de Pola voit d'un contact (rien de plus)."""
    return {'id': user.pk, 'username': user.username,
            'image': user.profile_image.url if user.profile_image else ''}


def _login_required(view):
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({'error': 'Connexion requise.', 'code': 'LOGIN'}, status=401)
        return view(request, *args, **kwargs)
    wrapped.__name__ = view.__name__
    return wrapped


@require_GET
@ensure_csrf_cookie
def hello(request):
    """Le premier appel de Pola : pose le jeton CSRF et dit qui est connecté (ou personne)."""
    user = request.user
    return JsonResponse({'ok': True, 'me': _me(user) if user.is_authenticated else None,
                         'channels': otp_codes.channels_for('login')})


@require_POST
def request_code(request):
    """Envoie un code au numéro. Compte existant (numéro confirmé) : code de connexion, par SMS,
    WhatsApp ou e-mail. Numéro inconnu : code d'inscription, par SMS ou WhatsApp seulement (il
    faut prouver qu'on a ce téléphone). Même réponse dans tous les cas (rien à deviner)."""
    data = _json(request)
    phone = otp_codes.read_phone(data.get('phone', ''), data.get('country', ''))
    if not phone:
        return JsonResponse({'error': "Numéro invalide : choisissez le pays, ou écrivez l'indicatif (+…). "
                                      "Il faut un numéro de mobile."}, status=400)
    account = otp_codes.account_for_phone(phone)
    purpose = 'login' if account else 'signup'
    if data.get('channel') == 'email' and account is None:
        # (pas de compte, donc pas d'adresse : on ne dit pas pour autant que le numéro est inconnu)
        return JsonResponse({'ok': True, 'message': _SENT, 'phone_display': format_phone_display(phone),
                             'channel': 'email'})
    channel = otp_codes.pick_channel(data.get('channel', ''), purpose if purpose == 'login' else 'verify')
    refused = otp_codes.channel_refused(phone, channel)
    if refused:
        return JsonResponse({'error': refused}, status=400)
    if otp_codes.too_many_sends(phone):
        return JsonResponse({'error': 'Trop de codes demandés pour ce numéro. Réessayez dans une heure.'}, status=429)
    error = otp_codes.issue_code(account, phone, purpose, channel)
    if error:
        return JsonResponse({'error': error}, status=500)
    request.session['pola_phone'] = phone
    return JsonResponse({'ok': True, 'message': _SENT, 'phone_display': format_phone_display(phone),
                         'channel': channel})


def _free_username(name):
    base = re.sub(r'[^\w.\-]', '', (name or '').strip().replace(' ', '_'))[:24] or 'pola'
    candidate = base
    while Account.objects.filter(username__iexact=candidate).exists():
        candidate = f'{base[:24]}_{secrets.randbelow(10000)}'
    return candidate


@require_POST
def verify_code(request):
    """Le code reçu. Connexion, ou création du compte (nom choisi, e-mail facultatif)."""
    data = _json(request)
    phone = request.session.get('pola_phone')
    if not phone:
        return JsonResponse({'error': 'Recommencez : indiquez votre numéro.'}, status=400)
    account = otp_codes.account_for_phone(phone)
    otp, error = otp_codes.check_code(phone, 'login' if account else 'signup', data.get('code'))
    if error:
        return JsonResponse({'error': error}, status=400)
    created = member = False
    if account is None:
        name = (data.get('name') or '').strip()
        if not name:
            # (le code reste valable : on redemande seulement le nom)
            otp.verified = False
            otp.save(update_fields=['verified'])
            return JsonResponse({'error': 'Choisissez le nom que verront vos contacts.', 'code': 'NAME'}, status=400)
        email = (data.get('email') or '').strip().lower()
        if email and Account.objects.filter(email__iexact=email).exists():
            otp.verified = False
            otp.save(update_fields=['verified'])
            return JsonResponse({'error': 'Cette adresse e-mail a déjà un compte : connectez-vous avec le numéro de ce compte.',
                                 'code': 'EMAIL'}, status=400)
        # Sans e-mail : une adresse interne, qui ne sert jamais à se connecter (seulement le numéro).
        email = email or f'pola-{secrets.token_hex(8)}@pola.vazimba.invalid'
        account = Account.objects.create_user(email, _free_username(name))
        account.set_unusable_password()
        account.phone_number, account.phone_verified = phone, True
        mode = data.get('mode')
        account.pola_mode = mode if mode in (Account.POLA_ONLY, Account.POLA_COMMUNITY) else Account.POLA_ONLY
        account.save()
        created = True
    elif not account.pola_mode:
        # Déjà membre de Vazimba : il le reste, même s'il a demandé « Pola seulement » (le cacher
        # d'un coup à tous ses amis serait une surprise). Pola le lui dit (`member`) et lui
        # propose de passer en « Pola seulement » dans ses réglages.
        account.pola_mode = Account.POLA_COMMUNITY
        account.save(update_fields=['pola_mode'])
    if not created and data.get('mode') == Account.POLA_ONLY and account.pola_mode == Account.POLA_COMMUNITY:
        member = True
    request.session.pop('pola_phone', None)
    login(request, account, backend=_BACKEND)
    request.session.set_expiry(SESSION_DAYS * 24 * 3600)
    return JsonResponse({'ok': True, 'created': created, 'member': member, 'me': _me(account)})


@require_POST
@_login_required
def set_mode(request):
    mode = _json(request).get('mode')
    if mode not in (Account.POLA_ONLY, Account.POLA_COMMUNITY):
        return JsonResponse({'error': 'Choix inconnu.'}, status=400)
    Account.objects.filter(pk=request.user.pk).update(pola_mode=mode)
    request.user.pola_mode = mode
    return JsonResponse({'ok': True, 'me': _me(request.user)})


@require_POST
@_login_required
def find_by_phone(request):
    """Trouver un utilisateur de Pola par son numéro exact, et ouvrir la conversation (secrète)
    avec lui. Seuls les utilisateurs de Pola qui ont confirmé leur numéro sont trouvables ainsi :
    les membres de Vazimba qui n'utilisent pas Pola n'ont pas donné leur accord."""
    from chat.utils import find_or_create_private_chat
    data = _json(request)
    phone = otp_codes.read_phone(data.get('phone', ''), data.get('country', ''))
    if not phone:
        return JsonResponse({'error': 'Numéro invalide.'}, status=400)
    other = (Account.objects.filter(phone_number=phone, phone_verified=True, is_active=True)
             .exclude(pola_mode='').exclude(pk=request.user.pk).first())
    if other is None or UserBlock.is_blocked_between(request.user, other):
        return JsonResponse({'found': False, 'message': "Personne n'utilise la messagerie de Pola avec ce numéro."})
    room = find_or_create_private_chat(request.user, other)
    changed = []
    if not room.is_active:
        room.is_active = True
        changed.append('is_active')
    if not room.encrypted:
        room.encrypted = True          # entre utilisateurs de Pola : toujours chiffré
        changed.append('encrypted')
    if changed:
        room.save(update_fields=changed)
    return JsonResponse({'found': True, 'person': _person(other), 'room_id': room.pk})


@require_GET
@_login_required
def conversations(request):
    from chat.models import PrivateChatRoom, RoomChatMessage, UnreadChatRoomMessages
    me = request.user
    rooms = (PrivateChatRoom.objects.filter(Q(user1=me) | Q(user2=me), is_active=True)
             .select_related('user1', 'user2'))
    if me.pola_mode == Account.POLA_ONLY:
        # « Pola seulement » : seulement les conversations avec des utilisateurs de Pola ;
        # celles avec les membres de Vazimba restent sur le site, rien n'est effacé.
        rooms = rooms.filter((Q(user1=me) & ~Q(user2__pola_mode='')) | (Q(user2=me) & ~Q(user1__pola_mode='')))
    unread = dict(UnreadChatRoomMessages.objects.filter(user=me, room__in=rooms).values_list('room_id', 'count'))
    result = []
    for room in rooms:
        other = room.user2 if room.user1_id == me.pk else room.user1
        last = RoomChatMessage.objects.filter(room=room).order_by('-timestamp').first()
        result.append({'room_id': room.pk, 'person': _person(other), 'encrypted': room.encrypted,
                       'unread': unread.get(room.pk, 0),
                       'last': (last.preview or '')[:80] if last else '',
                       'last_at': int(last.timestamp.timestamp() * 1000) if last else 0})
    result.sort(key=lambda r: -r['last_at'])
    return JsonResponse({'conversations': result})


@require_POST
def sign_out(request):
    logout(request)
    return JsonResponse({'ok': True})
