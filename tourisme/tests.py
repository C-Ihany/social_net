"""
Tests de la section Tourisme : lieux, guides, filtres, envois de photos.
Lancer :  python manage.py test tourisme
"""
import io
import re
import tempfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from .admin import notify_lieu_approved
from .models import GuideTouristique, LieuImage, LieuTouristique

User = get_user_model()


def _png(name='photo.png', size=(4, 4)):
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', size, (10, 120, 110)).save(buf, format='PNG')
    return SimpleUploadedFile(name, buf.getvalue(), content_type='image/png')


SVG = SimpleUploadedFile('logo.svg', b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
                         content_type='image/svg+xml')


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix='vazimba-test-tourisme-'))
class TourismeTests(TestCase):

    def setUp(self):
        self.author = User.objects.create_user(email='auteur@test.mg', username='auteur', password='pass12345')
        self.other = User.objects.create_user(email='autre@test.mg', username='autre', password='pass12345')
        self.lieu = LieuTouristique.objects.create(
            name='Chutes Victoria', description='Un rideau d\'eau.', category='nature', region='zm',
            added_by=self.author, is_approved=True,
        )

    # ── Slug ──────────────────────────────────────────────────────────────────
    def test_slug_non_latin_ne_casse_pas_les_listes(self):
        a = LieuTouristique.objects.create(name='الأهرامات', description='x', is_approved=True)
        b = LieuTouristique.objects.create(name='!!!', description='x', is_approved=True)
        self.assertEqual(a.slug, 'lieu')
        self.assertEqual(b.slug, 'lieu-1')
        for name in ('tourisme:home', 'tourisme:lieux_list'):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200)
        self.assertEqual(self.client.get(reverse('tourisme:lieu_detail', args=[a.slug])).status_code, 200)

    # ── Liste des lieux ───────────────────────────────────────────────────────
    def test_lien_tous_avec_region_seule(self):
        r = self.client.get(reverse('tourisme:lieux_list'), {'region': 'zm', 'cat': 'nature'})
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertNotIn('/tourisme/lieux/&', html)
        self.assertIn('href="?region=zm"', html)                 # « Tous » garde la région
        self.assertIn('Zambie', html)                            # libellé, pas la clé
        self.assertEqual(self.client.get(reverse('tourisme:lieux_list') + '?region=zm').status_code, 200)

    def test_autocomplete_renvoie_les_libelles(self):
        r = self.client.get(reverse('tourisme:lieu_autocomplete'), {'q': 'chutes'})
        item = r.json()['results'][0]
        self.assertEqual(item['region_label'], 'Zambie')
        self.assertEqual(item['icon'], 'forest')
        self.assertTrue(item['category_label'])

    # ── Proposer / modifier un lieu ───────────────────────────────────────────
    def test_proposer_un_lieu_refuse_le_svg_et_garde_les_images(self):
        self.client.force_login(self.other)
        r = self.client.post(reverse('tourisme:lieu_submit'), {
            'name': 'Île de Gorée', 'description': 'Mémoire.', 'category': 'histoire', 'region': 'sn',
            'images': [_png(), SVG],
        })
        lieu = LieuTouristique.objects.get(name='Île de Gorée')
        self.assertRedirects(r, reverse('tourisme:lieu_detail', args=[lieu.slug]))
        self.assertFalse(lieu.is_approved)
        self.assertEqual(lieu.images.count(), 1)
        self.assertTrue(lieu.images.first().is_primary)

    def test_proposer_un_lieu_valeurs_invalides(self):
        self.client.force_login(self.other)
        r = self.client.post(reverse('tourisme:lieu_submit'), {
            'name': 'Lac Rose', 'description': 'Rose.', 'category': 'x' * 40, 'region': 'sn'})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'value="Lac Rose"')               # la saisie est conservée
        self.assertFalse(LieuTouristique.objects.filter(name='Lac Rose').exists())
        r = self.client.post(reverse('tourisme:lieu_submit'), {'name': ' ', 'description': ''})
        self.assertEqual(r.status_code, 200)

    def test_modifier_un_lieu_approuve_le_renvoie_en_moderation(self):
        LieuImage.objects.create(lieu=self.lieu, image=_png(), is_primary=True)
        self.client.force_login(self.author)
        r = self.client.post(reverse('tourisme:lieu_edit', args=[self.lieu.slug]), {
            'name': 'Chutes Victoria', 'description': 'Nouveau texte.', 'category': 'nature', 'region': 'zm',
            'delete_images': ['abc', '999999'],
        })
        self.assertEqual(r.status_code, 302)
        self.lieu.refresh_from_db()
        self.assertFalse(self.lieu.is_approved)
        self.assertEqual(self.lieu.images.count(), 1)
        # un autre membre ne peut pas modifier
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse('tourisme:lieu_edit', args=[self.lieu.slug])).status_code, 403)

    def test_notification_a_l_approbation(self):
        from notification.models import Notification
        self.assertTrue(notify_lieu_approved(self.lieu, self.other))
        notif = Notification.objects.get(target=self.author)
        self.assertIn('Chutes Victoria', notif.verb)
        self.assertEqual(notif.redirect_url, reverse('tourisme:lieu_detail', args=[self.lieu.slug]))
        self.assertEqual(notif.get_content_object_type(), 'Restaurant')

    # ── Avis ──────────────────────────────────────────────────────────────────
    def test_avis(self):
        self.client.force_login(self.other)
        url = reverse('tourisme:lieu_detail', args=[self.lieu.slug])
        self.assertEqual(self.client.post(url, {'rating': 'abc', 'comment': 'Bien'}).status_code, 200)
        self.assertEqual(self.client.post(url, {'rating': '4', 'comment': 'Bien', 'visited_at': 'hier'}).status_code, 200)
        self.assertEqual(self.lieu.avis.count(), 0)
        self.assertEqual(self.client.post(url, {'rating': '4', 'comment': 'Bien'}).status_code, 302)
        self.assertEqual(self.lieu.avis.get().rating, 4)

    # ── Guides ────────────────────────────────────────────────────────────────
    def test_filtre_region_des_guides(self):
        g1 = GuideTouristique.objects.create(user=self.author, bio='Guide', regions_covered='Fianarantsoa, Haute Matsiatra')
        g2 = GuideTouristique.objects.create(user=self.other, bio='Guide', regions_covered='Lusaka et toute la Zambie')
        ids = lambda **p: [g.pk for g in self.client.get(reverse('tourisme:guides_list'), p).context['page_obj']]
        self.assertEqual(ids(region='haute_matsiatra'), [g1.pk])
        self.assertEqual(ids(region='zm'), [g2.pk])
        self.assertEqual(ids(region='sn'), [])
        r = self.client.get(reverse('tourisme:guides_autocomplete'), {'region': 'zm'})
        self.assertEqual([x['id'] for x in r.json()['results']], [g2.pk])

    def test_inscription_guide_bornes_et_photo(self):
        self.client.force_login(self.author)
        url = reverse('tourisme:guide_register')
        r = self.client.post(url, {'bio': '', 'years_experience': '3'})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(GuideTouristique.objects.exists())
        r = self.client.post(url, {'bio': 'Guide', 'photo': SVG})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(GuideTouristique.objects.exists())
        r = self.client.post(url, {
            'bio': 'Guide de montagne', 'years_experience': '-5', 'max_group_size': '99999',
            'prix_jour': '9' * 30, 'languages': 'x' * 900, 'phone': '+221 77 123 45 67', 'photo': _png(),
        })
        guide = GuideTouristique.objects.get(user=self.author)
        self.assertRedirects(r, reverse('tourisme:guide_profile', args=[guide.pk]))
        self.assertEqual((guide.years_experience, guide.max_group_size), (0, 100))
        self.assertEqual(int(guide.prix_jour), 9_999_999_999)
        self.assertEqual(len(guide.languages), 250)
        self.assertEqual(guide.whatsapp_number, '221771234567')
        self.assertTrue(guide.photo)

    def test_numero_whatsapp(self):
        g = GuideTouristique(user=self.author, bio='x')
        for raw, expected in [('+261 34 00 000 00', '261340000000'), ('00221771234567', '221771234567'),
                              ('034 00 000 00', ''), ('', ''), ('254 712 345 678', '254712345678')]:
            g.phone = raw
            self.assertEqual(g.whatsapp_number, expected, raw)

    def test_profil_guide_masque_les_lieux_non_approuves(self):
        guide = GuideTouristique.objects.create(user=self.author, bio='Guide', phone='034 00 000 00')
        pending = LieuTouristique.objects.create(name='Secret', description='x', is_approved=False)
        guide.lieux_favoris.add(self.lieu, pending)
        url = reverse('tourisme:guide_profile', args=[guide.pk])
        r = self.client.get(url)
        self.assertContains(r, 'Chutes Victoria')
        self.assertNotContains(r, 'Secret')
        self.assertNotContains(r, 'wa.me')                       # numéro local : pas de lien WhatsApp faux
        self.client.force_login(self.author)
        self.assertContains(self.client.get(url), 'Secret')

    # ── Rendu des pages dans les trois langues + scripts en ligne valides ─────
    def test_rendu_des_pages_fr_en_mg(self):
        import esprima
        guide = GuideTouristique.objects.create(user=self.author, bio='Guide', phone='+260 97 000 0000',
                                                is_verified=True, prix_jour=150000, years_experience=4)
        guide.lieux_favoris.add(self.lieu)
        LieuImage.objects.create(lieu=self.lieu, image=_png('a.png'), is_primary=True)
        LieuImage.objects.create(lieu=self.lieu, image=_png('b.png'), order=1)
        self.client.force_login(self.author)
        self.client.post(reverse('tourisme:lieu_detail', args=[self.lieu.slug]), {'rating': '5', 'comment': 'Superbe'})
        urls = [
            reverse('tourisme:home'),
            reverse('tourisme:lieux_list'),
            reverse('tourisme:lieux_list') + '?q=chutes&cat=nature&region=zm',
            reverse('tourisme:lieux_list') + '?q=introuvable',
            reverse('tourisme:lieu_detail', args=[self.lieu.slug]),
            reverse('tourisme:lieu_submit'),
            reverse('tourisme:lieu_edit', args=[self.lieu.slug]),
            reverse('tourisme:guides_list'),
            reverse('tourisme:guides_list') + '?verified=1&region=zm&q=guide',
            reverse('tourisme:guides_list') + '?q=introuvable',
            reverse('tourisme:guide_profile', args=[guide.pk]),
            reverse('tourisme:guide_register'),
        ]
        for lang in ('fr', 'en', 'mg'):
            self.client.cookies['zoot_language'] = lang
            for url in urls:
                r = self.client.get(url)
                self.assertEqual(r.status_code, 200, f'{lang} {url}')
                html = r.content.decode()
                for script in re.findall(r'<script(?![^>]*\bsrc=)(?![^>]*application/(?:json|ld\+json))[^>]*>(.*?)</script>', html, re.S):
                    if script.strip():
                        try:
                            esprima.parseScript(script)
                        except Exception as exc:        # pragma: no cover
                            self.fail(f'script invalide ({lang} {url}) : {exc}')
