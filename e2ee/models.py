"""
e2ee/models.py
──────────────
Ce que le serveur garde pour le chiffrement de bout en bout. RIEN de tout cela ne permet de lire
un message : ce sont les clés PUBLIQUES des appareils, des messages déjà chiffrés d'appareil à
appareil (« boîte aux lettres »), et une sauvegarde des clés chiffrée avec le code secret du membre.
Les clés secrètes ne quittent jamais l'appareil (IndexedDB du navigateur).
"""
from django.conf import settings
from django.db import models


class Device(models.Model):
    """Un appareil (navigateur, appli) d'un membre, avec ses clés publiques (format Matrix)."""
    user       = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='e2ee_devices')
    device_id  = models.CharField(max_length=64)
    keys       = models.JSONField(default=dict)            # device_keys signées par l'appareil
    name       = models.CharField(max_length=80, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen  = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('user', 'device_id')

    def __str__(self):
        return f'{self.user_id}/{self.device_id}'


class OneTimeKey(models.Model):
    """Clés à usage unique d'un appareil (et sa clé de secours, « fallback »), pour ouvrir une
    session chiffrée avec lui. Chaque clé à usage unique est donnée une seule fois puis effacée."""
    device    = models.ForeignKey(Device, on_delete=models.CASCADE, related_name='one_time_keys')
    algorithm = models.CharField(max_length=40)
    key_id    = models.CharField(max_length=80)
    key       = models.JSONField()
    fallback  = models.BooleanField(default=False)
    used      = models.BooleanField(default=False)          # (pour une clé de secours seulement)

    class Meta:
        # (une clé de secours peut porter le même nom qu'une clé à usage unique : deux séries à part)
        unique_together = ('device', 'algorithm', 'key_id', 'fallback')


class ToDeviceMessage(models.Model):
    """Boîte aux lettres d'appareil à appareil : le contenu est chiffré pour l'appareil destinataire
    (ou ce sont des messages de vérification). Effacé dès que l'appareil l'a reçu."""
    recipient        = models.ForeignKey(Device, on_delete=models.CASCADE, related_name='inbox')
    sender           = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='+')
    sender_device_id = models.CharField(max_length=64, blank=True, default='')
    type             = models.CharField(max_length=80)
    content          = models.JSONField()
    txn_id           = models.CharField(max_length=80, blank=True, default='')
    created_at       = models.DateTimeField(auto_now_add=True)


class DeviceListChange(models.Model):
    """Journal : « les appareils de ce membre ont changé » (nouvel appareil, clés changées). Les
    autres appareils le lisent pour aller rechercher ses clés ; le numéro sert de repère."""
    user       = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)


class CrossSigningKeys(models.Model):
    """Clés de signature croisée d'un membre (publiques) : elles attestent que ses appareils sont
    bien à lui, et servent à la vérification des contacts (étape 3)."""
    user          = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='e2ee_cross_signing')
    master        = models.JSONField(null=True, blank=True)
    self_signing  = models.JSONField(null=True, blank=True)
    user_signing  = models.JSONField(null=True, blank=True)  # (montrée à son propriétaire seulement)
    updated_at    = models.DateTimeField(auto_now=True)


class PeerSignature(models.Model):
    """Signature posée par un membre sur la clé maîtresse d'un autre (« j'ai vérifié cette
    personne »). Montrée seulement à celui qui l'a posée."""
    signer     = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='+')
    target     = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='+')
    key_id     = models.CharField(max_length=120)
    signature  = models.TextField()

    class Meta:
        unique_together = ('signer', 'target', 'key_id')


class KeyBackupVersion(models.Model):
    """Une sauvegarde des clés de conversation d'un membre. Les clés y sont chiffrées pour une clé
    de sauvegarde que seul le membre peut ouvrir (avec son code secret)."""
    user       = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='e2ee_backups')
    algorithm  = models.CharField(max_length=80)
    auth_data  = models.JSONField()
    deleted    = models.BooleanField(default=False)
    etag       = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)


class BackedUpRoomKey(models.Model):
    backup     = models.ForeignKey(KeyBackupVersion, on_delete=models.CASCADE, related_name='keys')
    room_id    = models.CharField(max_length=80)
    session_id = models.CharField(max_length=120)
    data       = models.JSONField()

    class Meta:
        unique_together = ('backup', 'room_id', 'session_id')


class RecoverySecret(models.Model):
    """La clé de sauvegarde, chiffrée DANS LE NAVIGATEUR avec une clé tirée du code secret du
    membre (PBKDF2 + AES-GCM). Le serveur ne voit ni le code ni la clé."""
    user       = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='e2ee_recovery')
    blob       = models.JSONField()
    updated_at = models.DateTimeField(auto_now=True)
