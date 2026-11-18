"""Range les numéros déjà enregistrés au format E.164 (+261341234567).

La connexion par numéro cherche le numéro sous cette forme exacte : un numéro écrit à la main
dans l'administration (« 034 12 345 67 », « +261 34 12 345 67 ») n'était jamais retrouvé.
Un numéro sans indicatif est lu comme malgache : jusqu'au 18/11/2026, le site n'acceptait que
des numéros malgaches (c'est un rangement des anciennes données, pas une règle pour la suite).
Un numéro illisible est laissé tel quel. (Deux comptes avec le même numéro confirmé : la connexion
par numéro les refuse tous les deux, et le journal le signale.)"""
from django.db import migrations


def tidy(apps, schema_editor):
    from account.sms import tidy_phone
    Account = apps.get_model('account', 'Account')
    for account in Account.objects.exclude(phone_number__isnull=True).exclude(phone_number=''):
        raw = account.phone_number
        new = tidy_phone(raw) if raw.strip().startswith(('+', '00')) else tidy_phone(raw, 'MG')
        if new and new != raw:
            account.phone_number = new
            account.save(update_fields=['phone_number'])


class Migration(migrations.Migration):
    dependencies = [('account', '0011_numeros_tous_pays')]
    operations = [migrations.RunPython(tidy, migrations.RunPython.noop)]
