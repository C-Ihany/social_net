"""
Vazimba s'adresse désormais à toute l'Afrique : l'accroche du Hero suit.

Comme en 0010, la réécriture est conditionnelle : seuls le titre et l'accroche
encore à leur valeur d'origine sont remplacés. Un texte saisi depuis l'admin
est laissé intact.
"""
from django.db import migrations, models


OLD_TITLE = "Le réseau social qui parle *malagasy*."
NEW_TITLE = "Le réseau social qui rassemble *l'Afrique*."
OLD_SUBTITLE = "Un fil d'actualité, une place de marché et un guide du pays — au même endroit."
NEW_SUBTITLE = "Un fil d'actualité, une place de marché et un guide du continent — au même endroit."


def appliquer(apps, schema_editor):
    HeroSettings = apps.get_model('personal', 'HeroSettings')
    HeroSettings.objects.filter(title=OLD_TITLE).update(title=NEW_TITLE)
    HeroSettings.objects.filter(subtitle=OLD_SUBTITLE).update(subtitle=NEW_SUBTITLE)


def revenir(apps, schema_editor):
    HeroSettings = apps.get_model('personal', 'HeroSettings')
    HeroSettings.objects.filter(title=NEW_TITLE).update(title=OLD_TITLE)
    HeroSettings.objects.filter(subtitle=NEW_SUBTITLE).update(subtitle=OLD_SUBTITLE)


class Migration(migrations.Migration):

    dependencies = [
        ('personal', '0011_hero_gradient_lagon'),
    ]

    operations = [
        migrations.AlterField(
            model_name='herosettings',
            name='title',
            field=models.CharField(
                default="Le réseau social qui rassemble *l'Afrique*.",
                help_text="Saut de ligne possible avec \\n. Un mot entre *astérisques* s'affiche dans le serif italique de la charte — par exemple : Le réseau social qui rassemble *l'Afrique*.",
                max_length=200, verbose_name='Titre principal (H1)'),
        ),
        migrations.AlterField(
            model_name='herosettings',
            name='subtitle',
            field=models.TextField(
                default="Un fil d'actualité, une place de marché et un guide du continent — au même endroit.",
                help_text='Une phrase, affichée sous le titre. Les phrases courtes rendent mieux.',
                verbose_name="Texte d'accroche"),
        ),
        migrations.RunPython(appliquer, revenir),
    ]
