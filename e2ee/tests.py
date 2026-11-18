"""Serveur des clés du chiffrement de bout en bout (étape 2 de la sécurité, 18/11/2026)."""
import json

from django.core.cache import cache
from django.test import Client, TestCase

from account.models import Account
from chat.models import PrivateChatRoom
from e2ee import ids
from e2ee.models import Device, OneTimeKey, ToDeviceMessage


def device_keys(user, device_id, curve='C' * 43, ed='E' * 43):
    return {'user_id': ids.user_id(user), 'device_id': device_id,
            'algorithms': ['m.olm.v1.curve25519-aes-sha2', 'm.megolm.v1.aes-sha2'],
            'keys': {f'curve25519:{device_id}': curve, f'ed25519:{device_id}': ed},
            'signatures': {ids.user_id(user): {f'ed25519:{device_id}': 'sig'}}}


class E2eeServerTests(TestCase):
    def setUp(self):
        cache.clear()
        self.lova = Account.objects.create_user('lova@example.com', 'lova', 'motdepasse-solide-123')
        self.miora = Account.objects.create_user('miora@example.com', 'miora', 'motdepasse-solide-456')
        self.intrus = Account.objects.create_user('intrus@example.com', 'intrus', 'motdepasse-solide-789')
        self.room = PrivateChatRoom.objects.create(user1=self.lova, user2=self.miora)

    def call(self, user, device, method, path, body=None):
        client = Client()
        client.force_login(user)
        kwargs = {'HTTP_X_E2EE_DEVICE': device}
        if body is not None:
            kwargs.update(data=json.dumps(body), content_type='application/json')
        response = getattr(client, method)(f'/e2ee/{path}', **kwargs)
        return response.status_code, (response.json() if response.content else {})

    def upload(self, user, device, otks=2, fallback=True):
        body = {'device_keys': device_keys(user, device),
                'one_time_keys': {f'signed_curve25519:K{i}': {'key': f'k{i}'} for i in range(otks)}}
        if fallback:
            body['fallback_keys'] = {'signed_curve25519:F1': {'key': 'f1', 'fallback': True}}
        return self.call(user, device, 'post', 'keys/upload', body)

    def test_publier_ses_cles(self):
        status, data = self.upload(self.lova, 'LOVA1', otks=3)
        self.assertEqual(status, 200)
        self.assertEqual(data['one_time_key_counts'], {'signed_curve25519': 3})

    def test_on_ne_publie_pas_au_nom_d_un_autre(self):
        status, _ = self.call(self.lova, 'LOVA1', 'post', 'keys/upload', {'device_keys': device_keys(self.miora, 'LOVA1')})
        self.assertEqual(status, 400)
        self.assertFalse(Device.objects.exists())

    def test_les_cles_d_identite_ne_changent_pas(self):
        self.upload(self.lova, 'LOVA1')
        body = {'device_keys': device_keys(self.lova, 'LOVA1', curve='X' * 43)}
        status, _ = self.call(self.lova, 'LOVA1', 'post', 'keys/upload', body)
        self.assertEqual(status, 400)

    def test_cles_lues_par_un_contact_mais_pas_par_un_inconnu(self):
        self.upload(self.lova, 'LOVA1')
        _, seen = self.call(self.miora, 'MIO1', 'post', 'keys/query', {'device_keys': {ids.user_id(self.lova): []}})
        self.assertIn('LOVA1', seen['device_keys'][ids.user_id(self.lova)])
        _, hidden = self.call(self.intrus, 'INT1', 'post', 'keys/query', {'device_keys': {ids.user_id(self.lova): []}})
        self.assertEqual(hidden['device_keys'], {})

    def test_une_cle_a_usage_unique_ne_sert_qu_une_fois(self):
        self.upload(self.lova, 'LOVA1', otks=1)
        ask = {'one_time_keys': {ids.user_id(self.lova): {'LOVA1': 'signed_curve25519'}}}
        _, first = self.call(self.miora, 'MIO1', 'post', 'keys/claim', ask)
        _, second = self.call(self.miora, 'MIO1', 'post', 'keys/claim', ask)
        self.assertEqual(list(first['one_time_keys'][ids.user_id(self.lova)]['LOVA1']), ['signed_curve25519:K0'])
        # (plus de clé à usage unique : la clé de secours prend le relais)
        self.assertEqual(list(second['one_time_keys'][ids.user_id(self.lova)]['LOVA1']), ['signed_curve25519:F1'])
        _, nothing = self.call(self.intrus, 'INT1', 'post', 'keys/claim', ask)
        self.assertEqual(nothing['one_time_keys'], {})

    def test_boite_aux_lettres(self):
        self.upload(self.lova, 'LOVA1')
        self.upload(self.miora, 'MIO1')
        self.upload(self.intrus, 'INT1')
        message = {'messages': {ids.user_id(self.lova): {'LOVA1': {'ciphertext': 'xyz'}}}}
        self.call(self.miora, 'MIO1', 'put', 'sendToDevice/m.room.encrypted/t1', message)
        self.call(self.miora, 'MIO1', 'put', 'sendToDevice/m.room.encrypted/t1', message)   # (renvoyé : une fois)
        self.call(self.intrus, 'INT1', 'put', 'sendToDevice/m.room.encrypted/t9', message)  # (pas un contact)
        status, data = self.call(self.lova, 'LOVA1', 'get', 'sync')
        self.assertEqual(status, 200)
        self.assertEqual(data['to_device']['events'],
                         [{'type': 'm.room.encrypted', 'sender': ids.user_id(self.miora), 'content': {'ciphertext': 'xyz'}}])
        self.call(self.lova, 'LOVA1', 'get', f"sync?ack={data['ack']}")
        self.assertFalse(ToDeviceMessage.objects.exists())

    def test_nouvel_appareil_d_un_contact_signale(self):
        self.upload(self.lova, 'LOVA1')
        _, first = self.call(self.lova, 'LOVA1', 'get', 'sync')
        self.upload(self.miora, 'MIO2')
        self.upload(self.intrus, 'INT1')
        _, then = self.call(self.lova, 'LOVA1', 'get', f"sync?since={first['since']}")
        self.assertEqual(then['device_lists']['changed'], [ids.user_id(self.miora)])

    def test_changer_d_identite_demande_le_mot_de_passe(self):
        master = {'user_id': ids.user_id(self.lova), 'usage': ['master'], 'keys': {'ed25519:M1': 'M1'}}
        status, _ = self.call(self.lova, 'LOVA1', 'post', 'keys/device_signing/upload', {'master_key': master})
        self.assertEqual(status, 200)
        other = dict(master, keys={'ed25519:M2': 'M2'})
        status, _ = self.call(self.lova, 'LOVA1', 'post', 'keys/device_signing/upload', {'master_key': other})
        self.assertEqual(status, 401)
        status, _ = self.call(self.lova, 'LOVA1', 'post', 'keys/device_signing/upload',
                              {'master_key': other, 'auth': {'password': 'motdepasse-solide-123'}})
        self.assertEqual(status, 200)

    def test_sauvegarde_chiffree(self):
        _, created = self.call(self.lova, 'LOVA1', 'post', 'room_keys/version',
                               {'algorithm': 'm.megolm_backup.v1.curve25519-aes-sha2', 'auth_data': {'public_key': 'P'}})
        version = created['version']
        mine, other = ids.room_id(self.room), ids.room_id(9999)
        body = {'rooms': {mine: {'sessions': {'S1': {'first_message_index': 0, 'session_data': {'c': 1}}}},
                          other: {'sessions': {'S2': {'first_message_index': 0, 'session_data': {'c': 2}}}}}}
        status, data = self.call(self.lova, 'LOVA1', 'put', f'room_keys/keys?version={version}', body)
        self.assertEqual((status, data['count']), (200, 1))          # (pas les conversations des autres)
        _, back = self.call(self.lova, 'LOVA1', 'get', f'room_keys/keys?version={version}')
        self.assertEqual(list(back['rooms']), [mine])
        status, _ = self.call(self.miora, 'MIO1', 'get', f'room_keys/keys?version={version}')
        self.assertEqual(status, 403)

    def test_code_secret_enregistre_chiffre(self):
        weak = {'salt': 's', 'iv': 'i', 'ciphertext': 'c', 'iterations': 1000}
        self.assertEqual(self.call(self.lova, 'LOVA1', 'put', 'recovery', weak)[0], 400)
        good = dict(weak, iterations=600000, v=1)
        self.assertEqual(self.call(self.lova, 'LOVA1', 'put', 'recovery', good)[0], 200)
        self.assertEqual(self.call(self.lova, 'LOVA1', 'get', 'recovery')[1]['iterations'], 600000)
        self.assertEqual(self.call(self.miora, 'MIO1', 'get', 'recovery')[0], 404)

    def test_connexion_et_jeton_csrf_obligatoires(self):
        self.assertEqual(Client().get('/e2ee/sync').status_code, 401)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.lova)
        response = client.post('/e2ee/keys/upload', data='{}', content_type='application/json',
                               HTTP_X_E2EE_DEVICE='LOVA1')
        self.assertEqual(response.status_code, 403)
