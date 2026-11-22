"""
bazar/uploads.py — contrôle des images envoyées hors formulaire Django.

Les vues du Bazar, du Tourisme et la demande de vérification rangent des fichiers
dans des ImageField sans passer par un `forms.ImageField` : rien ne vérifiait donc
ni le type ni la taille. `clean_image` fait ce contrôle avec Pillow (le contenu, pas
l'extension), refuse le SVG et tout ce qui n'est pas une image matricielle, puis
convertit les photos HEIC d'iPhone en JPEG.
"""
from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

MAX_IMAGE_MB = 10
ALLOWED_FORMATS = {'JPEG', 'PNG', 'WEBP', 'GIF', 'MPO', 'HEIF', 'HEIC', 'AVIF', 'BMP', 'TIFF'}


def clean_image(upload, max_mb=MAX_IMAGE_MB):
    """
    Vérifie qu'un fichier envoyé est bien une image acceptée et le renvoie prêt à
    être enregistré (HEIC → JPEG). Lève ValidationError (message traduit) sinon.
    """
    if upload is None:
        raise ValidationError(_('Aucun fichier reçu.'))
    name = getattr(upload, 'name', '') or ''
    if getattr(upload, 'size', 0) > max_mb * 1024 * 1024:
        raise ValidationError(_('« %(name)s » dépasse %(mb)d Mo.') % {'name': name, 'mb': max_mb})
    try:
        from PIL import Image
        upload.seek(0)
        img = Image.open(upload)
        fmt = (img.format or '').upper()
        img.verify()          # lit tout le fichier : rejette les images tronquées ou truquées
    except Exception:
        raise ValidationError(_('« %(name)s » n\'est pas une image lisible (JPG, PNG, WebP, HEIC).') % {'name': name})
    finally:
        try:
            upload.seek(0)
        except Exception:
            pass
    if fmt not in ALLOWED_FORMATS:
        raise ValidationError(_('« %(name)s » n\'est pas une image lisible (JPG, PNG, WebP, HEIC).') % {'name': name})
    from .views import _heic_to_jpeg
    return _heic_to_jpeg(upload)


def clean_images(uploads, limit, max_mb=MAX_IMAGE_MB):
    """
    Contrôle une liste de fichiers (au plus `limit`). Renvoie (images valides, messages
    d'erreur) : une photo refusée n'empêche pas d'enregistrer les autres.
    """
    ok, errors = [], []
    for f in list(uploads)[:max(0, limit)]:
        try:
            ok.append(clean_image(f, max_mb=max_mb))
        except ValidationError as e:
            errors.append(e.messages[0])
    return ok, errors
