"""
account/otp.py
──────────────
Les codes à usage unique envoyés par SMS ou WhatsApp : les fabriquer, les envoyer, les vérifier.
Servent à confirmer le numéro d'un compte (« verify ») et à se connecter avec son numéro
(« login »).

Pour se connecter, le code peut aussi partir par E-MAIL, à l'adresse du compte lié au numéro
(utile à l'étranger, sans SMS ni WhatsApp). Jamais pour CONFIRMER un numéro : un e-mail ne
prouve pas qu'on a le téléphone, et on pourrait s'attribuer le numéro de quelqu'un d'autre.

Protections :
- code de 6 chiffres tiré par `secrets`, valable 10 minutes, 5 essais au plus ;
- seule l'EMPREINTE du code est gardée en base (PhoneVerification.digest) ;
- 3 envois par numéro et par heure (ici), et des limites par adresse IP (dans les urls.py) ;
- par SMS, seulement des numéros malgaches (un SMS vers l'étranger coûte cher, et des robots
  s'en servent pour faire payer le site) ; par WhatsApp, tous les numéros.
"""
import logging
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from account.models import Account, PhoneVerification
from account.sms import normalize_phone, otp_channels, send_otp

logger = logging.getLogger(__name__)


def read_phone(raw, channel):
    """Le numéro au format E.164, ou None. À l'étranger, seulement par WhatsApp ou e-mail
    (par SMS, il faudrait payer un SMS vers l'étranger)."""
    return normalize_phone(raw or '', international=(channel in ('whatsapp', 'email')))


def channels_for(purpose):
    """Les moyens d'envoi proposés : l'e-mail en plus, seulement pour se connecter."""
    channels = otp_channels()
    return channels + ['email'] if purpose == 'login' else channels


def pick_channel(asked, purpose='verify'):
    """Le moyen d'envoi demandé s'il est proposé, sinon le premier proposé."""
    channels = channels_for(purpose)
    if asked in channels:
        return asked
    return channels[0] if channels else 'sms'


def too_many_sends(phone):
    """Vrai si ce numéro a déjà reçu trop de codes dans l'heure (tous buts confondus)."""
    since = timezone.now() - timedelta(hours=1)
    return PhoneVerification.objects.filter(phone=phone, created_at__gte=since).count() \
        >= PhoneVerification.MAX_SENDS_PER_HOUR


def issue_code(user, phone, purpose, channel):
    """Fabrique un code pour `user` et l'envoie au numéro. Rend None si tout va bien, sinon
    le message d'erreur à montrer. Les anciens codes en attente (même but) sont annulés."""
    PhoneVerification.objects.filter(user=user, phone=phone, purpose=purpose, verified=False) \
        .update(attempts=PhoneVerification.MAX_ATTEMPTS)
    code = PhoneVerification.generate_code()
    otp = PhoneVerification.objects.create(user=user, phone=phone, purpose=purpose, channel=channel,
                                           code=PhoneVerification.digest(phone, code))
    try:
        if channel == 'email':
            _send_by_email(user, code)
        else:
            send_otp(phone, code, channel)
    except Exception as exc:  # noqa: BLE001 - le fournisseur a refusé ou ne répond pas
        logger.error('[OTP] Envoi par %s échoué vers %s : %s', channel, phone, exc)
        otp.delete()          # (ne pas garder un code qui n'est pas parti)
        return "L'envoi du code a échoué. Vérifiez le numéro et réessayez."
    return None


def _send_by_email(user, code):
    """Le code de connexion à l'adresse e-mail du compte (Brevo en production)."""
    minutes = PhoneVerification.OTP_VALID_MINUTES
    send_mail(
        subject=f'Votre code de connexion Vazimba : {code}',
        message=(f"Bonjour {user.username},\n\n"
                 f"Votre code pour vous connecter à Vazimba avec votre numéro : {code}\n"
                 f"Il est valable {minutes} minutes.\n\n"
                 "Si vous n'avez rien demandé, ignorez ce message : sans ce code, personne ne peut "
                 "se connecter. Ne le donnez à personne, même pas à quelqu'un qui dit venir de Vazimba."),
        from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', None),
        recipient_list=[user.email],
    )


def check_code(phone, purpose, code, user=None):
    """Vérifie un code saisi. Rend (code_validé, message_d'erreur) : l'un des deux est None.
    Un essai raté est compté ; au 5e, le code est perdu."""
    code = (code or '').strip()
    if not code.isdigit() or len(code) != 6:
        return None, 'Le code doit comporter 6 chiffres.'
    pending = PhoneVerification.objects.filter(phone=phone, purpose=purpose, verified=False,
                                               attempts__lt=PhoneVerification.MAX_ATTEMPTS)
    if user is not None:
        pending = pending.filter(user=user)
    otp = pending.order_by('-created_at').first()
    if otp is None:
        return None, 'Aucun code en cours pour ce numéro. Demandez-en un nouveau.'
    if otp.is_expired:
        return None, 'Code expiré. Demandez un nouveau code.'
    otp.attempts += 1
    otp.save(update_fields=['attempts'])
    if not otp.matches(code):
        left = PhoneVerification.MAX_ATTEMPTS - otp.attempts
        if left <= 0:
            return None, 'Trop de tentatives incorrectes. Demandez un nouveau code.'
        return None, f'Code incorrect. {left} tentative(s) restante(s).'
    otp.verified = True
    otp.save(update_fields=['verified'])
    return otp, None


def account_for_phone(phone):
    """Le compte (actif) dont ce numéro est confirmé, s'il y en a exactement un."""
    found = list(Account.objects.filter(phone_number=phone, phone_verified=True, is_active=True)[:2])
    return found[0] if len(found) == 1 else None
