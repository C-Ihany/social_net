from django.apps import AppConfig


class E2eeConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'e2ee'
    verbose_name = 'Chiffrement de bout en bout'
