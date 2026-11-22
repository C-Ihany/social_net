from django.db import migrations
from django.utils.text import slugify


def repair_slugs(apps, schema_editor):
    """Les lieux dont le nom n'a aucune lettre latine avaient un slug vide (ou « -1 »,
    « -2 »… pour les suivants) : leur lien levait NoReverseMatch. On leur donne
    « lieu », « lieu-1 »…"""
    Lieu = apps.get_model('tourisme', 'LieuTouristique')
    taken = set(Lieu.objects.values_list('slug', flat=True))
    for lieu in Lieu.objects.order_by('pk'):
        if (lieu.slug or '').strip('-_'):
            continue
        base = slugify(lieu.name)[:200] or 'lieu'
        slug, n = base, 1
        while slug in taken:
            slug = f'{base}-{n}'
            n += 1
        taken.add(slug)
        Lieu.objects.filter(pk=lieu.pk).update(slug=slug)


class Migration(migrations.Migration):

    dependencies = [
        ('tourisme', '0003_alter_guidetouristique_languages_and_more'),
    ]

    operations = [
        migrations.RunPython(repair_slugs, migrations.RunPython.noop),
    ]
