"""Pays de résidence et pays d'origine à l'inscription ; devise par défaut."""
from django.test import TestCase
from django.urls import reverse

import regions
from account.forms import RegistrationForm
from account.models import Account


def _data(**extra):
    data = {'email': 'awa@test.sn', 'username': 'awa', 'password1': 'Motdepasse-2026', 'password2': 'Motdepasse-2026',
            'region': 'sn', 'origin_country': ''}
    data.update(extra)
    return data


class PaysInscriptionTests(TestCase):
    def test_pays_de_residence_obligatoire(self):
        form = RegistrationForm(_data(region=''))
        self.assertFalse(form.is_valid())
        self.assertIn('region', form.errors)

    def test_origine_reprise_du_pays_de_residence(self):
        form = RegistrationForm(_data())
        self.assertTrue(form.is_valid(), form.errors)
        account = form.save()
        self.assertEqual((account.region, account.origin_country), ('sn', 'sn'))

    def test_vivre_en_france_avec_une_origine(self):
        form = RegistrationForm(_data(region='fr', origin_country='sn'))
        self.assertTrue(form.is_valid(), form.errors)
        account = form.save()
        self.assertEqual((account.region, account.origin_country), ('fr', 'sn'))
        self.assertEqual(regions.currency_for_user(account), 'EUR')
        self.assertEqual(regions.nearby_label(account), 'Sénégal')

    def test_hors_d_afrique_l_origine_reste_facultative(self):
        form = RegistrationForm(_data(region='fr'))
        self.assertTrue(form.is_valid(), form.errors)
        account = form.save()
        self.assertEqual((account.region, account.origin_country), ('fr', ''))
        self.assertEqual(regions.nearby_label(account), 'France')

    def test_pays_inconnu_refuse(self):
        self.assertIn('region', RegistrationForm(_data(region='zz')).errors)

    def test_page_inscription_propose_les_deux_listes(self):
        html = self.client.get(reverse('register')).content.decode()
        self.assertIn('name="region"', html)
        self.assertIn('name="origin_country"', html)
        self.assertIn('Sénégal', html)
        for pays in ('France', 'Belgique', 'Canada', 'États-Unis', 'Autre pays'):
            self.assertIn(pays, html)

    def test_inscription_complete(self):
        r = self.client.post(reverse('register'), dict(_data(region='fr', origin_country='ci'), accept_terms='on'))
        self.assertEqual(r.status_code, 302)
        account = Account.objects.get(email='awa@test.sn')
        self.assertEqual((account.region, account.origin_country), ('fr', 'ci'))


class DeviseTests(TestCase):
    def test_devise_par_defaut(self):
        self.assertEqual(regions.currency_for_region('sn'), 'XOF')
        self.assertEqual(regions.currency_for_region('analamanga'), 'MGA')
        self.assertEqual(regions.currency_for_region('diaspora', 'sn'), 'EUR')
        self.assertEqual(regions.currency_for_region('', 'ke'), 'KES')
        self.assertEqual(regions.currency_for_region(''), 'MGA')

    def test_chaque_pays_a_une_devise_connue(self):
        for code, _label in regions.AFRICA_COUNTRIES:
            self.assertIn(regions.COUNTRY_CURRENCY[code], regions.CURRENCIES)

    def test_format(self):
        self.assertEqual(regions.format_money(12500, 'XOF'), '12 500 FCFA')
        self.assertEqual(regions.format_money('abc', 'XOF'), '')
