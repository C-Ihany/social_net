"""Codes par SMS / WhatsApp et connexion par numéro de téléphone (étape 1 de la sécurité, 18/11/2026)."""
from unittest import mock

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

    def ask_code(self, phone='034 12 345 67', channel='sms'):
        return self.client.post(reverse('phone-login'), {'step': 'numero', 'phone': phone, 'channel': channel})

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

    def test_numero_etranger_seulement_par_whatsapp(self):
        self.user.phone_number = '+33612345678'
        self.user.save()
        self.ask_code('+33 6 12 34 56 78', 'sms')
        self.assertEqual(SENT, [])
        self.ask_code('+33 6 12 34 56 78', 'whatsapp')
        self.assertEqual(SENT[-1][0], '+33612345678')
        self.assertEqual(SENT[-1][2], 'whatsapp')


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
        self.client.post(reverse('account:phone-send-otp'), {'phone': '034 12 345 67', 'channel': 'whatsapp'})
        to, code, channel = SENT[0]
        self.assertEqual((to, channel), ('+261341234567', 'whatsapp'))
        response = self.client.post(reverse('account:phone-verify-otp'), {'phone': '034 12 345 67', 'code': code})
        self.assertEqual(response.json()['ok'], True)
        self.user.refresh_from_db()
        self.assertTrue(self.user.phone_verified)

    def test_un_numero_deja_lie_a_un_autre_compte_est_refuse(self):
        other = Account.objects.create_user('miora@example.com', 'miora', 'motdepasse-solide-456')
        other.phone_number, other.phone_verified = '+261341234567', True
        other.save()
        response = self.client.post(reverse('account:phone-send-otp'), {'phone': '034 12 345 67'})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(SENT, [])


class PhoneNumberTests(TestCase):
    def test_numeros(self):
        self.assertEqual(sms.normalize_phone('034 12 345 67'), '+261341234567')
        self.assertIsNone(sms.normalize_phone('+33 6 12 34 56 78'))                 # (pas par SMS)
        self.assertEqual(sms.normalize_phone('+33 6 12 34 56 78', True), '+33612345678')
        self.assertEqual(sms.normalize_phone('0049 151 2345 6789', True), '+4915123456789')
        self.assertIsNone(sms.normalize_phone('12345', True))

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
