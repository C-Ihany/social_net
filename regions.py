"""
regions.py — Où se trouve un membre, une annonce, un groupe, un restaurant.

Vazimba s'adresse à toute l'Afrique : la liste propose les 54 pays du continent
(code ISO à deux lettres, en minuscules), puis la diaspora. Les régions de
Madagascar restent proposées, sous leur code d'origine, parce que des comptes,
des annonces et des restaurants existants les portent déjà : rien n'est à migrer.

Importé par account, post, group, bazar, resto et tourisme pour « Près de chez moi ».
"""

ALL_LABEL = "Toute l'Afrique"

# ── Les 54 pays d'Afrique (ordre alphabétique français) ─────────────────────
AFRICA_COUNTRIES = [
    ('za', 'Afrique du Sud'),
    ('dz', 'Algérie'),
    ('ao', 'Angola'),
    ('bj', 'Bénin'),
    ('bw', 'Botswana'),
    ('bf', 'Burkina Faso'),
    ('bi', 'Burundi'),
    ('cm', 'Cameroun'),
    ('cv', 'Cap-Vert'),
    ('km', 'Comores'),
    ('cg', 'Congo-Brazzaville'),
    ('cd', 'Congo-Kinshasa (RDC)'),
    ('ci', "Côte d'Ivoire"),
    ('dj', 'Djibouti'),
    ('eg', 'Égypte'),
    ('er', 'Érythrée'),
    ('sz', 'Eswatini'),
    ('et', 'Éthiopie'),
    ('ga', 'Gabon'),
    ('gm', 'Gambie'),
    ('gh', 'Ghana'),
    ('gn', 'Guinée'),
    ('gw', 'Guinée-Bissau'),
    ('gq', 'Guinée équatoriale'),
    ('ke', 'Kenya'),
    ('ls', 'Lesotho'),
    ('lr', 'Liberia'),
    ('ly', 'Libye'),
    ('mg', 'Madagascar'),
    ('mw', 'Malawi'),
    ('ml', 'Mali'),
    ('ma', 'Maroc'),
    ('mu', 'Maurice'),
    ('mr', 'Mauritanie'),
    ('mz', 'Mozambique'),
    ('na', 'Namibie'),
    ('ne', 'Niger'),
    ('ng', 'Nigeria'),
    ('ug', 'Ouganda'),
    ('cf', 'République centrafricaine'),
    ('rw', 'Rwanda'),
    ('st', 'Sao Tomé-et-Principe'),
    ('sn', 'Sénégal'),
    ('sc', 'Seychelles'),
    ('sl', 'Sierra Leone'),
    ('so', 'Somalie'),
    ('sd', 'Soudan'),
    ('ss', 'Soudan du Sud'),
    ('tz', 'Tanzanie'),
    ('td', 'Tchad'),
    ('tg', 'Togo'),
    ('tn', 'Tunisie'),
    ('zm', 'Zambie'),
    ('zw', 'Zimbabwe'),
]

# ── Régions de Madagascar (codes d'origine, déjà en base) ───────────────────
MADAGASCAR_REGIONS = [
    ('analamanga',        'Analamanga · Antananarivo'),
    ('vakinankaratra',    'Vakinankaratra · Antsirabe'),
    ('itasy',             'Itasy · Miarinarivo'),
    ('bongolava',         'Bongolava · Tsiroanomandidy'),
    ('haute_matsiatra',   'Haute Matsiatra · Fianarantsoa'),
    ('amoron_i_mania',    "Amoron'i Mania · Ambositra"),
    ('vatovavy',          'Vatovavy · Mananjary'),
    ('fitovinany',        'Fitovinany · Manakara'),
    ('ihorombe',          'Ihorombe · Ihosy'),
    ('atsimo_atsinanana', 'Atsimo-Atsinanana · Farafangana'),
    ('atsinanana',        'Atsinanana · Toamasina'),
    ('analanjirofo',      'Analanjirofo · Fenoarivo Atsinanana'),
    ('alaotra_mangoro',   'Alaotra-Mangoro · Ambatondrazaka'),
    ('boeny',             'Boeny · Mahajanga'),
    ('sofia',             'Sofia · Antsohihy'),
    ('betsiboka',         'Betsiboka · Maevatanana'),
    ('melaky',            'Melaky · Maintirano'),
    ('atsimo_andrefana',  'Atsimo-Andrefana · Toliara'),
    ('androy',            'Androy · Ambovombe'),
    ('anosy',             'Anosy · Tolagnaro'),
    ('menabe',            'Menabe · Morondava'),
    ('diana',             'Diana · Antsiranana'),
    ('sava',              'Sava · Sambava'),
]

DIASPORA = ('diaspora', 'Diaspora africaine')

