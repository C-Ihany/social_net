from django.urls import path

from ZOOT.ratelimit import ratelimit
from e2ee import views

app_name = 'e2ee'

# (limites larges : un appareil fait plusieurs demandes à chaque message chiffré)
_L = lambda view, rate='600/m': ratelimit(rate, methods=('GET', 'POST', 'PUT', 'DELETE'))(view)

urlpatterns = [
    path('keys/upload', _L(views.keys_upload), name='keys-upload'),
    path('keys/query', _L(views.keys_query), name='keys-query'),
    path('keys/claim', _L(views.keys_claim), name='keys-claim'),
    path('keys/device_signing/upload', _L(views.device_signing_upload, '20/m'), name='device-signing'),
    path('keys/signatures/upload', _L(views.signatures_upload, '60/m'), name='signatures'),
    path('sendToDevice/<str:event_type>/<str:txn_id>', _L(views.send_to_device), name='send-to-device'),
    path('sync', _L(views.sync), name='sync'),
    path('devices', _L(views.my_devices), name='devices'),
    path('devices/<str:device_id>', _L(views.delete_device, '30/m'), name='device'),
    path('room_keys/version', _L(views.backup_version, '60/m'), name='backup-version'),
    path('room_keys/keys', _L(views.backup_keys), name='backup-keys'),
    path('recovery', _L(views.recovery, '30/m'), name='recovery'),
]
