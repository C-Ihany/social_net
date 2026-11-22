from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from .models import Annonce, AnnonceImage

try:
    from regions import REGION_CHOICES
except ImportError:
    REGION_CHOICES = []


class AnnonceForm(forms.ModelForm):
    """
    Formulaire principal de création / modification d'annonce.
    Les photos sont gérées séparément via request.FILES.getlist('images') dans la vue.
    """

    class Meta:
        model = Annonce
        fields = [
            'listing_type',
            'title', 'category', 'condition',
            'price', 'price_negotiable',
            # Location-specific
            'prix_location', 'periode_location',
            'caution', 'duree_min',
            # Appartement
            'nb_pieces', 'surface_m2', 'meuble', 'charges_incluses',
            # Voiture en location
            'avec_chauffeur',
            'description',
            'location', 'region',
            'contact_phone', 'show_phone',
            'status',
        ]
        widgets = {
            'listing_type': forms.RadioSelect(attrs={'class': 'form-check-input'}),
            'title': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': _('Ex: Samsung Galaxy A54 128Go'),
                'maxlength': 180,
            }),
            'category': forms.Select(attrs={'class': 'form-control'}),
            'condition': forms.Select(attrs={'class': 'form-control'}),
            'price': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ex: 250000',
                'min': 0,
            }),
            'price_negotiable': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            # Location-specific widgets
            'prix_location': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ex: 150000',
                'min': 0,
            }),
            'periode_location': forms.Select(attrs={'class': 'form-control'}),
            'caution': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ex: 300000',
                'min': 0,
            }),
            'duree_min': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ex: 7',
                'min': 1,
            }),
            # Appartement
            'nb_pieces': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ex: 3',
                'min': 1,
            }),
            'surface_m2': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ex: 65',
                'min': 1,
                'step': '0.1',
            }),
            'meuble': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'charges_incluses': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            # Voiture
            'avec_chauffeur': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 5,
                'placeholder': _('Décrivez votre article : marque, modèle, défauts éventuels…'),
            }),
            'location': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': _('Ex : Dakar, Plateau'),
            }),
            'region': forms.Select(
                attrs={'class': 'form-control'},
                choices=[('', _("Toute l'Afrique"))] + list(REGION_CHOICES),
            ),
            'contact_phone': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': _('Numéro avec indicatif du pays (+…)'),
            }),
            'show_phone': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'status': forms.Select(
                attrs={'class': 'form-control'},
                # Exclure 'expiree' (géré automatiquement par le système)
                choices=[
                    ('active', _('Active — visible par tous')),
                    ('pause', _('En pause — masquée temporairement')),
                    ('vendue', _('Vendue — archivée')),
                    ('louee', _('Louée — archivée')),
                ],
            ),
        }
        labels = {
            'listing_type':      _('Type d\'annonce'),
            'title':             _('Titre de l\'annonce'),
            'category':          _('Catégorie'),
            'condition':         _('État'),
            'price':             _('Prix (Ariary)'),
            'price_negotiable':  _('Prix négociable'),
            'prix_location':     _('Prix de location (Ariary)'),
            'periode_location':  _('Période'),
            'caution':           _('Caution (Ariary)'),
            'duree_min':         _('Durée minimale (jours)'),
            'nb_pieces':         _('Nombre de pièces'),
            'surface_m2':        _('Surface (m²)'),
            'meuble':            _('Meublé'),
            'charges_incluses':  _('Charges incluses'),
            'avec_chauffeur':    _('Avec chauffeur'),
            'description':       _('Description'),
            'location':          _('Ville / quartier'),
            'region':            _('Région'),
            'contact_phone':     _('Téléphone / WhatsApp'),
            'show_phone':        _('Afficher le numéro publiquement'),
            'status':            _('Statut de l\'annonce'),
        }

    # Statuts que le vendeur peut choisir lui-même ('expiree' est posé par le système).
    EDITABLE_STATUSES = ('active', 'pause', 'vendue', 'louee')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Une annonce expirée garde son statut tant que le vendeur n'en choisit pas un autre :
        # sans cette option, la liste retomberait d'elle-même sur « Active ».
        self._was_expired = bool(self.instance.pk and self.instance.status == 'expiree')
        if self._was_expired:
            widget = self.fields['status'].widget
            widget.choices = [('expiree', _('Expirée — choisissez « Active » pour la republier'))] + list(widget.choices)

    def clean_status(self):
        status = self.cleaned_data.get('status')
        if status == 'expiree' and self._was_expired:
            return status
        if status not in self.EDITABLE_STATUSES:
            raise ValidationError(_('Choisissez un statut valide.'))
        return status

    def clean(self):
        data = super().clean()
        if data.get('listing_type') == 'location' and data.get('status') == 'vendue':
            data['status'] = 'louee'
        elif data.get('listing_type') == 'vente' and data.get('status') == 'louee':
            data['status'] = 'vendue'
        return data

    def clean_price(self):
        price = self.cleaned_data.get('price')
        if price is not None and price < 0:
            raise ValidationError(_('Le prix ne peut pas être négatif.'))
        return price

    def clean_prix_location(self):
        prix = self.cleaned_data.get('prix_location')
        if prix is not None and prix < 0:
            raise ValidationError(_('Le prix de location ne peut pas être négatif.'))
        return prix

    def clean_caution(self):
        caution = self.cleaned_data.get('caution')
        if caution is not None and caution < 0:
            raise ValidationError(_('La caution ne peut pas être négative.'))
        return caution
