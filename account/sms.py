"""
account/sms.py
──────────────
Envoi des codes de vérification (SMS, WhatsApp) et lecture des numéros de téléphone.

Numéros : TOUS les pays, avec la bibliothèque `phonenumbers` (les règles de numérotation de
chaque pays, tenues à jour par Google). Un numéro s'écrit au format international (+49…, +261…)
ou au format du pays choisi dans le formulaire ; il est gardé au format E.164.

SMS : Africa's Talking (SMS_BACKEND=africastalking). Les pays où le SMS est proposé se règlent
par SMS_COUNTRIES (vide = tous). En développement : console (le SMS s'affiche dans le terminal).
"""

import logging
import unicodedata
from functools import lru_cache
from typing import Optional

import phonenumbers
from phonenumbers import NumberParseException, PhoneNumberFormat, PhoneNumberType, geocoder
from django.conf import settings

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Numéros de téléphone (tous pays)
# ─────────────────────────────────────────────────────────────────────────────

# Les numéros qui reçoivent des SMS et WhatsApp. Les autres (surtaxés, gratuits, partagés…)
# sont refusés : des robots s'en servent pour faire payer les SMS au site (« SMS pumping »).
_TEXTABLE = (PhoneNumberType.MOBILE, PhoneNumberType.FIXED_LINE_OR_MOBILE)


def normalize_phone(raw: str, region: Optional[str] = None) -> Optional[str]:
    """Le numéro au format E.164 (+491511234567), ou None s'il n'est pas valable.

    `region` : le pays choisi (« DE », « MG », « FR »…), pour un numéro écrit sans indicatif.
    Un numéro qui commence par + ou 00 n'en a pas besoin. Seuls les numéros de mobile passent."""
    raw = (raw or '').strip()
    if not raw:
        return None
    if raw.startswith('00'):
        raw = '+' + raw[2:]
    try:
        number = phonenumbers.parse(raw, (region or '').upper() or None)
    except NumberParseException:
        return None
    if not phonenumbers.is_valid_number(number) or phonenumbers.number_type(number) not in _TEXTABLE:
        return None
    return phonenumbers.format_number(number, PhoneNumberFormat.E164)


def tidy_phone(raw: str, region: Optional[str] = None) -> Optional[str]:
    """Le numéro au format E.164 s'il est valable (mobile ou non), sinon None. Pour ranger un
    numéro écrit à la main (administration, anciens comptes) dans le format que cherche le site."""
    raw = (raw or '').strip()
    if raw.startswith('00'):
        raw = '+' + raw[2:]
    try:
        number = phonenumbers.parse(raw, (region or '').upper() or None)
    except NumberParseException:
        return None
    if not phonenumbers.is_valid_number(number):
        return None
    return phonenumbers.format_number(number, PhoneNumberFormat.E164)


def region_of(e164: str) -> str:
    """Le pays d'un numéro E.164 (« DE »), ou '' s'il est illisible."""
    try:
        return phonenumbers.region_code_for_number(phonenumbers.parse(e164 or '')) or ''
    except NumberParseException:
        return ''


def format_phone_display(e164: str) -> str:
    """Le numéro tel qu'on l'écrit : +49 1512 3456789, +261 34 12 345 67…"""
    try:
        return phonenumbers.format_number(phonenumbers.parse(e164 or ''), PhoneNumberFormat.INTERNATIONAL)
    except NumberParseException:
        return e164 or ''


@lru_cache(maxsize=8)
def country_choices(lang: str = 'fr') -> tuple:
    """Tous les pays pour la liste du formulaire : ((« DE », « Allemagne (+49) »), …), triés par nom.
    (Le malgache n'a pas de noms de pays dans phonenumbers : ce sont alors les noms français.)"""
    lang = 'fr' if lang in ('fr', 'mg') else 'en'
    choices = []
    for region in phonenumbers.SUPPORTED_REGIONS:
        example = phonenumbers.example_number(region)
        if example is None:
            continue
        name = geocoder.country_name_for_number(example, lang) or region
        choices.append((region, f'{name} (+{example.country_code})'))
    plain = lambda text: unicodedata.normalize('NFD', text).encode('ascii', 'ignore').decode().lower()
    return tuple(sorted(choices, key=lambda c: plain(c[1])))


def sms_allowed(e164: str) -> bool:
    """Vrai si le SMS est proposé vers ce pays (SMS_COUNTRIES, vide = tous les pays)."""
    countries = [c.strip().upper() for c in getattr(settings, 'SMS_COUNTRIES', []) if c.strip()]
    return not countries or region_of(e164) in countries


# ─────────────────────────────────────────────────────────────────────────────
# Backends SMS
# ─────────────────────────────────────────────────────────────────────────────

def _send_via_console(to: str, message: str) -> dict:
    """Backend développement : affiche le SMS dans les logs Django."""
    logger.info(
        '\n' + '=' * 60 +
        f'\n[SMS CONSOLE] To: {to}\n{message}\n' +
        '=' * 60
    )
    print(f'\n[SMS] To: {to}\n{message}\n')
    return {'status': 'ok', 'backend': 'console'}


