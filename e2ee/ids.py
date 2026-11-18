"""
e2ee/ids.py
───────────
Le moteur de chiffrement des navigateurs (matrix-sdk-crypto-wasm, celui de Matrix / Element)
nomme les personnes et les conversations comme Matrix :
- une personne : « @42:vazimba.io » (42 = son numéro de compte) ;
- une conversation privée : « !7:vazimba.io » (7 = le numéro de la PrivateChatRoom).
Ces noms ne servent qu'au chiffrement ; Vazimba n'est PAS un serveur Matrix.
"""
import re

from django.conf import settings

SERVER = getattr(settings, 'E2EE_SERVER_NAME', 'vazimba.io')
_USER_RE = re.compile(r'^@(\d{1,12}):' + re.escape(SERVER) + r'$')
_ROOM_RE = re.compile(r'^!(\d{1,12}):' + re.escape(SERVER) + r'$')


def user_id(user_or_pk):
    pk = getattr(user_or_pk, 'pk', user_or_pk)
    return f'@{pk}:{SERVER}'


def user_pk(mxid):
    """Le numéro de compte d'un nom « @42:vazimba.io », ou None."""
    match = _USER_RE.match(mxid or '') if isinstance(mxid, str) else None
    return int(match.group(1)) if match else None


def room_id(room_or_pk):
    pk = getattr(room_or_pk, 'pk', room_or_pk)
    return f'!{pk}:{SERVER}'


def room_pk(rid):
    match = _ROOM_RE.match(rid or '') if isinstance(rid, str) else None
    return int(match.group(1)) if match else None
