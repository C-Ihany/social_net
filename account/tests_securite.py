"""Codes par SMS / WhatsApp et connexion par numéro de téléphone (étape 1 de la sécurité, 18/11/2026)."""
from unittest import mock

from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from account import sms
from account.models import Account, PhoneVerification

SENT = []


def fake_send(to, code, channel='sms'):
    """Remplace l'envoi réel : on garde le code pour le saisir dans le test."""
    SENT.append((to, code, channel))
    return {'status': 'ok'}


@override_settings(DEBUG=True, WHATSAPP_TOKEN='', SMS_BACKEND='console')
@mock.patch('account.otp.send_otp', fake_send)
class PhoneLoginTests(TestCase):
    def setUp(self):
        cache.clear()                   # (les limites par adresse IP vivent dans le cache)
        SENT.clear()
        self.user = Account.objects.create_user('lova@example.com', 'lova', 'motdepasse-solide-123')
        self.user.phone_number, self.user.phone_verified = '+261341234567', True
        self.user.save()

    def ask_code(self, phone='034 12 345 67', channel='sms', country='MG'):
        return self.client.post(reverse('phone-login'), {'step': 'numero', 'phone': phone, 'channel': channel,
                                                         'country': country})

    def test_connexion_par_numero_et_code(self):
        response = self.ask_code()
        self.assertContains(response, 'Si ce numéro est lié à un compte')
        self.assertEqual(len(SENT), 1)
        code = SENT[0][1]
        response = self.client.post(reverse('phone-login'), {'step': 'code', 'code': code})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(int(self.client.session['_auth_user_id']), self.user.pk)

    def test_le_code_n_est_pas_garde_en_clair(self):
        self.ask_code()
        code = SENT[0][1]
        saved = PhoneVerification.objects.get()
        self.assertNotEqual(saved.code, code)
        self.assertEqual(len(saved.code), 64)
        self.assertTrue(saved.matches(code))

    def test_meme_reponse_pour_un_numero_inconnu(self):
        """La page ne doit pas dire quels numéros ont un compte."""
        known = self.ask_code().content.decode()
        cache.clear()
        unknown = self.ask_code('034 99 999 99').content.decode()
        self.assertIn('Si ce numéro est lié à un compte', unknown)
        self.assertEqual(len(SENT), 1)              # (aucun code envoyé au numéro inconnu)
        strip = lambda page: page.split('<strong>')[0]
        self.assertEqual(strip(known).count('auth-errors'), strip(unknown).count('auth-errors'))

    def test_un_mauvais_code_ne_connecte_pas_et_5_essais_au_plus(self):
        self.ask_code()
        good = SENT[0][1]
        wrong = '000000' if good != '000000' else '111111'
        for _ in range(5):
            self.client.post(reverse('phone-login'), {'step': 'code', 'code': wrong})
        self.assertNotIn('_auth_user_id', self.client.session)
        cache.clear()
        # (même le bon code ne marche plus : le code est perdu)
        self.client.post(reverse('phone-login'), {'step': 'code', 'code': good})
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_code_expire(self):
        self.ask_code()
        PhoneVerification.objects.update(created_at='2020-01-01T00:00:00Z')
        self.client.post(reverse('phone-login'), {'step': 'code', 'code': SENT[0][1]})
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_numero_non_confirme_ne_peut_pas_se_connecter(self):
        self.user.phone_verified = False
        self.user.save()
        self.ask_code()
        self.assertEqual(SENT, [])

    def test_trois_codes_par_heure_et_par_numero(self):
        for _ in range(4):
            cache.clear()
            self.ask_code()
        self.assertEqual(len(SENT), 3)

    def test_limite_par_adresse_ip(self):
        """10 demandes par heure et par adresse, même sur des numéros différents."""
        for i in range(12):
            response = self.ask_code(f'034 00 000 {i:02d}')
        self.assertEqual(response.status_code, 429)

    def test_code_d_un_compte_ne_connecte_pas_a_un_autre(self):
        other = Account.objects.create_user('miora@example.com', 'miora', 'motdepasse-solide-456')
        other.phone_number, other.phone_verified = '+261321112233', True
        other.save()
        self.ask_code('032 11 122 33')
        code_of_other = SENT[0][1]
        cache.clear()
        self.ask_code()                           # (la session vise maintenant le numéro de Lova)
        self.client.post(reverse('phone-login'), {'step': 'code', 'code': code_of_other})
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_tous_les_pays(self):
        """Un numéro allemand, écrit à l'allemande avec le pays choisi, ou avec l'indicatif."""
        self.user.phone_number = '+4915123456789'
        self.user.save()
        self.ask_code('0151 23456789', 'sms', 'DE')
        self.assertEqual((SENT[-1][0], SENT[-1][2]), ('+4915123456789', 'sms'))
        cache.clear()
        self.ask_code('+49 151 23456789', 'whatsapp', '')
        self.assertEqual(SENT[-1][0], '+4915123456789')

    @override_settings(SMS_COUNTRIES=['MG'])
    def test_pays_du_sms_reglables(self):
        """SMS_COUNTRIES limite le SMS à certains pays ; WhatsApp et e-mail restent ouverts."""
        self.user.phone_number = '+33612345678'
        self.user.save()
        response = self.ask_code('06 12 34 56 78', 'sms', 'FR')
        self.assertContains(response, "pas proposé vers ce pays")
        self.assertEqual(SENT, [])
        self.ask_code('06 12 34 56 78', 'whatsapp', 'FR')
        self.assertEqual(SENT[-1][2], 'whatsapp')

    @override_settings(SMS_MAX_PER_DAY=2)
    def test_plafond_quotidien_de_sms(self):
        for number in ('+261341111111', '+261342222222'):
            PhoneVerification.objects.create(user=self.user, phone=number, code='x', channel='sms')
        response = self.ask_code()
        self.assertContains(response, 'momentanément indisponibles')
        self.assertEqual(SENT, [])

    def test_la_page_propose_tous_les_pays_sans_deviner_d_apres_la_langue(self):
        """Quelqu'un à l'étranger garde souvent le numéro de son pays : la langue du navigateur ne
        doit pas choisir le pays à sa place (034… aurait été lu comme un numéro allemand)."""
        response = self.client.get(reverse('phone-login'), HTTP_ACCEPT_LANGUAGE='de-DE,de;q=0.9')
        self.assertNotContains(response, ' selected>')
        self.assertContains(response, 'value="MG"')
        self.assertContains(response, 'value="JP"')

    def test_le_pays_est_retenu_apres_une_connexion(self):
        self.ask_code()
        response = self.client.post(reverse('phone-login'), {'step': 'code', 'code': SENT[0][1]})
        self.assertEqual(response.cookies['vz_phone_country'].value, 'MG')
        self.client.logout()                     # (le client de test vide alors ses cookies)
        self.client.cookies['vz_phone_country'] = 'MG'
        self.assertContains(self.client.get(reverse('phone-login')), '<option value="MG" selected>')

    def test_numero_range_par_la_migration_puis_retrouve(self):
        """Un numéro écrit à la main (« 034 12 345 67 ») est rangé en +261341234567 et retrouvé."""
        import importlib
        from django.apps import apps
        Account.objects.filter(pk=self.user.pk).update(phone_number='034 12 345 67')
        importlib.import_module('account.migrations.0012_numeros_au_format_e164').tidy(apps, None)
        self.user.refresh_from_db()
        self.assertEqual(self.user.phone_number, '+261341234567')
        self.ask_code()
        self.assertEqual(len(SENT), 1)

    def test_code_par_email_a_l_adresse_du_compte(self):
        """À l'étranger sans SMS ni WhatsApp : le code part à l'e-mail du compte lié au numéro."""
        self.user.phone_number = '+4915112345678'
        self.user.save()
        response = self.ask_code('+49 151 1234 5678', 'email')
        self.assertContains(response, "adresse e-mail de ce compte")
        self.assertEqual(SENT, [])                          # (ni SMS ni WhatsApp)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['lova@example.com'])
        code = mail.outbox[0].subject.split(': ')[-1]
        self.assertEqual(PhoneVerification.objects.get().channel, 'email')
        self.client.post(reverse('phone-login'), {'step': 'code', 'code': code})
        self.assertEqual(int(self.client.session['_auth_user_id']), self.user.pk)

    def test_email_meme_reponse_pour_un_numero_inconnu(self):
        response = self.ask_code('+49 151 9999 9999', 'email')
        self.assertContains(response, "adresse e-mail de ce compte")
        self.assertEqual(len(mail.outbox), 0)