def _send_via_africastalking(to: str, message: str) -> dict:
    """Backend production : Africa's Talking SMS API."""
    try:
        import africastalking
    except ImportError:
        logger.error('[SMS] africastalking non installé — pip install africastalking')
        raise RuntimeError('Package africastalking manquant.')

    username = getattr(settings, 'AT_USERNAME', 'sandbox')
    api_key  = getattr(settings, 'AT_API_KEY',  'atsk_sandbox_key')
    sender   = getattr(settings, 'AT_SENDER',   None)

    africastalking.initialize(username, api_key)
    sms = africastalking.SMS

    kwargs = {'message': message, 'recipients': [to]}
    if sender:
        kwargs['sender_id'] = sender

    response = sms.send(**kwargs)
    logger.info('[SMS] Africa\'s Talking response: %s', response)

    # Vérifier qu'au moins un message est "Success"
    recipients = response.get('SMSMessageData', {}).get('Recipients', [])
    if not recipients:
        raise RuntimeError(f'Africa\'s Talking : aucun destinataire dans la réponse — {response}')

    status = recipients[0].get('status', '')
    if status not in ('Success', 'success'):
        raise RuntimeError(f'Africa\'s Talking : statut inattendu "{status}" — {response}')

    return {'status': 'ok', 'backend': 'africastalking', 'at_response': response}


# ─────────────────────────────────────────────────────────────────────────────
# Point d'entrée public
# ─────────────────────────────────────────────────────────────────────────────

def send_otp_sms(to: str, code: str) -> dict:
    """
    Envoie le code OTP par SMS au numéro `to` (format E.164).
    Sélectionne automatiquement le backend selon SMS_BACKEND dans settings.py.

    Raises:
        RuntimeError: si l'envoi échoue côté fournisseur.
    """
    message = (
        f'Votre code Vazimba : {code}\n'
        f'Valable 10 minutes. Ne le partagez jamais.'
    )

    backend = getattr(settings, 'SMS_BACKEND', 'console')

    if backend == 'africastalking':
        return _send_via_africastalking(to, message)
    else:
        # Fallback console (développement ou backend inconnu)
        return _send_via_console(to, message)


# ─────────────────────────────────────────────────────────────────────────────
# WhatsApp
# ─────────────────────────────────────────────────────────────────────────────

def _send_via_whatsapp(to: str, code: str) -> dict:
    """Le code par WhatsApp, avec l'API officielle de Meta (WhatsApp Cloud API).

    Il faut un modèle de message « Authentification » approuvé par Meta (WHATSAPP_TEMPLATE,
    en français), avec le bouton « Copier le code » : c'est la seule forme de message que
    WhatsApp laisse envoyer à quelqu'un qui n'a pas écrit en premier. Réglages :
    WHATSAPP_TOKEN, WHATSAPP_PHONE_ID (identifiant du numéro expéditeur chez Meta)."""
    import requests
    token = getattr(settings, 'WHATSAPP_TOKEN', '')
    phone_id = getattr(settings, 'WHATSAPP_PHONE_ID', '')
    if not token or not phone_id:
        raise RuntimeError('WhatsApp non configuré (WHATSAPP_TOKEN, WHATSAPP_PHONE_ID).')
    body = {
        'messaging_product': 'whatsapp',
        'to': to.lstrip('+'),
        'type': 'template',
        'template': {
            'name': getattr(settings, 'WHATSAPP_TEMPLATE', 'code_vazimba'),
            'language': {'code': getattr(settings, 'WHATSAPP_LANG', 'fr')},
            'components': [
                {'type': 'body', 'parameters': [{'type': 'text', 'text': code}]},
                # (le bouton « Copier le code » des modèles d'authentification reçoit le code aussi)
                {'type': 'button', 'sub_type': 'url', 'index': '0',
                 'parameters': [{'type': 'text', 'text': code}]},
            ],
        },
    }
    response = requests.post(
        f'https://graph.facebook.com/{getattr(settings, "WHATSAPP_API_VERSION", "v21.0")}/{phone_id}/messages',
        json=body, headers={'Authorization': f'Bearer {token}'}, timeout=15,
    )
    if response.status_code >= 300:
        # (le corps de la réponse dit pourquoi ; jamais le jeton dans le journal)
        raise RuntimeError(f'WhatsApp : erreur {response.status_code} — {response.text[:300]}')
    return {'status': 'ok', 'backend': 'whatsapp'}


def otp_channels() -> list:
    """Les moyens d'envoi du code proposés : WhatsApp s'il est configuré, le SMS si un
    fournisseur l'est. En développement, les deux (le code s'affiche dans le terminal)."""
    channels = []
    if getattr(settings, 'WHATSAPP_TOKEN', '') or settings.DEBUG:
        channels.append('whatsapp')
    if getattr(settings, 'SMS_BACKEND', 'console') != 'console' or settings.DEBUG:
        channels.append('sms')
    return channels


def send_otp(to: str, code: str, channel: str = 'sms') -> dict:
    """Envoie le code par le moyen choisi (« sms » ou « whatsapp »). En développement (aucun
    fournisseur réglé), le code s'affiche dans le terminal de Django."""
    if channel == 'whatsapp':
        if not getattr(settings, 'WHATSAPP_TOKEN', '') and settings.DEBUG:
            return _send_via_console(to, f'[WhatsApp] Votre code Vazimba : {code}')
        return _send_via_whatsapp(to, code)
    return send_otp_sms(to, code)
