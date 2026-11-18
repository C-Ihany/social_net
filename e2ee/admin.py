from django.contrib import admin

from e2ee.models import Device


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    """Appareils du chiffrement de bout en bout (clés publiques seulement : rien n'y est lisible)."""
    list_display = ('user', 'device_id', 'created_at', 'last_seen')
    search_fields = ('user__username', 'device_id')
    readonly_fields = ('user', 'device_id', 'keys', 'created_at', 'last_seen')
