"""Le service worker ne garde pas en cache les pages privées (messagerie, clés, connexion)."""
import re

from django.test import TestCase


class ServiceWorkerTests(TestCase):
    def setUp(self):
        self.js = self.client.get('/sw.js').content.decode()

    def test_servi_sans_cache_et_sans_balise_de_gabarit(self):
        response = self.client.get('/sw.js')
        self.assertEqual(response.status_code, 200)
        self.assertIn('no-store', response['Cache-Control'])
        self.assertNotIn('{%', self.js)
        self.assertNotIn('{{', self.js)

    def test_la_messagerie_n_est_jamais_gardee_en_cache(self):
        paths = re.search(r'const NO_CACHE_PATHS = \[(.*?)\];', self.js, re.S).group(1)
        for path in ("'/chat/'", "'/e2ee/'", "'/login/'", "'/admin/'"):
            self.assertIn(path, paths)
        # La liste sert vraiment : la mise en cache des pages la consulte (avant, elle était
        # déclarée mais jamais lue, et /chat/ partait dans le cache).
        html = self.js[self.js.index('function networkFirstHTML'):]
        html = html[:html.index('\n}\n')]
        self.assertIn('_isNoCachePath(', html)
        self.assertRegex(html, r'response\.ok && !noCache && !_isNoStore\(response\)')
        self.assertIn('if (noCache) return cache.match(OFFLINE_URL)', html)

    def test_refuser_un_appel_depuis_la_notification(self):
        # (POST sans jeton CSRF : la vue l'accepte, mais seulement d'une personne de la conversation)
        from account.models import Account
        from chat.models import PrivateChatRoom
        from django.test import Client
        a, b, c = (Account.objects.create_user(email=f'{n}@test.mg', username=n, password='x12345678')
                   for n in ('ana', 'ben', 'cle'))
        room = PrivateChatRoom.objects.create(user1=a, user2=b)
        url = f'/chat/call-reject-push/?room_id={room.pk}'
        for user, status in ((b, 200), (c, 404)):
            client = Client(enforce_csrf_checks=True)
            client.force_login(user)
            self.assertEqual(client.post(url).status_code, status)
            self.assertEqual(client.get(url).status_code, 405)
