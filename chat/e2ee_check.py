"""Vérifie qu'un message annoncé « chiffré » a bien la forme d'un message Megolm (le serveur ne
peut pas le lire, mais il refuse du texte en clair déguisé, ou un contenu démesuré)."""
import json

MAX_CIPHERTEXT = 64 * 1024


def is_ciphertext(text):
    if not isinstance(text, str) or len(text) > MAX_CIPHERTEXT:
        return False
    try:
        data = json.loads(text)
    except ValueError:
        return False
    return (isinstance(data, dict) and data.get('algorithm') == 'm.megolm.v1.aes-sha2'
            and isinstance(data.get('ciphertext'), str) and isinstance(data.get('session_id'), str))


def ms(timestamp):
    """L'heure d'un message en millisecondes (le moteur de chiffrement en a besoin, toujours la même)."""
    return int(timestamp.timestamp() * 1000)