@override_settings(DEBUG=True, WHATSAPP_TOKEN='', SMS_BACKEND='console')
@mock.patch('account.otp.send_otp', fake_send)
class PhoneVerifyTests(TestCase):
    """Confirmer son numéro quand on est connecté (ce qui existait déjà, avec WhatsApp en plus)."""

    def setUp(self):
        cache.clear()
        SENT.clear()
        self.user = Account.objects.create_user('lova@example.com', 'lova', 'motdepasse-solide-123')
        self.client.force_login(self.user)

    def test_confirmer_son_numero_par_whatsapp(self):
        self.client.post(reverse('account:phone-send-otp'), {'phone': '034 12 345 67', 'country': 'MG', 'channel': 'whatsapp'})
        to, code, channel = SENT[0]
        self.assertEqual((to, channel), ('+261341234567', 'whatsapp'))
        response = self.client.post(reverse('account:phone-verify-otp'), {'phone': '+261341234567', 'code': code})
        self.assertEqual(response.json()['ok'], True)
        self.user.refresh_from_db()
        self.assertTrue(self.user.phone_verified)

    def test_un_email_ne_confirme_jamais_un_numero(self):
        """Confirmer un numéro par e-mail ne prouverait rien : on retombe sur SMS / WhatsApp."""
        self.client.post(reverse('account:phone-send-otp'), {'phone': '034 12 345 67', 'country': 'MG', 'channel': 'email'})
        self.assertEqual(len(mail.outbox), 0)
        self.assertNotEqual(SENT[0][2], 'email')

    def test_un_numero_deja_lie_a_un_autre_compte_est_refuse(self):
        other = Account.objects.create_user('miora@example.com', 'miora', 'motdepasse-solide-456')
        other.phone_number, other.phone_verified = '+261341234567', True
        other.save()
        response = self.client.post(reverse('account:phone-send-otp'), {'phone': '034 12 345 67', 'country': 'MG'})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(SENT, [])


