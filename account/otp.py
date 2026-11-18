"""
account/otp.py
──────────────
Les codes à usage unique envoyés par SMS ou WhatsApp : les fabriquer, les envoyer, les vérifier.
Servent à confirmer le numéro d'un compte (« verify ») et à se connecter avec son numéro
(« login »).

Protections :
- code de 6 chiffres tiré par `secrets`, valable 10 minutes, 5 essais au plus ;
- seule l'EMPREINTE du code est gardée en base (PhoneVerification.digest) ;
- 3 envois par numéro et par heure (ici), et des limites par adresse IP (dans les urls.py) ;
- par SMS, seulement des numéros malgaches (un SMS vers l'étranger coûte cher, et des robots
  s'en servent pour faire payer le site) ; par WhatsApp, tous les numéros.
"""
import logging
from datetime import timedelta

from django.utils import timezone

from account.models import Account, PhoneVerification
from account.sms import normalize_phone, otp_channels, send_otp

logger = logging.getLogger(__name__)


def read_phone(raw, channel):
    """Le numéro au format E.164, ou None. À l'étranger, seulement par WhatsApp."""
    return normalize_phone(raw or '', international=(channel == 'whatsapp'))


def pick_channel(asked):
    """Le moyen d'envoi demandé s'il est proposé, sinon le premier proposé."""
    channels = otp_channels()
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
        send_otp(phone, code, channel)
    except Exception as exc:  # noqa: BLE001 - le fournisseur a refusé ou ne répond pas
        logger.error('[OTP] Envoi par %s échoué vers %s : %s', channel, phone, exc)
        otp.delete()          # (ne pas garder un code qui n'est pas parti)
        return "L'envoi du code a échoué. Vérifiez le numéro et réessayez."
    return None


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
