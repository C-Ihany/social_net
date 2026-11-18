"""Messagerie de Pola côté Vazimba : connexion / inscription par numéro depuis Pola, choix
« Pola seulement » (invisible sur le réseau social) ou « Pola + communauté », trouver un
utilisateur de Pola par son numéro (18/11/2026)."""
import json
from unittest import mock

from django.core.cache import cache
from django.test import Client, TestCase, override_settings

from account.models import Account
from chat.models import PrivateChatRoom

SENT = []


def fake_send(to, code, channel='sms'):
    SENT.append((to, code, channel))
    return {'status': 'ok'}


@override_settings(DEBUG=True, WHATSAPP_TOKEN='', SMS_BACKEND='console')
@mock.patch('account.otp.send_otp', fake_send)
class PolaApiTests(TestCase):
    def setUp(self):
        cache.clear()
        SENT.clear()
        self.member = Account.objects.create_user('lova@example.com', 'lova', 'motdepasse-solide-123')
        self.member.phone_number, self.member.phone_verified = '+261341234567', True
        self.member.save()

    def post(self, client, path, body):
        return client.post(f'/api/pola/{path}', data=json.dumps(body), content_type='application/json')

    def sign_up(self, phone='+33612345678', name='Miora', mode='pola'):
        client = Client()
        self.assertEqual(client.get('/api/pola/bonjour').json()['me'], None)
        self.post(client, 'code', {'phone': phone})
        code = SENT[-1][1]
        response = self.post(client, 'verifier', {'code': code})
        self.assertEqual(response.json()['code'], 'NAME')          # (le nom manque : redemandé)
        data = self.post(client, 'verifier', {'code': code, 'name': name, 'mode': mode}).json()
        self.assertTrue(data['ok'] and data['created'])
        return client, Account.objects.get(phone_number=phone)

    def test_inscription_depuis_pola_par_numero(self):
        client, user = self.sign_up()
        self.assertEqual((user.username, user.pola_mode, user.phone_verified), ('Miora', 'pola', True))
        self.assertFalse(user.has_usable_password())
        self.assertTrue(user.email.endswith('@pola.vazimba.invalid'))
        self.assertEqual(client.get('/api/pola/bonjour').json()['me']['username'], 'Miora')
        self.assertGreater(client.session.get_expiry_age(), 100 * 24 * 3600)   # (session longue)

    def test_connexion_d_un_membre_existant(self):
        client = Client()
        client.get('/api/pola/bonjour')
        self.post(client, 'code', {'phone': '034 12 345 67', 'country': 'MG'})
        data = self.post(client, 'verifier', {'code': SENT[-1][1]}).json()
        self.assertEqual((data['created'], data['me']['username'], data['me']['mode']), (False, 'lova', 'community'))

    def test_membre_qui_demande_pola_seulement_reste_membre_et_le_sait(self):
        client = Client()
        client.get('/api/pola/bonjour')
        self.post(client, 'code', {'phone': '+261341234567'})
        data = self.post(client, 'verifier', {'code': SENT[-1][1], 'mode': 'pola'}).json()
        self.assertEqual((data['member'], data['me']['mode']), (True, 'community'))

    def test_pola_seulement_ne_liste_que_les_conversations_avec_pola(self):
        from chat.utils import find_or_create_private_chat
        client, miora = self.sign_up(mode='community')
        rado = Account.objects.create_user('rado@example.com', 'rado', 'motdepasse-solide-789')
        find_or_create_private_chat(miora, rado)                          # un membre du site seulement
        friend = Account.objects.create_user('hery@example.com', 'hery', 'motdepasse-solide-456')
        friend.pola_mode = 'pola'
        friend.save()
        find_or_create_private_chat(miora, friend)                        # un utilisateur de Pola
        names = lambda: sorted(c['person']['username'] for c in client.get('/api/pola/conversations').json()['conversations'])
        PrivateChatRoom.objects.update(is_active=True)
        self.assertEqual(names(), ["hery", "rado"])
        self.post(client, 'mode', {'mode': 'pola'})
        self.assertEqual(names(), ['hery'])
        self.assertEqual(PrivateChatRoom.objects.count(), 2)              # (rien n'est effacé)

    def test_pola_seulement_invisible_sur_le_reseau_social(self):
        _, hidden = self.sign_up()
        web = Client()
        web.force_login(self.member)
        self.assertEqual(web.get(f'/account/{hidden.pk}/').status_code, 404)           # profil
        self.assertEqual(web.get(f'/account/{self.member.pk}/').status_code, 200)      # (l'adresse est la bonne)
        self.assertNotIn('Miora', web.get('/search/?q=Mio').content.decode())         # recherche
        self.assertEqual(web.post('/chat/create_or_return_private_chat', {'user2_id': hidden.pk}).status_code, 403)
        self.assertEqual(web.post('/friend/friend_request/', {'receiver_user_id': hidden.pk}).status_code, 404)
        rado = Account.objects.create_user('rado@example.com', 'rado', 'motdepasse-solide-789')
        self.assertEqual(web.post('/friend/friend_request/', {'receiver_user_id': rado.pk}).status_code, 200)

    def test_pola_et_communaute_visible(self):
        _, open_user = self.sign_up(mode='community')
        web = Client()
        web.force_login(self.member)
        self.assertEqual(web.get(f'/account/{open_user.pk}/').status_code, 200)

    def test_trouver_par_numero_ouvre_une_conversation_secrete(self):
        miora_client, miora = self.sign_up()
        cache.clear()
        # Lova se connecte à Pola elle aussi
        lova = Client()
        lova.get('/api/pola/bonjour')
        self.post(lova, 'code', {'phone': '+261341234567'})
        self.post(lova, 'verifier', {'code': SENT[-1][1]})
        found = self.post(lova, 'trouver', {'phone': '+33 6 12 34 56 78'}).json()
        self.assertTrue(found['found'])
        self.assertEqual(found['person']['username'], 'Miora')
        room = PrivateChatRoom.objects.get(pk=found['room_id'])
        self.assertTrue(room.encrypted and room.is_active)
        # Maintenant qu'elles se parlent, Lova voit le profil de Miora (et elle seule)
        self.assertTrue(miora.visible_to(Account.objects.get(pk=self.member.pk)))
        convs = miora_client.get('/api/pola/conversations').json()['conversations']
        self.assertEqual([c['person']['username'] for c in convs], ['lova'])

    def test_un_membre_qui_n_utilise_pas_pola_n_est_pas_trouvable(self):
        client, _ = self.sign_up()
        other = Account.objects.create_user('rado@example.com', 'rado', 'motdepasse-solide-789')
        other.phone_number, other.phone_verified = '+261321112233', True
        other.save()
        self.assertFalse(self.post(client, 'trouver', {'phone': '+261321112233'}).json()['found'])

    def test_changer_de_choix(self):
        client, user = self.sign_up()
        self.assertEqual(self.post(client, 'mode', {'mode': 'community'}).json()['me']['mode'], 'community')
        user.refresh_from_db()
        self.assertFalse(user.hidden)
        self.assertEqual(self.post(client, 'mode', {'mode': 'n importe quoi'}).status_code, 400)

    def test_email_demande_pour_un_numero_inconnu_ne_trahit_rien(self):
        client = Client()
        client.get('/api/pola/bonjour')
        data = self.post(client, 'code', {'phone': '+4915123456789', 'channel': 'email'}).json()
        self.assertEqual(data['channel'], 'email')
        self.assertEqual(SENT, [])