class PhoneNumberTests(TestCase):
    def test_numeros_de_tous_les_pays(self):
        self.assertEqual(sms.normalize_phone('034 12 345 67', 'MG'), '+261341234567')
        self.assertEqual(sms.normalize_phone('06 12 34 56 78', 'FR'), '+33612345678')
        self.assertEqual(sms.normalize_phone('0151 23456789', 'de'), '+4915123456789')
        self.assertEqual(sms.normalize_phone('+1 415 555 2671'), '+14155552671')
        self.assertEqual(sms.normalize_phone('0049 151 2345 6789'), '+4915123456789')
        self.assertIsNone(sms.normalize_phone('06 12 34 56 78'))              # (sans pays ni indicatif)
        self.assertIsNone(sms.normalize_phone('12345', 'FR'))
        self.assertIsNone(sms.normalize_phone('+33 1 42 68 53 00'))           # (fixe : pas de SMS)
        self.assertIsNone(sms.normalize_phone('+33 8 99 23 45 67'))           # (surtaxé)
        self.assertEqual(sms.format_phone_display('+4915123456789'), '+49 1512 3456789')

    @override_settings(WHATSAPP_TOKEN='jeton', WHATSAPP_PHONE_ID='42', DEBUG=False)
    def test_message_whatsapp_envoye_a_meta(self):
        with mock.patch('requests.post') as post:
            post.return_value.status_code = 200
            sms.send_otp('+33612345678', '123456', 'whatsapp')
        url, = post.call_args.args
        body = post.call_args.kwargs['json']
        self.assertIn('/42/messages', url)
        self.assertEqual(body['to'], '33612345678')
        self.assertEqual(body['template']['components'][0]['parameters'][0]['text'], '123456')
        self.assertEqual(post.call_args.kwargs['headers']['Authorization'], 'Bearer jeton')


class AdminPhoneTests(TestCase):
    def test_l_administration_range_le_numero(self):
        from account.admin import AccountAdminForm
        user = Account.objects.create_user('lova@example.com', 'lova', 'motdepasse-solide-123')
        form = AccountAdminForm(instance=user)
        form.cleaned_data = {'phone_number': '+261 34 12 345 67'}
        self.assertEqual(form.clean_phone_number(), '+261341234567')
        form.cleaned_data = {'phone_number': '+33 6 12 34 56 78'}
        self.assertEqual(form.clean_phone_number(), '+33612345678')
        form.cleaned_data = {'phone_number': '034 12 345 67'}      # (sans indicatif : refusé)
        from django import forms
        with self.assertRaises(forms.ValidationError):
            form.clean_phone_number()


class CsrfPageTests(TestCase):
    def test_formulaire_perime_page_claire(self):
        """Formulaire ouvert avant une connexion dans un autre onglet : page claire, pas l'erreur brute."""
        from django.test import Client
        response = Client(enforce_csrf_checks=True).post(reverse('phone-login'), {'step': 'code', 'code': '123456'})
        self.assertEqual(response.status_code, 403)
        self.assertContains(response, 'Cette page a expiré', status_code=403)
