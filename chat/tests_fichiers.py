"""Fichiers du chat privé : seulement pour les deux personnes de la conversation (18/11/2026)."""
import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from account.models import Account
from chat.models import PrivateChatRoom, RoomChatMessage
from chat.utils import LazyRoomChatMessageEncoder

MEDIA = tempfile.mkdtemp()


@override_settings(MEDIA_ROOT=MEDIA)
class ChatFileTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        self.lova = Account.objects.create_user('lova@example.com', 'lova', 'x-motdepasse-1')
        self.miora = Account.objects.create_user('miora@example.com', 'miora', 'x-motdepasse-2')
        self.intrus = Account.objects.create_user('intrus@example.com', 'intrus', 'x-motdepasse-3')
        self.room = PrivateChatRoom.objects.create(user1=self.lova, user2=self.miora)
        self.msg = RoomChatMessage.objects.create(
            user=self.lova, room=self.room, file_type='document',
            file=SimpleUploadedFile('ordonnance.pdf', b'%PDF secret', content_type='application/pdf'))

    def test_les_deux_personnes_ouvrent_le_fichier(self):
        for person in (self.lova, self.miora):
            self.client.force_login(person)
            response = self.client.get(reverse('chat:file', args=[self.msg.pk]))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(b''.join(response.streaming_content), b'%PDF secret')
            self.assertIn('no-store', response['Cache-Control'])

    def test_un_autre_membre_ne_peut_pas(self):
        self.client.force_login(self.intrus)
        self.assertEqual(self.client.get(reverse('chat:file', args=[self.msg.pk])).status_code, 404)

    def test_sans_compte_non_plus(self):
        response = self.client.get(reverse('chat:file', args=[self.msg.pk]))
        self.assertEqual(response.status_code, 302)          # (vers la page de connexion)

    def test_les_messages_ne_donnent_plus_l_adresse_directe(self):
        data = LazyRoomChatMessageEncoder().serialize([self.msg])[0]
        self.assertEqual(data['file_url'], reverse('chat:file', args=[self.msg.pk]))

    def test_envoi_d_un_fichier_rend_le_lien_verifie(self):
        self.client.force_login(self.lova)
        response = self.client.post(reverse('chat:upload-chat-file'), {
            'room_id': self.room.pk, 'file': SimpleUploadedFile('photo.png', b'\x89PNG...', content_type='image/png')})
        url = response.json()['file_url']
        self.assertTrue(url.startswith('/chat/fichier/'), url)