# Liste plate (valeur vide en tête) : c'est elle que parcourent les formulaires
# et les gabarits — {% for code, label in region_choices %}.
REGION_CHOICES = (
    [('', ALL_LABEL)]
    + AFRICA_COUNTRIES
    + [(code, 'Madagascar — ' + label) for code, label in MADAGASCAR_REGIONS]
    + [DIASPORA]
)

# La même liste, regroupée, pour un <select> à <optgroup>.
REGION_GROUPS = [
    ('Pays', AFRICA_COUNTRIES),
    ('Régions de Madagascar', MADAGASCAR_REGIONS),
    ('Ailleurs', [DIASPORA]),
]

# Libellé court (onglet « ma région », pastille) : le pays, ou la région sans son chef-lieu
REGION_SHORT = dict(AFRICA_COUNTRIES + [(code, label.split(' · ')[0]) for code, label in MADAGASCAR_REGIONS] + [DIASPORA])

# Dictionnaire code → libellé (pour les gabarits et les vues)
REGION_LABELS = dict(REGION_CHOICES)

# Juste les codes valides (sans la valeur vide)
REGION_CODES = [code for code, _ in REGION_CHOICES if code]


# ════════════════════════════════════════════════════════════════════════════
# Pays d'un code de région, et devise
# ════════════════════════════════════════════════════════════════════════════
_COUNTRY_CODES = {code for code, _ in AFRICA_COUNTRIES}
_MADAGASCAR_CODES = {code for code, _ in MADAGASCAR_REGIONS}
COUNTRY_LABELS = dict(AFRICA_COUNTRIES)


def country_of(region):
    """Le pays (code ISO minuscule) d'un code de région : 'sn' → 'sn',
    'analamanga' → 'mg', 'diaspora' ou vide → ''."""
    if region in _COUNTRY_CODES:
        return region
    if region in _MADAGASCAR_CODES:
        return 'mg'
    return ''


# Devise : code ISO → (symbole affiché après le montant, nom)
CURRENCIES = {
    'XOF': ('FCFA', "Franc CFA (Afrique de l'Ouest)"),
    'XAF': ('FCFA', 'Franc CFA (Afrique centrale)'),
    'MGA': ('Ar', 'Ariary'),
    'ZAR': ('R', 'Rand'),
    'DZD': ('DA', 'Dinar algérien'),
    'AOA': ('Kz', 'Kwanza'),
    'BWP': ('P', 'Pula'),
    'BIF': ('FBu', 'Franc burundais'),
    'CVE': ('Esc', 'Escudo cap-verdien'),
    'KMF': ('FC', 'Franc comorien'),
    'CDF': ('FC', 'Franc congolais'),
    'DJF': ('Fdj', 'Franc de Djibouti'),
    'EGP': ('E£', 'Livre égyptienne'),
    'ERN': ('Nfk', 'Nakfa'),
    'SZL': ('E', 'Lilangeni'),
    'ETB': ('Br', 'Birr'),
    'GMD': ('D', 'Dalasi'),
    'GHS': ('GH₵', 'Cedi'),
    'GNF': ('FG', 'Franc guinéen'),
    'KES': ('KSh', 'Shilling kényan'),
    'LSL': ('L', 'Loti'),
    'LRD': ('L$', 'Dollar libérien'),
    'LYD': ('LD', 'Dinar libyen'),
    'MWK': ('MK', 'Kwacha malawien'),
    'MAD': ('DH', 'Dirham marocain'),
    'MUR': ('Rs', 'Roupie mauricienne'),
    'MRU': ('UM', 'Ouguiya'),
    'MZN': ('MT', 'Metical'),
    'NAD': ('N$', 'Dollar namibien'),
    'NGN': ('₦', 'Naira'),
    'UGX': ('USh', 'Shilling ougandais'),
    'RWF': ('FRw', 'Franc rwandais'),
    'STN': ('Db', 'Dobra'),
    'SCR': ('SR', 'Roupie seychelloise'),
    'SLE': ('Le', 'Leone'),
    'SOS': ('Sh', 'Shilling somalien'),
    'SDG': ('SDG', 'Livre soudanaise'),
    'SSP': ('SSP', 'Livre sud-soudanaise'),
    'TZS': ('TSh', 'Shilling tanzanien'),
    'TND': ('DT', 'Dinar tunisien'),
    'ZMW': ('ZK', 'Kwacha zambien'),
    'ZWG': ('ZiG', 'Zimbabwe Gold'),
    # Diaspora
    'EUR': ('€', 'Euro'),
    'USD': ('$', 'Dollar américain'),
    'GBP': ('£', 'Livre sterling'),
    'CAD': ('CA$', 'Dollar canadien'),
    'CHF': ('CHF', 'Franc suisse'),
}

