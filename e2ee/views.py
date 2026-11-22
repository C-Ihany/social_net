"""
e2ee/views.py
─────────────
Le serveur des clés du chiffrement de bout en bout. Le moteur du navigateur (matrix-sdk-crypto-wasm)
parle le langage des serveurs Matrix pour ses clés ; Vazimba en reprend seulement les quelques
demandes nécessaires, avec les mêmes formes de messages :

  POST keys/upload               publier les clés publiques de cet appareil
  POST keys/query                lire les clés publiques des appareils d'un contact
  POST keys/claim                prendre une clé à usage unique d'un appareil (pour lui écrire)
  PUT  sendToDevice/<type>/<txn> déposer des messages chiffrés pour d'autres appareils
  GET  sync                      relever sa boîte aux lettres + qui a changé d'appareils
  POST keys/device_signing/upload, keys/signatures/upload   signature croisée (vérification)
  room_keys/version, room_keys/keys, recovery               sauvegarde chiffrée des clés

L'appareil se présente avec l'en-tête « X-E2EE-Device ». On ne parle qu'à ses CONTACTS : les
personnes avec qui l'on a une conversation privée (et soi-même).
Rien ici ne permet de lire un message : le serveur ne voit que des clés publiques et des
contenus chiffrés.
"""
import json
import re
from functools import wraps

from django.contrib.auth.hashers import check_password
from django.db import transaction
from django.db.models import Count, Max, Q
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from chat.models import PrivateChatRoom
from e2ee import ids
from e2ee.models import (BackedUpRoomKey, CrossSigningKeys, Device, DeviceListChange, KeyBackupVersion,
                         OneTimeKey, PeerSignature, RecoverySecret, ToDeviceMessage)

MAX_BODY = 256 * 1024          # une demande ne dépasse pas 256 Ko
MAX_DEVICES = 10               # appareils par membre (au-delà, le plus ancien est oublié)
MAX_OTKS_PER_UPLOAD = 200
MAX_INBOX_BATCH = 100
MAX_INBOX = 2000               # messages en attente par appareil (au-delà, les nouveaux sont refusés)
_DEVICE_RE = re.compile(r'^[A-Za-z0-9_\-]{4,64}$')


def _error(status, errcode, message):
    # (même forme que les erreurs Matrix : le moteur du navigateur les comprend)
    return JsonResponse({'errcode': errcode, 'error': message}, status=status)


def api(view):
    """Connexion obligatoire, corps JSON lu et limité, appareil lu dans l'en-tête."""
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return _error(401, 'M_UNKNOWN_TOKEN', 'Connexion requise.')
        request.json = {}
        if request.method in ('POST', 'PUT'):
            # (la taille annoncée d'abord : inutile de lire 100 Mo pour les refuser)
            try:
                announced = int(request.META.get('CONTENT_LENGTH') or 0)
            except ValueError:
                announced = 0
            if announced > MAX_BODY or len(request.body) > MAX_BODY:
                return _error(413, 'M_TOO_LARGE', 'Demande trop grande.')
            try:
                request.json = json.loads(request.body or b'{}')
            except (ValueError, UnicodeDecodeError):
                return _error(400, 'M_NOT_JSON', 'JSON illisible.')
            if not isinstance(request.json, dict):
                return _error(400, 'M_BAD_JSON', 'Un objet JSON est attendu.')
        device_id = request.headers.get('X-E2EE-Device', '')
        request.device_id = device_id if _DEVICE_RE.match(device_id) else ''
        return view(request, *args, **kwargs)
    return wrapped


def _my_device(request):
    if not request.device_id:
        return None
    return Device.objects.filter(user=request.user, device_id=request.device_id).first()


def contacts(user):
    """Les numéros de compte avec qui `user` peut échanger des clés : lui-même et les personnes
    avec qui il a une conversation privée (sauf celles qu'il a bloquées ou qui l'ont bloqué)."""
    from account.models import UserBlock
    pairs = PrivateChatRoom.objects.filter(Q(user1=user) | Q(user2=user)).values_list('user1_id', 'user2_id')
    allowed = {user.pk}
    for a, b in pairs:
        allowed.update((a, b))
    if len(allowed) > 1:
        for blocker, blocked in UserBlock.objects.filter(Q(blocker=user) | Q(blocked=user)).values_list('blocker_id', 'blocked_id'):
            allowed.discard(blocked if blocker == user.pk else blocker)
    return allowed


