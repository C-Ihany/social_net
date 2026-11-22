"""Corrections du 2026-11-22 (audit compte / amis) : non-régression."""
from django.test import TestCase

from account.forms import RegistrationForm
from account.models import Account
from friend.models import FriendList
from post.models import Post


class ProfilVisibiliteTests(TestCase):
    def setUp(self):
        self.alice = Account.objects.create_user('alice@test.mg', 'Alice', 'pw12345678')
        self.bob = Account.objects.create_user('bob@test.mg', 'Bob', 'pw12345678')
        self.carla = Account.objects.create_user('carla@test.mg', 'Carla', 'pw12345678')
        FriendList.objects.get(user=self.alice).friends.add(self.bob)
        FriendList.objects.get(user=self.bob).friends.add(self.alice)

    def test_liste_d_amis_reservee_au_membre_et_a_ses_amis(self):
        self.assertNotContains(self.client.get(f'/account/{self.alice.pk}/'), 'friend-card-link')
        self.client.force_login(self.carla)
        self.assertNotContains(self.client.get(f'/account/{self.alice.pk}/'), 'friend-card-link')
        self.client.force_login(self.bob)
        self.assertContains(self.client.get(f'/account/{self.alice.pk}/'), 'friend-card-link')

    def test_recherche_instantanee_sans_brouillon(self):
        Post.objects.create(author=self.alice, title='zanzibar secret', body='x', status='draft')
        Post.objects.create(author=self.alice, title='zanzibar public', body='x', status='published')
        titles = [p['title'] for p in self.client.get('/account/search/api/?q=zanzibar').json()['posts']]
        self.assertEqual(titles, ['zanzibar public'])

    def test_ancienne_page_de_recherche_redirigee(self):
        self.assertRedirects(self.client.get('/search/?q=Ali'), '/recherche/?q=Ali', fetch_redirect_response=False)


class CompteTests(TestCase):
    def test_pseudo_html_refuse_a_l_inscription(self):
        data = {'email': 'x@test.mg', 'password1': 'Azerty!2345', 'password2': 'Azerty!2345'}
        self.assertIn('username', RegistrationForm({**data, 'username': '<img src=x onerror=1>'}).errors)
        self.assertTrue(RegistrationForm({**data, 'username': 'Rasoa_Be-2 é'}).is_valid())

    def test_suppression_d_un_compte_sans_mot_de_passe(self):
        user = Account.objects.create_user('pola@test.mg', 'Pola')
        user.set_unusable_password(); user.save()
        self.client.force_login(user)
        self.assertContains(self.client.get('/account/supprimer/'), 'confirm_word')
        self.client.post('/account/supprimer/', {'confirm_word': 'autre'})
        self.assertTrue(Account.objects.filter(pk=user.pk).exists())
        self.client.post('/account/supprimer/', {'confirm_word': 'supprimer'})
        self.assertFalse(Account.objects.filter(pk=user.pk).exists())

    def test_deconnexion_en_post_seulement(self):
        user = Account.objects.create_user('a@test.mg', 'Alice', 'pw12345678')
        self.client.force_login(user)
        self.assertEqual(self.client.get('/logout/').status_code, 200)       # page de confirmation
        self.assertIn('_auth_user_id', self.client.session)
        self.client.post('/logout/')
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_visiteur_anonyme_sans_socket_de_notifications(self):
        html = self.client.get('/login/').content.decode()
        self.assertNotIn('new WebSocket', html)
