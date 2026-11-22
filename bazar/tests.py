"""Tests du Bazar : visibilité des annonces, statuts, prix affiché, WhatsApp, contrôle des photos."""
import io

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from .models import Annonce, whatsapp_digits


def _png(name='a.png'):
    buf = io.BytesIO()
    Image.new('RGB', (20, 20), (200, 30, 30)).save(buf, 'PNG')
    return SimpleUploadedFile(name, buf.getvalue(), 'image/png')


@override_settings(ALLOWED_HOSTS=['*'])
class BazarTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(email='o@t.io', username='owner', password='x12345678')
        self.other = User.objects.create_user(email='v@t.io', username='other', password='x12345678')
        self.vente = Annonce.objects.create(seller=self.owner, title='Vélo', description='d',
                                            location='Dakar', price=125000)
        self.loc = Annonce.objects.create(seller=self.owner, title='Studio', description='d', location='Lomé',
                                          listing_type='location', prix_location=300000, periode_location='mois')

    def _form(self, **over):
        data = dict(listing_type='vente', title='Nouveau', category='autres', condition='bon',
                    description='d', location='Lomé', status='active', periode_location='jour')
        data.update(over)
        return data

    def test_annonce_en_pause_invisible_sauf_proprietaire(self):
        self.vente.status = 'pause'
        self.vente.save()
        url = reverse('bazar:detail', args=[self.vente.pk])
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_prix_affiche_selon_le_type(self):
        self.assertEqual(self.vente.display_price, self.vente.formatted_price)
        self.assertIn('300 000 Ar', self.loc.display_price)

    def test_location_se_clot_en_louee_et_ne_se_reactive_pas_par_la_bascule(self):
        self.client.force_login(self.owner)
        self.client.post(reverse('bazar:mark_sold', args=[self.loc.pk]))
        self.loc.refresh_from_db()
        self.assertEqual(self.loc.status, 'louee')
        r = self.client.post(reverse('bazar:toggle_status', args=[self.loc.pk]))
        self.assertEqual(r.status_code, 400)
        self.loc.refresh_from_db()
        self.assertEqual(self.loc.status, 'louee')

    def test_bascule_active_pause(self):
        self.client.force_login(self.owner)
        r = self.client.post(reverse('bazar:toggle_status', args=[self.vente.pk]))
        self.assertEqual(r.json()['new_status'], 'pause')
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(reverse('bazar:toggle_status', args=[self.vente.pk])).status_code, 403)

    def test_statut_expiree_refuse_au_formulaire(self):
        self.client.force_login(self.owner)
        r = self.client.post(reverse('bazar:edit', args=[self.vente.pk]), self._form(status='expiree'))
        self.assertEqual(r.status_code, 200)          # formulaire réaffiché avec l'erreur
        self.vente.refresh_from_db()
        self.assertEqual(self.vente.status, 'active')

    def test_annonce_expiree_reste_expiree_a_la_modification(self):
        self.vente.status = 'expiree'
        self.vente.save()
        self.client.force_login(self.owner)
        r = self.client.post(reverse('bazar:edit', args=[self.vente.pk]), self._form(status='expiree', title='Vélo 2'))
        self.assertEqual(r.status_code, 302)
        self.vente.refresh_from_db()
        self.assertEqual((self.vente.status, self.vente.title), ('expiree', 'Vélo 2'))

    def test_photos_non_images_refusees(self):
        self.client.force_login(self.owner)
        svg = SimpleUploadedFile('x.svg', b'<svg xmlns="http://www.w3.org/2000/svg"></svg>', 'image/svg+xml')
        r = self.client.post(reverse('bazar:create'), {**self._form(), 'images': [_png(), svg]})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Annonce.objects.get(title='Nouveau').images.count(), 1)

    def test_numero_whatsapp(self):
        self.assertEqual(whatsapp_digits('+221 77 123 45 67'), '221771234567')
        self.assertEqual(whatsapp_digits('00221 77 123 45 67'), '221771234567')
        self.assertEqual(whatsapp_digits('034 12 345 67'), '')      # format local : pas de lien wa.me
        self.assertEqual(whatsapp_digits(''), '')

    def test_filtres_conserves_dans_les_onglets_et_la_pagination(self):
        for i in range(14):
            Annonce.objects.create(seller=self.owner, title=f'A{i}', description='d', location='L', price=1000)
        html = self.client.get(reverse('bazar:index'), {'cat': 'autres', 'type': 'vente'}).content.decode()
        self.assertIn('cat=autres&amp;type=location', html)                # onglet « À louer » garde la catégorie
        self.assertIn('cat=autres&amp;type=vente&amp;page=2', html)        # pagination garde le type
        self.assertIn('name="type" value="vente"', html)                   # le formulaire de filtres aussi
