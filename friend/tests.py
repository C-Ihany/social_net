from django.test import TestCase

from account.models import Account
from friend.models import FriendList, FriendRequest
from notification.models import Notification


class FriendRequestRulesTests(TestCase):
    """Règles d'amitié corrigées le 2026-11-22 (audit, constats 3 et 6)."""

    def setUp(self):
        self.alice = Account.objects.create_user('alice@test.mg', 'Alice', 'pw12345678')
        self.bob = Account.objects.create_user('bob@test.mg', 'Bob', 'pw12345678')
        self.client.force_login(self.alice)

    def test_une_demande_annulee_ne_peut_plus_etre_acceptee(self):
        fr = FriendRequest.objects.create(sender=self.bob, receiver=self.alice)
        fr.cancel()
        response = self.client.post(f'/friend/friend_request_accept/{fr.pk}/')
        self.assertEqual(response.status_code, 409)
        self.assertFalse(FriendList.objects.get(user=self.alice).friends.filter(pk=self.bob.pk).exists())

    def test_une_demande_en_attente_s_accepte(self):
        fr = FriendRequest.objects.create(sender=self.bob, receiver=self.alice)
        response = self.client.post(f'/friend/friend_request_accept/{fr.pk}/')
        self.assertEqual(response.json()['response'], 'Friend request accepted.')
        self.assertTrue(FriendList.objects.get(user=self.alice).friends.filter(pk=self.bob.pk).exists())
        self.assertTrue(FriendList.objects.get(user=self.bob).friends.filter(pk=self.alice.pk).exists())

    def test_retirer_un_inconnu_n_envoie_aucune_notification(self):
        before = Notification.objects.count()
        response = self.client.post('/friend/friend_remove/', {'receiver_user_id': self.bob.pk})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Notification.objects.count(), before)

    def test_la_liste_d_amis_d_un_non_ami_renvoie_au_profil(self):
        response = self.client.get(f'/friend/list/{self.bob.pk}')
        self.assertRedirects(response, f'/account/{self.bob.pk}/', fetch_redirect_response=False)
