"""
account/sms.py
──────────────
Backend SMS pour Vazimba — vérification de numéro de téléphone.

Fournisseur principal : Africa's Talking (couverture Madagascar : Airtel, Orange, Telma)
Backend développement : console (affiche le SMS dans le terminal, aucun envoi réel)

Normalisation des numéros malgaches :
  034 XX XXX XX  →  +26134XXXXXXX
  032 XX XXX XX  →  +26132XXXXXXX
  Formats acceptés : 034..., 0034..., +261 34..., 261 34...
"""

import logging
import re
from typing import Optional

from django.conf import settings

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Normalisation du numéro de téléphone
# ─────────────────────────────────────────────────────────────────────────────

_MADAGASCAR_PREFIXES = ('32', '33', '34', '38', '20')


def normalize_madagascar_phone(raw: str) -> Optional[str]:
    """
    Convertit un numéro saisi librement en format E.164 (+261XXXXXXXXX).
    Retourne None si le numéro n'est pas reconnaissable.

    Exemples acceptés :
        034 12 345 67  →  +261341234567
        0341234567     →  +261341234567
        +261 34 12 345 67  →  +261341234567
        261341234567   →  +261341234567
    """
    if not raw:
        return None

    # Supprimer espaces, tirets, points, parenthèses
    digits = re.sub(r'[\s\-\.\(\)]', '', raw)

    # Supprimer le + initial si présent
    if digits.startswith('+'):
        digits = digits[1:]

    # Forme internationale : 261XXXXXXXXX (12 chiffres)
    if digits.startswith('261') and len(digits) == 12:
        local = digits[3:]  # les 9 chiffres après 261
        prefix2 = local[:2]
        if prefix2 in _MADAGASCAR_PREFIXES:
            return '+' + digits

    # Forme locale commençant par 0 : 0XXXXXXXXX (10 chiffres)
    if digits.startswith('0') and len(digits) == 10:
        local = digits[1:]  # sans le 0 initial
        prefix2 = local[:2]
        if prefix2 in _MADAGASCAR_PREFIXES:
            return '+261' + local

    # Forme avec 00 international : 00261XXXXXXXXX (14 chiffres)
    if digits.startswith('00261') and len(digits) == 14:
        local = digits[5:]
        prefix2 = local[:2]
        if prefix2 in _MADAGASCAR_PREFIXES:
            return '+261' + local

    return None


def format_phone_display(e164: str) -> str:
    """
    Formate un numéro E.164 pour l'affichage.
    +261341234567 → +261 34 12 345 67
    """
    if not e164 or not e164.startswith('+261') or len(e164) != 13:
        return e164
    d = e164[4:]   # 9 chiffres
    return f'+261 {d[:2]} {d[2:4]} {d[4:7]} {d[7:]}'


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
# Numéros étrangers et WhatsApp
# ─────────────────────────────────────────────────────────────────────────────
# Le code peut aussi partir par WhatsApp : utile à l'étranger (le SMS malgache n'y arrive pas,
# WhatsApp oui) et moins cher. Par SMS, seuls les numéros malgaches sont acceptés : un SMS vers
# l'étranger coûte cher, et des robots s'en servent pour faire payer le site (« SMS pumping »).

def normalize_phone(raw: str, international: bool = False) -> Optional[str]:
    """Le numéro au format E.164. Un numéro malgache s'écrit librement (034…, +261…) ;
    avec international=True, un numéro étranger est accepté s'il commence par + ou 00
    (indicatif du pays) et compte de 8 à 15 chiffres."""
    local = normalize_madagascar_phone(raw)
    if local or not international or not raw:
        return local
    digits = re.sub(r'[\s\-\.\(\)]', '', raw)
    if digits.startswith('00'):
        digits = '+' + digits[2:]
    if re.fullmatch(r'\+[1-9]\d{7,14}', digits):
        return digits
    return None


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
