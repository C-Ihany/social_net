"""Les adresses que Pola (l'assistant de bureau) appelle : voir account/pola_api.py."""
from django.urls import path

from ZOOT.ratelimit import ratelimit
from account import pola_api

app_name = 'pola'

urlpatterns = [
    path('bonjour', ratelimit('60/m', methods=('GET',))(pola_api.hello), name='hello'),
    path('code', ratelimit('6/h', key='ip')(pola_api.request_code), name='code'),
    path('verifier', ratelimit('20/h', key='ip')(pola_api.verify_code), name='verify'),
    path('mode', ratelimit('20/h')(pola_api.set_mode), name='mode'),
    # (trouver par numéro : limité, pour qu'on ne puisse pas essayer tous les numéros)
    path('trouver', ratelimit('30/h')(pola_api.find_by_phone), name='find'),
    path('conversations', ratelimit('120/m', methods=('GET',))(pola_api.conversations), name='conversations'),
    path('deconnexion', pola_api.sign_out, name='sign-out'),
]