def _changed(user_pk):
    DeviceListChange.objects.create(user_id=user_pk)


def _otk_counts(device):
    counts = {}
    for algorithm in device.one_time_keys.filter(fallback=False).values_list('algorithm', flat=True):
        counts[algorithm] = counts.get(algorithm, 0) + 1
    return counts


# ── Clés des appareils ──────────────────────────────────────────────────────

@require_http_methods(['POST'])
@api
def keys_upload(request):
    body, me = request.json, request.user
    if not request.device_id:
        return _error(400, 'M_MISSING_PARAM', 'Appareil inconnu (en-tête X-E2EE-Device).')
    device = _my_device(request)
    device_keys = body.get('device_keys')
    if device_keys is not None:
        if not isinstance(device_keys, dict) or device_keys.get('user_id') != ids.user_id(me) \
                or device_keys.get('device_id') != request.device_id or not isinstance(device_keys.get('keys'), dict):
            return _error(400, 'M_INVALID_PARAM', 'Clés de l\'appareil invalides.')
        if device is None:
            # Trop d'appareils : on oublie le plus ancien (vieux navigateur jamais revu)
            mine = Device.objects.filter(user=me).order_by('last_seen')
            for old in mine[:max(0, mine.count() - MAX_DEVICES + 1)]:
                old.delete()
            device = Device.objects.create(user=me, device_id=request.device_id, keys=device_keys)
            _changed(me.pk)
        elif device.keys != device_keys:
            old_identity = (device.keys or {}).get('keys', {})
            # Les clés d'identité d'un appareil ne changent jamais ; seules les signatures s'ajoutent.
            if any(old_identity.get(k) not in (None, v) for k, v in device_keys['keys'].items()):
                return _error(400, 'M_INVALID_PARAM', 'Les clés de cet appareil ne peuvent pas changer.')
            device.keys = device_keys
            device.save(update_fields=['keys', 'last_seen'])
            _changed(me.pk)
    if device is None:
        return _error(400, 'M_INVALID_PARAM', 'Publiez d\'abord les clés de l\'appareil.')

    one_time = body.get('one_time_keys') or {}
    fallback = body.get('fallback_keys') or {}
    if not isinstance(one_time, dict) or not isinstance(fallback, dict) or len(one_time) > MAX_OTKS_PER_UPLOAD:
        return _error(400, 'M_INVALID_PARAM', 'Clés à usage unique invalides.')
    for full_id, key in one_time.items():
        algorithm, _, key_id = str(full_id).partition(':')
        if algorithm and key_id:
            OneTimeKey.objects.get_or_create(device=device, algorithm=algorithm, key_id=key_id, fallback=False,
                                             defaults={'key': key})
    for full_id, key in fallback.items():
        algorithm, _, key_id = str(full_id).partition(':')
        if algorithm and key_id:
            device.one_time_keys.filter(fallback=True, algorithm=algorithm).delete()
            OneTimeKey.objects.create(device=device, algorithm=algorithm, key_id=key_id, key=key, fallback=True)
    return JsonResponse({'one_time_key_counts': _otk_counts(device)})


@require_http_methods(['POST'])
@api
def keys_query(request):
    asked = request.json.get('device_keys') or {}
    if not isinstance(asked, dict):
        return _error(400, 'M_INVALID_PARAM', 'device_keys invalide.')
    me, allowed = request.user, contacts(request.user)
    result = {'device_keys': {}, 'master_keys': {}, 'self_signing_keys': {}, 'user_signing_keys': {}, 'failures': {}}
    for mxid, wanted in asked.items():
        pk = ids.user_pk(mxid)
        if pk is None or pk not in allowed:
            continue                                     # (pas un contact : on ne dit rien)
        devices = Device.objects.filter(user_id=pk)
        if isinstance(wanted, list) and wanted:
            devices = devices.filter(device_id__in=wanted)
        result['device_keys'][mxid] = {d.device_id: d.keys for d in devices}
        cross = CrossSigningKeys.objects.filter(user_id=pk).first()
        if cross and cross.master:
            master = json.loads(json.dumps(cross.master))
            # Mes propres signatures de vérification sur cette personne (vues par moi seul)
            for sig in PeerSignature.objects.filter(signer=me, target_id=pk):
                master.setdefault('signatures', {}).setdefault(ids.user_id(me), {})[sig.key_id] = sig.signature
            result['master_keys'][mxid] = master
        if cross and cross.self_signing:
            result['self_signing_keys'][mxid] = cross.self_signing
        if cross and cross.user_signing and pk == me.pk:
            result['user_signing_keys'][mxid] = cross.user_signing
    return JsonResponse(result)