COUNTRY_CURRENCY = {
    'bj': 'XOF', 'bf': 'XOF', 'ci': 'XOF', 'gw': 'XOF', 'ml': 'XOF', 'ne': 'XOF', 'sn': 'XOF', 'tg': 'XOF',
    'cm': 'XAF', 'cf': 'XAF', 'td': 'XAF', 'cg': 'XAF', 'gq': 'XAF', 'ga': 'XAF',
    'mg': 'MGA', 'za': 'ZAR', 'dz': 'DZD', 'ao': 'AOA', 'bw': 'BWP', 'bi': 'BIF', 'cv': 'CVE', 'km': 'KMF',
    'cd': 'CDF', 'dj': 'DJF', 'eg': 'EGP', 'er': 'ERN', 'sz': 'SZL', 'et': 'ETB', 'gm': 'GMD', 'gh': 'GHS',
    'gn': 'GNF', 'ke': 'KES', 'ls': 'LSL', 'lr': 'LRD', 'ly': 'LYD', 'mw': 'MWK', 'ma': 'MAD', 'mu': 'MUR',
    'mr': 'MRU', 'mz': 'MZN', 'na': 'NAD', 'ng': 'NGN', 'ug': 'UGX', 'rw': 'RWF', 'st': 'STN', 'sc': 'SCR',
    'sl': 'SLE', 'so': 'SOS', 'sd': 'SDG', 'ss': 'SSP', 'tz': 'TZS', 'tn': 'TND', 'zm': 'ZMW', 'zw': 'ZWG',
}

DEFAULT_CURRENCY = 'MGA'     # devise des annonces et restaurants créés avant l'ouverture à l'Afrique
DIASPORA_CURRENCY = 'EUR'

# Pour un <select> : « FCFA — Franc CFA (Afrique de l'Ouest) »
CURRENCY_CHOICES = [(code, f'{symbol} — {name}') for code, (symbol, name) in CURRENCIES.items()]


def currency_for_region(region, origin_country=''):
    """Devise proposée par défaut : celle du pays où l'on vit ; pour la diaspora
    l'euro (modifiable dans le formulaire) ; sans rien de renseigné, celle du
    pays d'origine, sinon la devise historique."""
    country = country_of(region)
    if country:
        return COUNTRY_CURRENCY.get(country, DEFAULT_CURRENCY)
    if region == DIASPORA[0]:
        return DIASPORA_CURRENCY
    return COUNTRY_CURRENCY.get(origin_country, DEFAULT_CURRENCY)


def currency_for_user(user):
    """Devise par défaut d'un membre (voir currency_for_region)."""
    if not getattr(user, 'is_authenticated', False):
        return DEFAULT_CURRENCY
    return currency_for_region(getattr(user, 'region', '') or '', getattr(user, 'origin_country', '') or '')


def currency_symbol(code):
    return CURRENCIES.get(code or DEFAULT_CURRENCY, (code or '', ''))[0]


def format_money(value, currency=DEFAULT_CURRENCY):
    """« 12 500 FCFA » : montant entier, milliers séparés par une espace fine
    insécable, symbole de la devise après. Chaîne vide si la valeur est illisible."""
    try:
        amount = int(round(float(value)))
    except (TypeError, ValueError):
        return ''
    return f'{amount:,}'.replace(',', ' ') + ' ' + currency_symbol(currency)


def nearby_q(user, region_field='region', author_field='author'):
    """Filtre « près de chez moi » pour un contenu qui porte un code de région
    (`region_field`) et un auteur (`author_field`, ou None s'il n'y en a pas).

    - on vit dans un pays d'Afrique : le contenu de ce pays (pour Madagascar,
      choisi comme pays : toutes ses régions ; choisi comme région : cette région) ;
    - on vit ailleurs (diaspora) : le contenu du pays d'origine, plus celui des
      membres de la diaspora qui ont la même origine ;
    - rien de renseigné : None (pas de filtre possible).
    """
    from django.db.models import Q
    region = getattr(user, 'region', '') or ''
    origin = getattr(user, 'origin_country', '') or ''
    if region == 'mg':
        return Q(**{f'{region_field}__in': ['mg'] + sorted(_MADAGASCAR_CODES)})
    if region and region != DIASPORA[0]:
        return Q(**{region_field: region})
    if origin:
        codes = ['mg'] + sorted(_MADAGASCAR_CODES) if origin == 'mg' else [origin]
        q = Q(**{f'{region_field}__in': codes})
        if author_field:
            q |= Q(**{region_field: DIASPORA[0], f'{author_field}__origin_country': origin})
        return q
    if region == DIASPORA[0]:
        return Q(**{region_field: region})
    return None


def nearby_label(user):
    """Libellé court de l'onglet « près de chez moi » pour ce membre."""
    region = getattr(user, 'region', '') or ''
    origin = getattr(user, 'origin_country', '') or ''
    if region and region != DIASPORA[0]:
        return REGION_SHORT.get(region, '')
    if origin:
        return COUNTRY_LABELS.get(origin, '')
    return REGION_SHORT.get(region, '')
