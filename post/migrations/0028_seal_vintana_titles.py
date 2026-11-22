"""Capsules temporelles encore scellées : retire les titres recopiés du message.

Sans titre saisi, l'ancienne création utilisait les 80 premiers caractères du
message comme titre — visible sur la carte scellée, en recherche et dans les
favoris. On remplace ces titres par un libellé neutre.
"""
import html
import re

from django.db import migrations
from django.utils import timezone

NEUTRAL = 'Capsule temporelle'


def seal_titles(apps, schema_editor):
    Post = apps.get_model('post', 'Post')
    qs = Post.objects.filter(post_type='vintana', reveal_date__gt=timezone.now()).exclude(title='')
    for post in qs.iterator():
        message = html.unescape(re.sub(r'<[^>]+>', '', post.body or '')).strip()
        title = (post.title or '').strip()
        if title and title != NEUTRAL and message.startswith(title):
            post.title = NEUTRAL
            post.save(update_fields=['title'])


class Migration(migrations.Migration):

    dependencies = [
        ('post', '0027_alter_post_region'),
    ]

    operations = [
        migrations.RunPython(seal_titles, migrations.RunPython.noop),
    ]
