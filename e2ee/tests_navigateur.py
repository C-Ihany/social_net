"""Essai de bout en bout dans de VRAIS navigateurs (Chromium, par Playwright) : le moteur de
chiffrement du navigateur (static/js/e2ee/vz-e2ee.mjs) contre le serveur des clés (e2ee/views.py).

Lent (le moteur pèse 8 Mo) ; sauté si Playwright ou Chromium manquent (sur Railway, par exemple).
Lancer seul :  SECRET_KEY=essai-local DEBUG=True venv/bin/python manage.py test e2ee.tests_navigateur
"""
import os
import unittest

from django.conf import settings
from django.contrib.auth import SESSION_KEY, BACKEND_SESSION_KEY, HASH_SESSION_KEY
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings

from account.models import Account
from chat.models import PrivateChatRoom

os.environ.setdefault('DJANGO_ALLOW_ASYNC_UNSAFE', 'true')   # (Playwright tourne dans ce fil)
try:
    from playwright.sync_api import sync_playwright
except ImportError:                                           # pragma: no cover
    sync_playwright = None

MODULE = '/static/js/e2ee/vz-e2ee.mjs'


@unittest.skipIf(sync_playwright is None, 'Playwright absent')
@override_settings(STORAGES={**settings.STORAGES, 'staticfiles': {
    'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}})
class E2EEInBrowsersTests(StaticLiveServerTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.pw = sync_playwright().start()
        try:
            cls.browser = cls.pw.chromium.launch()
        except Exception as exc:                              # pragma: no cover
            cls.pw.stop()
            raise unittest.SkipTest(f'Chromium indisponible : {exc}')

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        super().tearDownClass()

    def setUp(self):
        self.lova = Account.objects.create_user('lova@example.com', 'lova', 'motdepasse-solide-123')
        self.miora = Account.objects.create_user('miora@example.com', 'miora', 'motdepasse-solide-456')
        self.room = PrivateChatRoom.objects.create(user1=self.lova, user2=self.miora)

    def device(self, user):
        """Un navigateur neuf (= un nouvel appareil), connecté au compte `user`, moteur ouvert."""
        session = SessionStore()
        session[SESSION_KEY] = str(user.pk)
        session[BACKEND_SESSION_KEY] = settings.AUTHENTICATION_BACKENDS[0]
        session[HASH_SESSION_KEY] = user.get_session_auth_hash()
        session.save()
        context = self.browser.new_context()
        context.add_cookies([{'name': settings.SESSION_COOKIE_NAME, 'value': session.session_key,
                              'url': self.live_server_url},
                             {'name': 'csrftoken', 'value': 'a' * 32, 'url': self.live_server_url}])
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(self.live_server_url + '/static/js/e2ee/vz-e2ee.mjs')   # (même origine)
        page.evaluate("""async ([module, pk]) => {
            const { VazimbaE2EE } = await import(module);
            window.e2ee = await VazimbaE2EE.open({ userPk: pk, csrf: 'a'.repeat(32) });
            window.VazimbaE2EE = VazimbaE2EE;
        }""", [MODULE, user.pk])
        self.assertEqual(errors, [])
        return page

    def encrypt(self, page, other, body):
        return page.evaluate("([room, other, body]) => window.e2ee.encrypt(room, other, { body })",
                             [self.room.pk, other.pk, body])

    def decrypt(self, page, msg_id, sender, ciphertext):
        return page.evaluate("""async ([room, id, sender, ct]) => {
            try { return (await window.e2ee.decrypt(room, { id, senderPk: sender, ts: Date.now(), ciphertext: ct })).content.body; }
            catch (e) { return 'ERREUR ' + (e.code || e.message); }
        }""", [self.room.pk, msg_id, sender.pk, ciphertext])

    def test_conversation_chiffree_de_bout_en_bout(self):
        lova, miora = self.device(self.lova), self.device(self.miora)

        ciphertext = self.encrypt(lova, self.miora, 'Salama Miora !')
        self.assertNotIn('Salama', ciphertext)                       # (le serveur ne voit que ça)
        self.assertIn('m.megolm.v1.aes-sha2', ciphertext)
        self.assertEqual(self.decrypt(miora, 1, self.lova, ciphertext), 'Salama Miora !')
        self.assertEqual(self.decrypt(lova, 1, self.lova, ciphertext), 'Salama Miora !')   # (ses propres messages)

        reply = self.encrypt(miora, self.lova, 'Salama Lova, manao ahoana ?')
        self.assertEqual(self.decrypt(lova, 2, self.miora, reply), 'Salama Lova, manao ahoana ?')

        # Un inconnu (autre compte, sans conversation) ne peut rien en tirer
        intrus_user = Account.objects.create_user('intrus@example.com', 'intrus', 'motdepasse-solide-789')
        intrus = self.device(intrus_user)
        self.assertEqual(self.decrypt(intrus, 2, self.miora, reply), 'ERREUR MISSING_KEY')

    def test_nouvel_appareil_retrouve_l_historique_avec_le_code_secret(self):
        lova, miora = self.device(self.lova), self.device(self.miora)
        lova.evaluate("() => window.e2ee.setupRecovery('mon code secret à moi')")
        ciphertext = self.encrypt(miora, self.lova, 'Message ancien')
        self.assertEqual(self.decrypt(lova, 1, self.miora, ciphertext), 'Message ancien')   # (clé reçue, sauvegardée)

        phone = self.device(self.lova)                                # nouveau téléphone de Lova
        self.assertEqual(self.decrypt(phone, 1, self.miora, ciphertext), 'ERREUR MISSING_KEY')
        wrong = phone.evaluate("""async () => {
            try { await window.e2ee.unlock('mauvais code'); return 'ouvert'; } catch (e) { return e.code; }
        }""")
        self.assertEqual(wrong, 'BAD_PASSPHRASE')
        phone.evaluate("() => window.e2ee.unlock('mon code secret à moi')")
        self.assertEqual(self.decrypt(phone, 1, self.miora, ciphertext), 'Message ancien')

    def test_fichier_chiffre(self):
        page = self.device(self.lova)
        result = page.evaluate("""() => {
            const original = new TextEncoder().encode('photo-secrète');
            const { data, info } = window.VazimbaE2EE.encryptFile(original);
            const back = window.VazimbaE2EE.decryptFile(data, info);
            return [new TextDecoder().decode(back), new TextDecoder().decode(data).includes('secrète')];
        }""")
        self.assertEqual(result, ['photo-secrète', False])