@require_http_methods(['POST'])
@api
def keys_claim(request):
    asked = request.json.get('one_time_keys') or {}
    if not isinstance(asked, dict):
        return _error(400, 'M_INVALID_PARAM', 'one_time_keys invalide.')
    allowed = contacts(request.user)
    claimed = {}
    with transaction.atomic():
        for mxid, devices in asked.items():
            pk = ids.user_pk(mxid)
            if pk is None or pk not in allowed or not isinstance(devices, dict):
                continue
            for device_id, algorithm in list(devices.items())[:MAX_DEVICES * 2]:
                device = Device.objects.filter(user_id=pk, device_id=device_id).first()
                if device is None:
                    continue
                key = (OneTimeKey.objects.select_for_update()
                       .filter(device=device, algorithm=algorithm, fallback=False).order_by('id').first())
                if key is not None:
                    key.delete()                         # (une clé à usage unique ne sert qu'une fois)
                else:
                    key = device.one_time_keys.filter(algorithm=algorithm, fallback=True).first()
                    if key is None:
                        continue
                    if not key.used:
                        key.used = True
                        key.save(update_fields=['used'])
                claimed.setdefault(mxid, {})[device_id] = {f'{key.algorithm}:{key.key_id}': key.key}
    return JsonResponse({'one_time_keys': claimed, 'failures': {}})


# ── Boîte aux lettres d'appareil à appareil ─────────────────────────────────

@require_http_methods(['PUT'])
@api
def send_to_device(request, event_type, txn_id):
    me = request.user
    messages = request.json.get('messages') or {}
    if not isinstance(messages, dict) or len(event_type) > 80 or len(txn_id) > 80:
        return _error(400, 'M_INVALID_PARAM', 'messages invalide.')
    # La même demande renvoyée (coupure réseau) n'est déposée qu'une fois.
    if txn_id and ToDeviceMessage.objects.filter(sender=me, sender_device_id=request.device_id, txn_id=txn_id).exists():
        return JsonResponse({})
    allowed = contacts(me)
    created = []
    for mxid, per_device in messages.items():
        pk = ids.user_pk(mxid)
        if pk is None or pk not in allowed or not isinstance(per_device, dict):
            continue
        for device_id, content in per_device.items():
            targets = Device.objects.filter(user_id=pk).annotate(waiting=Count('inbox'))
            if device_id != '*':
                targets = targets.filter(device_id=device_id)
            for device in targets:
                if device.waiting >= MAX_INBOX:
                    continue                             # (boîte pleine : on n'empile pas sans fin)
                created.append(ToDeviceMessage(recipient=device, sender=me, sender_device_id=request.device_id,
                                               type=event_type, content=content, txn_id=txn_id))
    ToDeviceMessage.objects.bulk_create(created[:MAX_DEVICES * 20])
    return JsonResponse({})


@require_http_methods(['GET'])
@api
def sync(request):
    """Ce que l'appareil doit savoir : ses messages d'appareil à appareil, les contacts qui ont
    changé d'appareils, et combien de clés à usage unique il lui reste.
    ?since=<repère> (journal des appareils) &ack=<numéro> (messages déjà reçus, à effacer)."""
    device = _my_device(request)
    if device is None:
        return _error(400, 'M_INVALID_PARAM', 'Appareil inconnu : publiez d\'abord ses clés.')
    try:
        since = int(request.GET.get('since') or 0)
        ack = int(request.GET.get('ack') or 0)
    except ValueError:
        return _error(400, 'M_INVALID_PARAM', 'Repère invalide.')
    if ack:
        device.inbox.filter(id__lte=ack).delete()
    inbox = list(device.inbox.select_related('sender').order_by('id')[:MAX_INBOX_BATCH])
    events = [{'type': m.type, 'sender': ids.user_id(m.sender_id), 'content': m.content} for m in inbox]
    changes = DeviceListChange.objects.filter(id__gt=since, user_id__in=contacts(request.user))
    changed = sorted({ids.user_id(pk) for pk in changes.values_list('user_id', flat=True)}) if since else []
    latest = DeviceListChange.objects.aggregate(m=Max('id'))['m'] or 0
    fallback_unused = sorted(set(device.one_time_keys.filter(fallback=True, used=False)
                                 .values_list('algorithm', flat=True)))
    device.save(update_fields=['last_seen'])
    return JsonResponse({
        'to_device': {'events': events},
        'ack': inbox[-1].id if inbox else ack,
        'more': len(inbox) == MAX_INBOX_BATCH,
        'device_lists': {'changed': changed, 'left': []},
        'since': latest,
        'device_one_time_keys_count': _otk_counts(device),
        'device_unused_fallback_key_types': fallback_unused,
    })


