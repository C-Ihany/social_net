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
        self.assertIn('300\u202f000\u00a0Ar', self.loc.display_price)   # même rendu que le filtre vz_money

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

    # ── Devise par pays ───────────────────────────────────────────────────────
    def test_devise_de_l_annonce_et_filtre_de_prix(self):
        """Une annonce en XOF s'affiche en FCFA ; un filtre de prix ne compare que la devise du visiteur."""
        User = get_user_model()
        User.objects.filter(pk=self.other.pk).update(region='sn')
        xof = Annonce.objects.create(seller=self.other, title='Pirogue', description='d', location='Dakar',
                                     region='sn', price=90000, currency='XOF')
        self.assertIn('FCFA', xof.display_price)
        self.assertNotIn('Ar', xof.display_price)
        self.assertIn('Ar', self.vente.display_price)           # l'existant reste en ariary
        r = self.client.get(reverse('bazar:detail', args=[xof.pk]))
        self.assertContains(r, 'FCFA')
        # Sans filtre de prix : tout s'affiche, chacun dans sa devise
        r = self.client.get(reverse('bazar:index'))
        self.assertContains(r, 'Pirogue'); self.assertContains(r, 'Vélo')
        # Visiteur sénégalais + filtre de prix : seulement les annonces en FCFA, et c'est dit
        self.client.login(email='v@t.io', password='x12345678')
        r = self.client.get(reverse('bazar:index'), {'pmax': '200000'})
        self.assertContains(r, 'Pirogue'); self.assertNotContains(r, 'Vélo')
        self.assertContains(r, 'Prix en FCFA')
        r = self.client.get(reverse('bazar:index'), {'sort': 'price_asc'})
        self.assertNotContains(r, 'Vélo')
        # Création : devise proposée d'après le pays, modifiable
        r = self.client.get(reverse('bazar:create'))
        self.assertContains(r, '<option value="XOF" selected>')
        self.client.post(reverse('bazar:create'), self._form(title='Sans devise', price='500'))
        self.assertEqual(Annonce.objects.get(title='Sans devise').currency, 'XOF')
        self.client.post(reverse('bazar:create'), self._form(title='En euros', price='50', currency='EUR'))
        self.assertEqual(Annonce.objects.get(title='En euros').currency, 'EUR')

    def test_pres_de_chez_moi_pays_et_diaspora(self):
        User = get_user_model()
        Annonce.objects.filter(pk=self.vente.pk).update(region='analamanga')
        Annonce.objects.filter(pk=self.loc.pk).update(region='tg')
        # « Madagascar » choisi comme pays : toutes ses régions
        User.objects.filter(pk=self.other.pk).update(region='mg')
        self.client.login(email='v@t.io', password='x12345678')
        r = self.client.get(reverse('bazar:index'), {'near': '1'})
        self.assertContains(r, 'Vélo'); self.assertNotContains(r, 'Studio')
        # Diaspora d'origine togolaise : le contenu du Togo
        User.objects.filter(pk=self.other.pk).update(region='diaspora', origin_country='tg')
        r = self.client.get(reverse('bazar:index'), {'near': '1'})
        self.assertContains(r, 'Studio'); self.assertNotContains(r, 'Vélo')

    def test_rendu_des_pages_fr_en_mg(self):
        """Pages touchées par la devise : 200 dans les trois langues, scripts en ligne analysables."""
        import re
        try:
            import esprima
        except ImportError:
            esprima = None
        Annonce.objects.filter(pk=self.loc.pk).update(currency='XOF', caution=50000)
        self.client.login(email='o@t.io', password='x12345678')
        urls = [reverse('bazar:index'), reverse('bazar:index') + '?pmin=10&sort=price_asc&near=1',
                reverse('bazar:detail', args=[self.vente.pk]), reverse('bazar:detail', args=[self.loc.pk]),
                reverse('bazar:create'), reverse('bazar:edit', args=[self.loc.pk]),
                reverse('bazar:mes_annonces'), reverse('bazar:mes_favoris')]
        for lang in ('fr', 'en', 'mg'):
            self.client.cookies['zoot_language'] = lang
            for url in urls:
                r = self.client.get(url)
                self.assertEqual(r.status_code, 200, f'{lang} {url}')
                html = r.content.decode()
                self.assertNotIn('vz_ariary', html)
                if esprima:
                    for m in re.finditer(r'<script(?![^>]*\bsrc=)(?![^>]*application/(?:json|ld\+json))[^>]*>(.*?)</script>', html, re.S):
                        if m.group(1).strip():
                            js = m.group(1).replace('?.[', '[').replace('?.(', '(').replace('?.', '.').replace(' ?? ', ' || ')
                            try:
                                esprima.parseScript(js, tolerant=False)
                            except Exception as e:      # pragma: no cover
                                self.fail(f'{lang} {url} : script en ligne invalide — {e}')
