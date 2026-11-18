"""Conversation secrète (chiffrement de bout en bout) côté serveur : activer, n'accepter que du
chiffré, ne jamais montrer le texte chiffré dans les aperçus (étape 2c, 18/11/2026)."""
import asyncio
import json
import time

from channels.testing import WebsocketCommunicator
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TransactionTestCase

from account.models import Account
from chat.constants import MSG_TYPE_SECRET, SECRET_PREVIEW
from chat.consumers import ChatConsumer
from chat.models import PrivateChatRoom, RoomChatMessage, UnreadChatRoomMessages

CIPHER = json.dumps({'algorithm': 'm.megolm.v1.aes-sha2', 'ciphertext': 'AwgAEnAB…', 'session_id': 'S1',
                     'sender_key': 'K', 'device_id': 'VZABC'})


def mk(name):
    return Account.objects.create_user(email=f'{name}@test.mg', username=name, password='x12345678')


class SecretRoomTests(TransactionTestCase):
    def setUp(self):
        self.a, self.b, self.c = mk('ana'), mk('ben'), mk('cle')
        self.room = PrivateChatRoom.objects.create(user1=self.a, user2=self.b, is_active=True)

    def client_of(self, user):
        client = Client()
        client.force_login(user)
        return client

    def comm(self, user):
        comm = WebsocketCommunicator(ChatConsumer.as_asgi(), '/chat/%d/' % self.room.id)
        comm.scope['user'] = user
        return comm

    async def drain(self, comm, want, timeout=2):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            try:
                data = await comm.receive_json_from(timeout=0.5)
            except Exception:
                continue
            if want(data):
                return data
        self.fail('trame attendue non reçue')

    def test_activer_seulement_dans_sa_conversation(self):
        self.assertEqual(self.client_of(self.c).post('/chat/secret/', {'room_id': self.room.id, 'on': '1'}).status_code, 404)
        self.assertEqual(self.client_of(self.b).post('/chat/secret/', {'room_id': self.room.id, 'on': '1'}).json(),
                         {'ok': True, 'encrypted': True})
        self.room.refresh_from_db()
        self.assertTrue(self.room.encrypted)

    def test_dans_une_conversation_secrete_seul_le_chiffre_passe(self):
        self.room.encrypted = True
        self.room.save()

        async def scenario():
            ca, cb = self.comm(self.a), self.comm(self.b)
            await ca.connect(); await cb.connect()
            await ca.send_json_to({'command': 'join', 'room': str(self.room.id)})
            joined = await self.drain(ca, lambda d: 'join' in d)
            self.assertTrue(joined['encrypted'])
            await cb.send_json_to({'command': 'join', 'room': str(self.room.id)})
            await self.drain(cb, lambda d: 'join' in d)
            # En clair : refusé
            await ca.send_json_to({'command': 'send', 'room': str(self.room.id), 'message': 'en clair'})
            error = await self.drain(ca, lambda d: d.get('error'))
            self.assertEqual(error['error'], 'SECRET_ROOM')
            # Chiffré : passe, et l'autre le reçoit avec son heure exacte
            await ca.send_json_to({'command': 'send', 'room': str(self.room.id), 'message': CIPHER, 'encrypted': True})
            got = await self.drain(cb, lambda d: d.get('msg_type') == 0)
            self.assertTrue(got['encrypted'])
            self.assertEqual(got['message'], CIPHER)
            self.assertIsInstance(got['ts'], int)
            # Du texte en clair déguisé en « chiffré » : refusé
            await ca.send_json_to({'command': 'send', 'room': str(self.room.id), 'message': 'coucou', 'encrypted': True})
            error = await self.drain(ca, lambda d: d.get('error'))
            self.assertEqual(error['error'], 'NOT_SECRET_ROOM')
            await ca.disconnect(); await cb.disconnect()
        asyncio.run(scenario())
        self.assertEqual(list(RoomChatMessage.objects.values_list('content', 'encrypted')), [(CIPHER, True)])

    def test_le_texte_chiffre_n_apparait_jamais_dans_les_apercus(self):
        self.room.encrypted = True
        self.room.save()

        async def scenario():
            ca = self.comm(self.a)
            await ca.connect()
            await ca.send_json_to({'command': 'join', 'room': str(self.room.id)})
            await self.drain(ca, lambda d: 'join' in d)
            await ca.send_json_to({'command': 'send', 'room': str(self.room.id), 'message': CIPHER, 'encrypted': True})
            await asyncio.sleep(0.3)
            await ca.disconnect()
        asyncio.run(scenario())
        unread = UnreadChatRoomMessages.objects.get(room=self.room, user=self.b)
        self.assertEqual(unread.most_recent_message, SECRET_PREVIEW)
        page = self.client_of(self.b).get('/chat/').content.decode()
        self.assertNotIn('megolm', page)

    def test_message_chiffre_refuse_hors_conversation_secrete(self):
        async def scenario():
            ca = self.comm(self.a)
            await ca.connect()
            await ca.send_json_to({'command': 'join', 'room': str(self.room.id)})
            await self.drain(ca, lambda d: 'join' in d)
            await ca.send_json_to({'command': 'send', 'room': str(self.room.id), 'message': CIPHER, 'encrypted': True})
            error = await self.drain(ca, lambda d: d.get('error'))
            self.assertEqual(error['error'], 'NOT_SECRET_ROOM')
            await ca.disconnect()
        asyncio.run(scenario())

    def test_fichier_chiffre(self):
        self.room.encrypted = True
        self.room.save()
        client = self.client_of(self.a)
        clear = client.post('/chat/upload_file/', {'room_id': self.room.id,
                                                   'file': SimpleUploadedFile('photo.jpg', b'x', 'image/jpeg')})
        self.assertEqual(clear.status_code, 400)                     # (en clair : refusé)
        sent = client.post('/chat/upload_file/', {
            'room_id': self.room.id, 'encrypted': '1', 'content': CIPHER, 'file_type': 'image',
            'file': SimpleUploadedFile('vacances.jpg', b'\x00charabia', 'application/octet-stream')}).json()
        self.assertEqual(sent['file_name'], '')                      # (le vrai nom reste secret)
        msg = RoomChatMessage.objects.get(pk=sent['msg_id'])
        self.assertTrue(msg.encrypted)
        self.assertNotIn('vacances', msg.file.name)
        self.assertEqual(msg.file_type, 'image')
        got = self.client_of(self.b).get(f'/chat/fichier/{msg.pk}/')
        self.assertEqual(b''.join(got.streaming_content), b'\x00charabia')
        self.assertIn('attachment', got['Content-Disposition'])     # (jamais affiché tel quel)

    def test_l_autre_est_prevenu_du_changement(self):
        ana = self.client_of(self.a)          # (connexion préparée hors de la boucle asynchrone)

        async def scenario():
            cb = self.comm(self.b)
            await cb.connect()
            await cb.send_json_to({'command': 'join', 'room': str(self.room.id)})
            await self.drain(cb, lambda d: 'join' in d)
            from channels.db import database_sync_to_async
            await database_sync_to_async(ana.post)('/chat/secret/', {'room_id': self.room.id, 'on': '1'})
            notice = await self.drain(cb, lambda d: d.get('msg_type') == MSG_TYPE_SECRET)
            self.assertEqual((notice['encrypted'], notice['username']), (True, 'ana'))
            await cb.disconnect()
        asyncio.run(scenario())