@require_http_methods(['GET'])
@api
def my_devices(request):
    devices = Device.objects.filter(user=request.user).order_by('-last_seen')
    return JsonResponse({'devices': [
        {'device_id': d.device_id, 'name': d.name, 'last_seen': d.last_seen.isoformat(),
         'current': d.device_id == request.device_id} for d in devices]})


@require_http_methods(['DELETE'])
@api
def delete_device(request, device_id):
    deleted, _ = Device.objects.filter(user=request.user, device_id=device_id).delete()
    if deleted:
        _changed(request.user.pk)
    return JsonResponse({'deleted': bool(deleted)})


# ── Signature croisée (vérification des contacts) ───────────────────────────

@require_http_methods(['POST'])
@api
def device_signing_upload(request):
    me, body = request.user, request.json
    keys = {name: body.get(f'{name}_key') for name in ('master', 'self_signing', 'user_signing')}
    for name, key in keys.items():
        if key is not None and (not isinstance(key, dict) or key.get('user_id') != ids.user_id(me)):
            return _error(400, 'M_INVALID_PARAM', f'Clé {name} invalide.')
    cross, _ = CrossSigningKeys.objects.get_or_create(user=me)
    # Remplacer une identité déjà posée exige le mot de passe : sinon, quelqu'un qui volerait la
    # session pourrait se faire passer pour ce membre auprès de ses contacts.
    if cross.master and keys['master'] and keys['master'] != cross.master:
        auth = body.get('auth')
        password = auth.get('password', '') if isinstance(auth, dict) else ''
        if not isinstance(password, str) or not password or not check_password(password, me.password):
            return JsonResponse({'errcode': 'M_FORBIDDEN', 'error': 'Mot de passe requis pour changer d\'identité.',
                                 'flows': [{'stages': ['m.login.password']}], 'params': {}}, status=401)
    for name, key in keys.items():
        if key is not None:
            setattr(cross, name, key)
    cross.save()
    _changed(me.pk)
    return JsonResponse({})


@require_http_methods(['POST'])
@api
def signatures_upload(request):
    me = request.user
    for mxid, objects in request.json.items():
        pk = ids.user_pk(mxid)
        if pk is None or not isinstance(objects, dict):
            continue
        for key_id, signed in objects.items():
            all_signatures = signed.get('signatures') if isinstance(signed, dict) else None
            signatures = all_signatures.get(ids.user_id(me)) if isinstance(all_signatures, dict) else None
            if not isinstance(signatures, dict) or not signatures:
                continue
            if pk == me.pk:
                device = Device.objects.filter(user=me, device_id=key_id).first()
                if device is not None:
                    device.keys.setdefault('signatures', {}).setdefault(ids.user_id(me), {}).update(signatures)
                    device.save(update_fields=['keys', 'last_seen'])
                    continue
                cross = CrossSigningKeys.objects.filter(user=me).first()
                if cross and cross.master:
                    cross.master.setdefault('signatures', {}).setdefault(ids.user_id(me), {}).update(signatures)
                    cross.save(update_fields=['master', 'updated_at'])
            elif pk in contacts(me):
                for sig_id, value in signatures.items():
                    PeerSignature.objects.update_or_create(signer=me, target_id=pk, key_id=sig_id,
                                                           defaults={'signature': str(value)})
        _changed(me.pk)
    return JsonResponse({'failures': {}})


# ── Sauvegarde des clés (chiffrée pour le membre seul) ──────────────────────

def _current_backup(user):
    return KeyBackupVersion.objects.filter(user=user, deleted=False).order_by('-id').first()


