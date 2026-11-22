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
