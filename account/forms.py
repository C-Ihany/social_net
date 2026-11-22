from django import forms
from django.utils.translation import gettext_lazy as _
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import authenticate

from .models import Account

import re

# Pseudo : lettres (accents compris), chiffres, espace et . _ -
# Appliqué aux NOUVEAUX pseudos seulement (inscription, changement de pseudo) :
# les comptes existants et ceux créés depuis Pola ne sont pas touchés.
# Sans cette règle, un pseudo comme <img src=x onerror=…> était accepté et
# s'exécutait partout où le pseudo est inséré dans une page.
_USERNAME_RE = re.compile(r'^[\w .\-]+$', re.UNICODE)


def validate_new_username(username):
    username = (username or '').strip()
    if len(username) < 2 or not _USERNAME_RE.match(username) or not re.search(r'[^\W_]', username):
        raise forms.ValidationError(_(
            'Le nom d’utilisateur ne peut contenir que des lettres, des chiffres, des espaces '
            'et les signes . _ - (2 caractères au moins).'))
    return username


def residence_choices():
    """Où vit le membre, à l'inscription : un pays d'Afrique, ou ailleurs (diaspora).
    (Les régions de Madagascar se choisissent ensuite dans le profil.)"""
    from regions import AFRICA_COUNTRIES, DIASPORA
    return [('', _('Choisir…'))] + list(AFRICA_COUNTRIES) + [(DIASPORA[0], _("Hors d'Afrique (diaspora)"))]


def origin_choices():
    from regions import AFRICA_COUNTRIES
    return [('', _('Le même pays'))] + list(AFRICA_COUNTRIES)


def clean_origin(region, origin):
    """Pays d'origine cohérent avec le lieu de vie : repris du pays où l'on vit
    s'il n'est pas précisé, exigé quand on vit hors d'Afrique."""
    from regions import country_of, DIASPORA
    if not origin:
        origin = country_of(region)
    if region == DIASPORA[0] and not origin:
        raise forms.ValidationError(_("Vous vivez hors d'Afrique : indiquez votre pays d'origine."))
    return origin


class RegistrationForm(UserCreationForm):
    email = forms.EmailField(max_length=254, help_text=_('Obligatoire. Indiquez une adresse e-mail valide.'))
    # Où l'on vit, et d'où l'on vient : un membre né au Sénégal qui vit en Europe
    # choisit « Hors d'Afrique » puis « Sénégal ».
    region = forms.ChoiceField(label=_('Où vivez-vous ?'), choices=[], required=True,
                               error_messages={'required': _('Indiquez le pays où vous vivez.')})
    origin_country = forms.ChoiceField(label=_("Pays d'origine"), choices=[], required=False)

    class Meta:
        model = Account
        fields = ('email', 'username', 'region', 'origin_country', 'password1', 'password2', )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['region'].choices = residence_choices()
        self.fields['origin_country'].choices = origin_choices()

    def clean(self):
        data = super().clean()
        if data.get('region'):
            try:
                data['origin_country'] = clean_origin(data['region'], data.get('origin_country', ''))
            except forms.ValidationError as exc:
                self.add_error('origin_country', exc)
        return data

    def save(self, commit=True):
        account = super().save(commit=False)
        account.region = self.cleaned_data.get('region', '')
        account.origin_country = self.cleaned_data.get('origin_country', '')
        if commit:
            account.save()
        return account

    def clean_email(self):
        email = self.cleaned_data['email'].lower()
        try:
            account = Account.objects.exclude(pk=self.instance.pk).get(email=email)
        except Account.DoesNotExist:
            return email
        raise forms.ValidationError(_('Cette adresse e-mail est déjà utilisée.'))

    def clean_username(self):
        username = validate_new_username(self.cleaned_data['username'])
        try:
            account = Account.objects.exclude(pk=self.instance.pk).get(username=username)
        except Account.DoesNotExist:
            return username
        raise forms.ValidationError(_('Ce nom d’utilisateur est déjà pris.'))



class AccountAuthenticationForm(forms.ModelForm):

    password = forms.CharField(label=_('Mot de passe'), widget=forms.PasswordInput)

    class Meta:
        model = Account
        fields = ('email', 'password')

    def clean(self):
        if self.is_valid():
            email = self.cleaned_data['email']
            password = self.cleaned_data['password']
            if not authenticate(email=email, password=password):
                raise forms.ValidationError(_("E-mail ou mot de passe incorrect."))


ACCEPTED_IMAGE_TYPES = (
    'image/jpeg', 'image/jpg', 'image/png', 'image/gif',
    'image/webp', 'image/bmp', 'image/tiff', 'image/heic', 'image/heif',
)
ACCEPTED_IMAGE_EXTENSIONS = '.jpg,.jpeg,.png,.gif,.webp,.bmp,.tiff,.tif,.heic,.heif'


class AccountUpdateForm(forms.ModelForm):

    bio = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'rows': 3, 'placeholder': _('Parlez un peu de vous…')}),
        label=_('Bio'),
    )
    location = forms.CharField(
        required=False,
        max_length=100,
        widget=forms.TextInput(attrs={'placeholder': _('Ville, pays')}),
        label=_('Localisation'),
    )
    region = forms.ChoiceField(
        required=False,
        label=_('Pays de résidence'),
        choices=[],  # rempli dynamiquement dans __init__
        widget=forms.Select(),
    )
    origin_country = forms.ChoiceField(required=False, label=_("Pays d'origine"), choices=[])

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from regions import REGION_CHOICES
        self.fields['region'].choices = REGION_CHOICES
        self.fields['origin_country'].choices = origin_choices()

    class Meta:
        model = Account
        fields = ('username', 'email', 'profile_image', 'hide_email', 'bio', 'location', 'region', 'origin_country')
        widgets = {
            'profile_image': forms.FileInput(attrs={
                'accept': ACCEPTED_IMAGE_EXTENSIONS,
            }),
        }

    def clean_email(self):
        email = self.cleaned_data['email'].lower()
        try:
            account = Account.objects.exclude(pk=self.instance.pk).get(email=email)
        except Account.DoesNotExist:
            return email
        raise forms.ValidationError(_('Cette adresse e-mail est déjà utilisée.'))

    def clean_username(self):
        username = self.cleaned_data['username']
        if username != self.instance.username:      # pseudo inchangé : jamais refusé
            username = validate_new_username(username)
        try:
            account = Account.objects.exclude(pk=self.instance.pk).get(username=username)
        except Account.DoesNotExist:
            return username
        raise forms.ValidationError(_('Ce nom d’utilisateur est déjà pris.'))

    def clean(self):
        data = super().clean()
        try:
            data['origin_country'] = clean_origin(data.get('region', ''), data.get('origin_country', ''))
        except forms.ValidationError as exc:
            self.add_error('origin_country', exc)
        return data

    def save(self, commit=True):
        account = super(AccountUpdateForm, self).save(commit=False)
        account.username   = self.cleaned_data['username']
        account.email      = self.cleaned_data['email'].lower()
        account.hide_email = self.cleaned_data['hide_email']
        account.bio        = self.cleaned_data.get('bio', '')
        account.location   = self.cleaned_data.get('location', '')
        account.region     = self.cleaned_data.get('region', '')
        account.origin_country = self.cleaned_data.get('origin_country', '')
        # Ne remplace la photo que si un nouveau fichier est uploadé
        new_image = self.cleaned_data.get('profile_image')
        if new_image:
            account.profile_image = new_image
        if commit:
            account.save()
        return account