@require_http_methods(['GET', 'POST'])
@api
def backup_version(request):
    me = request.user
    if request.method == 'POST':
        algorithm, auth_data = request.json.get('algorithm'), request.json.get('auth_data')
        if not isinstance(algorithm, str) or not isinstance(auth_data, dict):
            return _error(400, 'M_INVALID_PARAM', 'Sauvegarde invalide.')
        # Un code secret existe déjà : refaire la sauvegarde rendrait illisibles, sur un nouvel
        # appareil, tous les messages d'avant. Il faut le demander exprès (« replace »).
        if request.json.get('replace') is not True and RecoverySecret.objects.filter(user=me).exists():
            return _error(409, 'M_RECOVERY_EXISTS', 'Un code secret existe déjà pour ce compte.')
        KeyBackupVersion.objects.filter(user=me).update(deleted=True)
        backup = KeyBackupVersion.objects.create(user=me, algorithm=algorithm, auth_data=auth_data)
        return JsonResponse({'version': str(backup.pk)})
    backup = _current_backup(me)
    if backup is None:
        return _error(404, 'M_NOT_FOUND', 'Aucune sauvegarde.')
    return JsonResponse({'algorithm': backup.algorithm, 'auth_data': backup.auth_data, 'version': str(backup.pk),
                         'count': backup.keys.count(), 'etag': str(backup.etag)})


def _my_room_ids(user):
    return {ids.room_id(pk) for pk in
            PrivateChatRoom.objects.filter(Q(user1=user) | Q(user2=user)).values_list('pk', flat=True)}


@require_http_methods(['GET', 'PUT'])
@api
def backup_keys(request):
    me = request.user
    backup = _current_backup(me)
    if backup is None or request.GET.get('version') != str(backup.pk):
        return _error(403, 'M_WRONG_ROOM_KEYS_VERSION', 'Version de sauvegarde périmée.')
    if request.method == 'GET':
        rooms = {}
        for key in backup.keys.all():
            rooms.setdefault(key.room_id, {'sessions': {}})['sessions'][key.session_id] = key.data
        return JsonResponse({'rooms': rooms})
    rooms = request.json.get('rooms') or {}
    if not isinstance(rooms, dict):
        return _error(400, 'M_INVALID_PARAM', 'rooms invalide.')
    mine = _my_room_ids(me)
    wanted = {}
    for room_id, room in rooms.items():
        sessions = room.get('sessions') if isinstance(room, dict) else None
        if room_id not in mine or not isinstance(sessions, dict):
            continue
        for session_id, data in sessions.items():
            if isinstance(data, dict) and isinstance(session_id, str) and len(session_id) <= 120:
                wanted[(room_id, session_id)] = data
    # Les copies déjà gardées, lues en une seule requête (avant : deux requêtes par clé)
    existing = {(k.room_id, k.session_id): k for k in
                BackedUpRoomKey.objects.filter(backup=backup, room_id__in={r for r, _ in wanted})}

    def first_index(data):
        value = data.get('first_message_index', 0) if isinstance(data, dict) else 0
        return value if isinstance(value, int) else 0

    to_create, to_update = [], []
    for (room_id, session_id), data in wanted.items():
        old = existing.get((room_id, session_id))
        if old is None:
            to_create.append(BackedUpRoomKey(backup=backup, room_id=room_id, session_id=session_id, data=data))
        # (on garde la meilleure copie : celle qui remonte le plus loin dans la conversation)
        elif first_index(old.data) >= first_index(data):
            old.data = data
            to_update.append(old)
    BackedUpRoomKey.objects.bulk_create(to_create, ignore_conflicts=True)
    BackedUpRoomKey.objects.bulk_update(to_update, ['data'])
    backup.etag += 1
    backup.save(update_fields=['etag'])
    return JsonResponse({'count': backup.keys.count(), 'etag': str(backup.etag)})


_RECOVERY_FIELDS = {'v', 'salt', 'iterations', 'iv', 'ciphertext', 'backup_version'}


@require_http_methods(['GET', 'PUT'])
@api
def recovery(request):
    """La clé de sauvegarde chiffrée avec le code secret (dans le navigateur)."""
    me = request.user
    if request.method == 'GET':
        secret = RecoverySecret.objects.filter(user=me).first()
        if secret is None:
            return JsonResponse({'exists': False})     # (pas d'erreur : c'est une simple question)
        return JsonResponse(dict(secret.blob, exists=True))
    blob = request.json
    if set(blob) - _RECOVERY_FIELDS or not {'salt', 'iv', 'ciphertext', 'iterations'} <= set(blob) \
            or not isinstance(blob.get('iterations'), int) or blob['iterations'] < 100000:
        return _error(400, 'M_INVALID_PARAM', 'Sauvegarde du code secret invalide.')
    RecoverySecret.objects.update_or_create(user=me, defaults={'blob': blob})
    return JsonResponse({})
