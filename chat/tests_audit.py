"""Corrections de l'audit du 22/11/2026 : conversation listée dès le premier message, long message
vers quelqu'un d'absent, blocage respecté partout, aperçu jamais interprété comme du HTML."""
import asyncio
import time

from channels.testing import WebsocketCommunicator
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TransactionTestCase

from account.models import Account, UserBlock
from chat.consumers import ChatConsumer
from chat.models import PREVIEW_MAX, PrivateChatRoom, RoomChatMessage, UnreadChatRoomMessages
from notification.models import Notification


def mk(name):
    return Account.objects.create_user(email=f'{name}@test.mg', username=name, password='x12345678')


class Base(TransactionTestCase):
    def setUp(self):
        self.a, self.b = mk('ana'), mk('ben')

    def client_of(self, user):
        client = Client()
        client.force_login(user)
        return client

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

    def send(self, user, room, text):
        """`user` rejoint `room`, envoie `text`, et rend la première trame de message ou d'erreur."""
        async def scenario():
            comm = WebsocketCommunicator(ChatConsumer.as_asgi(), '/chat/%d/' % room.id)
            comm.scope['user'] = user
            await comm.connect()
            await comm.send_json_to({'command': 'join', 'room': str(room.id)})
            await self.drain(comm, lambda d: 'join' in d)
            await comm.send_json_to({'command': 'send', 'room': str(room.id), 'message': text})
            got = await self.drain(comm, lambda d: d.get('msg_type') == 0 or d.get('error'))
            await comm.disconnect()
            return got
        return asyncio.run(scenario())


class ConversationListTests(Base):
    def test_listee_des_le_premier_message(self):
        # Ouverte depuis un profil ou une annonce : pas encore « active », mais montrée à celui qui l'ouvre
        page = self.client_of(self.a).get(f'/chat/?user_id={self.b.pk}').content.decode()
        room = PrivateChatRoom.objects.get(user1=self.a, user2=self.b)
        self.assertFalse(room.is_active)
        self.assertIn(f'id_friend_container_{self.b.pk}', page)
        self.assertNotIn(f'id_friend_container_{self.a.pk}', self.client_of(self.b).get('/chat/').content.decode())
        # Premier message : la conversation est dans la liste des deux, sans être amis
        self.assertEqual(self.send(self.a, room, 'Bonjour')['message'], 'Bonjour')
        room.refresh_from_db()
        self.assertTrue(room.is_active)
        self.assertIn(f'id_friend_container_{self.a.pk}', self.client_of(self.b).get('/chat/').content.decode())
        self.assertIn(f'id_friend_container_{self.b.pk}', self.client_of(self.a).get('/chat/').content.decode())

    def test_identifiant_illisible_sans_erreur(self):
        client = self.client_of(self.a)
        self.assertEqual(client.get('/chat/?user_id=abc').status_code, 200)
        self.assertEqual(client.get('/chat/?room_id=abc').status_code, 200)
        self.assertEqual(client.post('/chat/secret/', {'room_id': 'abc', 'on': '1'}).status_code, 404)
        self.assertEqual(client.post('/chat/create_or_return_private_chat', {'user2_id': 'abc'}).json()['ok'], False)
        self.assertEqual(client.post('/chat/create_or_return_private_chat', {'user2_id': self.b.pk}).json()['ok'], True)


class LongMessageTests(Base):
    def test_long_message_vers_quelqu_un_d_absent(self):
        room = PrivateChatRoom.objects.create(user1=self.a, user2=self.b)
        text = 'é' * 900
        got = self.send(self.a, room, text)
        self.assertEqual(got.get('message'), text)                    # (diffusé en entier)
        self.assertEqual(RoomChatMessage.objects.get().content, text)
        unread = UnreadChatRoomMessages.objects.get(room=room, user=self.b)
        self.assertEqual(unread.count, 1)
        self.assertEqual(len(unread.most_recent_message), PREVIEW_MAX)
        verb = Notification.objects.get(target=self.b).verb
        self.assertLessEqual(len(verb), Notification._meta.get_field('verb').max_length)


