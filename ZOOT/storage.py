"""
Storage personnalisé pour les fichiers statiques et médias en production.

Deux problèmes à résoudre avec WhiteNoise 6.x :

1. collectstatic : CompressedManifestStaticFilesStorage lève MissingFileError
   pour les fichiers référencés mais absents (ex. *.css.map sourcemaps).
   → On intercepte dans post_process.

2. Rendu des templates : quand {% static 'xxx' %} est évalué, Django appelle
   stored_name() qui appelle hashed_name() → ValueError si le fichier n'est
   pas dans le manifeste. manifest_strict=False ne suffit pas car WhiteNoise
   surcharge hashed_name() sans attraper l'exception.
   → On surcharge stored_name() pour retourner le nom original en fallback.
"""
import logging
import warnings
from django.conf import settings
from whitenoise.storage import CompressedManifestStaticFilesStorage, MissingFileError

# ── Media Cloudflare R2 (S3-compatible) ──────────────────────────────────────
try:
    from storages.backends.s3boto3 import S3Boto3Storage

    class R2MediaStorage(S3Boto3Storage):
        """
        Backend Cloudflare R2 via l'API S3-compatible.
        Hérite de S3Boto3Storage mais utilise l'endpoint R2 configuré dans settings.py.
        Les fichiers uploadés sont publics (ACL public-read via AWS_DEFAULT_ACL).
        """
        # Pas besoin de surcharger : tout vient de settings.py (AWS_* variables)
        pass

except ImportError:
    # En développement sans django-storages, on utilise le backend local.
    from django.core.files.storage import FileSystemStorage as R2MediaStorage  # noqa: F811

# ── Fichiers privés (pièces jointes du chat privé) ───────────────────────────
# Sur Cloudflare R2, un objet n'a pas de droits à lui : si le seau des médias est public
# (r2.dev ou domaine perso), TOUT ce qu'il contient est lisible par qui a le lien. Les
# fichiers du chat privé vont donc dans un seau à part, SANS accès public
# (R2_PRIVATE_BUCKET_NAME), et ne sont donnés que par des liens signés valables 5 minutes,
# après vérification que la personne fait partie de la conversation (chat.views.chat_file).
try:
    from storages.backends.s3boto3 import S3Boto3Storage as _S3

    class R2PrivateStorage(_S3):
        default_acl = None              # (R2 ignore les ACL : c'est le seau qui est privé)
        querystring_auth = True         # liens signés…
        querystring_expire = 300        # …valables 5 minutes
        custom_domain = None            # jamais le domaine public des médias
        file_overwrite = False

        def __init__(self, **settings_override):
            settings_override.setdefault('bucket_name', getattr(settings, 'R2_PRIVATE_BUCKET_NAME', None))
            super().__init__(**settings_override)
except ImportError:
    R2PrivateStorage = None


def private_storage():
    """Le stockage des fichiers privés : le seau privé de R2 s'il est configuré, sinon le
    stockage habituel (en développement : le disque). C'est un appelable donné au champ
    `file` de RoomChatMessage : la migration ne dépend pas de la configuration."""
    from django.core.files.storage import default_storage
    if R2PrivateStorage is not None and getattr(settings, 'R2_PRIVATE_BUCKET_NAME', None) \
            and getattr(settings, 'R2_ACCOUNT_ID', None):
        return R2PrivateStorage()
    return default_storage


def is_private_storage(storage) -> bool:
    """Vrai si ce stockage est le seau privé (liens signés)."""
    return R2PrivateStorage is not None and isinstance(storage, R2PrivateStorage)


# Alias rétro-compatible : les migrations existantes importent AutoMediaCloudinaryStorage
AutoMediaCloudinaryStorage = R2MediaStorage
# ─────────────────────────────────────────────────────────────────────────────

logger = logging.getLogger(__name__)

# CKEditor référence des assets (PNG/SVG/GIF) absents du manifeste → Django émet
# des RuntimeWarning très verbeux à chaque collectstatic. On les supprime ici
# car ils ne représentent aucun vrai problème de fonctionnement.
warnings.filterwarnings(
    "ignore",
    message=r"The CSS file .* references a file which could not be found",
    category=RuntimeWarning,
)


class RelaxedStaticFilesStorage(CompressedManifestStaticFilesStorage):
    manifest_strict = False  # Indique à Django de ne pas lever de ValueError

    def stored_name(self, name):
        """
        Fallback : si le fichier n'est pas dans le manifeste (ValueError),
        retourner le nom original sans hash. Le fichier sera servi tel quel.
        """
        try:
            return super().stored_name(name)
        except (ValueError, Exception) as e:
            logger.warning("RelaxedStaticFilesStorage: fichier absent du manifeste — %s (%s)", name, e)
            return name

    def post_process(self, paths, dry_run=False, **options):
        """
        Surcharge du générateur de post-traitement.

        WhiteNoise ne lève PAS l'exception directement : il la retourne dans
        un tuple (original_path, exception, False). C'est Django qui ensuite
        re-lève l'exception dans collect(). Il faut donc inspecter chaque
        tuple et supprimer ceux qui contiennent une erreur de fichier manquant.
        """
        skipped = []
        gen = super().post_process(paths, dry_run=dry_run, **options)
        while True:
            try:
                result = next(gen)
            except StopIteration:
                break
            except Exception as e:
                # Exception levée directement (cas rare) → on log et on ignore
                logger.warning("collectstatic: exception ignorée — %s", e)
                continue

            # result = (original_path, processed_path, processed)
            # Selon la version de Django/WhiteNoise, l'exception peut être
            # dans result[1] OU result[2] — on vérifie les deux.
            has_error = (
                isinstance(result, (tuple, list))
                and len(result) >= 2
                and any(isinstance(result[i], Exception) for i in range(len(result)))
            )
            if has_error:
                skipped.append(result[0])
                # Ne pas yield → Django ne verra jamais l'erreur
            else:
                yield result

        if skipped:
            logger.warning(
                "collectstatic: %d fichier(s) ignoré(s) pour cause d'assets manquants "
                "(principalement CKEditor). Premier : %s",
                len(skipped),
                skipped[0],
            )