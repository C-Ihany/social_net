"""Déplace les fichiers du chat privé déjà envoyés vers le seau R2 privé.

    python manage.py chat_fichiers_prives              # essai : dit ce qui serait fait
    python manage.py chat_fichiers_prives --copier     # copie dans le seau privé
    python manage.py chat_fichiers_prives --copier --supprimer   # puis les retire du seau public

À lancer UNE fois sur Railway, après avoir créé le seau privé et défini R2_PRIVATE_BUCKET_NAME.
Tant qu'un fichier n'est pas copié, il reste visible dans le chat (chat.views.chat_file le
cherche encore dans le seau public), mais aussi par son ancien lien public : c'est la
suppression qui ferme ce lien. On ne supprime qu'après avoir vérifié la copie (même taille).
"""
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand, CommandError

from chat.models import RoomChatMessage
from ZOOT.storage import is_private_storage, private_storage


class Command(BaseCommand):
    help = "Déplace les fichiers du chat privé vers le seau R2 privé."

    def add_arguments(self, parser):
        parser.add_argument('--copier', action='store_true', help="copier pour de vrai (sinon : essai)")
        parser.add_argument('--supprimer', action='store_true', help="retirer ensuite les fichiers du seau public")

    def handle(self, *args, copier=False, supprimer=False, **options):
        private = private_storage()
        if not is_private_storage(private):
            raise CommandError("Le seau privé n'est pas configuré (R2_PRIVATE_BUCKET_NAME, et R2 en production).")
        if supprimer and not copier:
            raise CommandError("--supprimer ne va qu'avec --copier.")
        done = skipped = missing = 0
        for msg in RoomChatMessage.objects.exclude(file='').exclude(file__isnull=True).iterator():
            name = msg.file.name
            if private.exists(name):
                skipped += 1
                if copier and supprimer and default_storage.exists(name) \
                        and default_storage.size(name) == private.size(name):
                    default_storage.delete(name)
                continue
            if not default_storage.exists(name):
                missing += 1
                self.stdout.write(f"introuvable : {name}")
                continue
            if not copier:
                self.stdout.write(f"à copier : {name}")
                done += 1
                continue
            with default_storage.open(name, 'rb') as source:
                saved = private.save(name, source)
            if saved != name:
                raise CommandError(f"copie sous un autre nom ({saved}) : arrêt, rien n'est supprimé")
            if private.size(name) != default_storage.size(name):
                raise CommandError(f"copie incomplète de {name} : arrêt, rien n'est supprimé")
            if supprimer:
                default_storage.delete(name)
            done += 1
        verb = "copiés" if copier else "à copier"
        self.stdout.write(self.style.SUCCESS(f"{done} {verb}, {skipped} déjà dans le seau privé, {missing} introuvables."))
