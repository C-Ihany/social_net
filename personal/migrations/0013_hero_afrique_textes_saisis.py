"""
Accueil : le titre et l'accroche saisis dans l'admin parlaient encore de
Madagascar et des Malgaches (« La voix de *Madagascar* a trouvé son réseau. »).
La migration 0012 ne remplaçait que les textes par défaut ; celle-ci remplace
aussi un texte saisi, mais seulement s'il mentionne Madagascar — un texte déjà
réécrit par le propriétaire n'est pas touché.
"""
from django.db import migrations

MOTS = ('madagascar', 'malgache', 'malagasy', 'madagasikara')
TITRE = "La voix de *l'Afrique* a trouvé son réseau."
ACCROCHE = (
    "Pendant trop longtemps, les Africains ont partagé leurs histoires sur des plateformes "
    "qui ne les connaissaient pas. Vazimba change ça : un fil d'actualité, une place de marché "
    "et un guide du continent — au même endroit."
)


def appliquer(apps, schema_editor):
    HeroSettings = apps.get_model('personal', 'HeroSettings')
    for hero in HeroSettings.objects.all():
        maj = {}
        if any(m in (hero.title or '').lower() for m in MOTS):
            maj['title'] = TITRE
        if any(m in (hero.subtitle or '').lower() for m in MOTS):
            maj['subtitle'] = ACCROCHE
        if maj:
            HeroSettings.objects.filter(pk=hero.pk).update(**maj)


class Migration(migrations.Migration):

    dependencies = [
        ('personal', '0012_hero_afrique'),
    ]

    operations = [
        migrations.RunPython(appliquer, migrations.RunPython.noop),
    ]