class BlockTests(Base):
    def setUp(self):
        super().setUp()
        self.room = PrivateChatRoom.objects.create(user1=self.a, user2=self.b, is_active=True)
        UserBlock.objects.create(blocker=self.b, blocked=self.a)

    def test_plus_de_message_ni_de_fichier(self):
        for user in (self.a, self.b):
            self.assertEqual(self.send(user, self.room, 'coucou')['error'], 'BLOCKED')
        self.assertFalse(RoomChatMessage.objects.exists())
        sent = self.client_of(self.a).post('/chat/upload_file/', {
            'room_id': self.room.id, 'file': SimpleUploadedFile('photo.jpg', b'x', 'image/jpeg')})
        self.assertEqual(sent.status_code, 403)
        reply = self.client_of(self.a).post('/chat/story-reply/', {'story_author_id': self.b.pk, 'message': 'joli'})
        self.assertEqual(reply.status_code, 404)

    def test_pas_de_nouvelle_conversation_par_l_adresse(self):
        c = mk('cle')
        UserBlock.objects.create(blocker=c, blocked=self.a)
        self.client_of(self.a).get(f'/chat/?user_id={c.pk}')
        self.assertFalse(PrivateChatRoom.objects.filter(user2=c).exists())

    def test_pas_d_appel(self):
        async def scenario():
            ca = WebsocketCommunicator(ChatConsumer.as_asgi(), '/chat/%d/' % self.room.id)
            ca.scope['user'] = self.a
            await ca.connect()
            await ca.send_json_to({'command': 'join', 'room': str(self.room.id)})
            await self.drain(ca, lambda d: 'join' in d)
            await ca.send_json_to({'command': 'call_offer', 'room': str(self.room.id), 'sdp': {}, 'call_mode': 'audio'})
            error = await self.drain(ca, lambda d: d.get('error'))
            await ca.disconnect()
            return error
        self.assertEqual(asyncio.run(scenario())['error'], 'BLOCKED')


class StoryReplyTests(Base):
    def test_jamais_de_texte_en_clair_dans_une_conversation_secrete(self):
        PrivateChatRoom.objects.create(user1=self.a, user2=self.b, is_active=True, encrypted=True)
        reply = self.client_of(self.a).post('/chat/story-reply/', {'story_author_id': self.b.pk, 'message': 'joli'})
        self.assertEqual((reply.status_code, reply.json()['code']), (409, 'SECRET_ROOM'))
        self.assertFalse(RoomChatMessage.objects.exists())


class PageTests(Base):
    def test_page_et_scripts_dans_les_trois_langues(self):
        """La page se rend, et aucun texte traduit ne casse ses scripts en ligne."""
        import re
        try:
            import esprima
        except ImportError:
            esprima = None
        PrivateChatRoom.objects.create(user1=self.a, user2=self.b, is_active=True)
        for lang in ('fr', 'en', 'mg'):
            client = self.client_of(self.a)
            client.cookies['zoot_language'] = lang
            # (texte pré-rempli avec apostrophe, guillemets et barre oblique : rien ne casse le script)
            response = client.get('/chat/', {'user_id': self.b.pk, 'story_reply': 'l\'été "ici" \\ </script>'})
            self.assertEqual(response.status_code, 200)
            page = response.content.decode()
            self.assertEqual(client.get('/offline/').status_code, 200)
            # Les contenus venus d'autres membres ne passent jamais par innerHTML
            self.assertNotIn("innerHTML = user_info['username']", page)
            self.assertNotIn("innerHTML = notification['verb']", page)
            self.assertNotIn("innerHTML = notification['from']['title']", page)
            if esprima is None:
                continue
            for script in re.findall(r'<script(?![^>]*\bsrc=)(?![^>]*type="(?!text/javascript)[^"]*")[^>]*>(.*?)</script>', page, re.S):
                if script.strip():
                    esprima.parseScript(script, tolerant=False)
