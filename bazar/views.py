import io

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import BooleanField, Case, F, Q, When
from django.core.paginator import Paginator
from django.core.files.uploadedfile import InMemoryUploadedFile
from django.http import Http404, JsonResponse
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from .models import Annonce, AnnonceImage, SellerVerification, BazarFavori
from .forms import AnnonceForm
from .uploads import clean_image, clean_images

# ── Constantes ─────────────────────────────────────────────────────────────────
PAGE_SIZE            = 12
MAX_IMAGES           = 8     # vendeur standard
MAX_IMAGES_VERIFIED  = 12    # vendeur vérifié (particulier)
MAX_IMAGES_PRO       = 20    # concessionnaire / boutique pro
BUMP_COOLDOWN_H      = 24    # heures entre deux bumps


# ── Conversion HEIC → JPEG ─────────────────────────────────────────────────────

def _heic_to_jpeg(upload_file):
    """
    Si le fichier est au format HEIC/HEIF (photo iPhone), le convertit en JPEG
    pour la compatibilité navigateur.  Les autres formats passent sans modification.
    Nécessite pillow-heif (installé via requirements.txt + enregistré dans apps.py).
    """
    name = getattr(upload_file, 'name', '') or ''
    if not name.lower().endswith(('.heic', '.heif')):
        return upload_file
    try:
        from PIL import Image
        img = Image.open(upload_file)
        buf = io.BytesIO()
        img.convert('RGB').save(buf, format='JPEG', quality=88, optimize=True)
        buf.seek(0)
        jpeg_name = name.rsplit('.', 1)[0] + '.jpg'
        return InMemoryUploadedFile(
            buf, 'image', jpeg_name, 'image/jpeg', buf.getbuffer().nbytes, None,
        )
    except Exception:
        # En cas d'erreur inattendue, on laisse passer le fichier original
        upload_file.seek(0)
        return upload_file


def _prepare_image(upload_file):
    """HEIC → JPEG puis redimensionnement/WebP : les photos d'annonce de 3 à
    8 Mo étaient stockées et servies en taille d'origine dans la grille."""
    from post.media_utils import compress_image
    return compress_image(_heic_to_jpeg(upload_file))


# ── Liste / Explore ─────────────────────────────────────────────────────────────

def bazar_index(request):
    """
    Page principale du Bazar : liste des annonces actives avec filtres.
    URL: /bazar/
    """
    qs = (
        Annonce.objects
        .filter(status='active')
        .select_related('seller', 'seller__seller_verification')
        .prefetch_related('images')
        # Annotations : vendeur approuvé (any type) + vendeur pro (boutique)
        .annotate(
            seller_verified=Case(
                When(seller__seller_verification__status='approved', then=True),
                default=False,
                output_field=BooleanField(),
            ),
            seller_is_pro=Case(
                When(
                    seller__seller_verification__status='approved',
                    seller__seller_verification__seller_type='pro',
                    then=True,
                ),
                default=False,
                output_field=BooleanField(),
            ),
        )
    )

    # ── Filtres URL ──────────────────────────────────────────────────────────
    q            = request.GET.get('q', '').strip()
    category     = request.GET.get('cat', '').strip()
    condition    = request.GET.get('cond', '').strip()
    location     = request.GET.get('loc', '').strip()
    region       = request.GET.get('region', '').strip()
    price_min    = request.GET.get('pmin', '').strip()
    price_max    = request.GET.get('pmax', '').strip()
    sort         = request.GET.get('sort', 'recent')
    only_verified = request.GET.get('verified', '')

    if q:
        qs = qs.filter(
            Q(title__icontains=q) |
            Q(description__icontains=q) |
            Q(location__icontains=q)
        )

    if category:
        qs = qs.filter(category=category)

    if condition:
        qs = qs.filter(condition=condition)

    if location:
        qs = qs.filter(location__icontains=location)

    if region:
        qs = qs.filter(region=region)

    # « Près de chez moi » : le pays où l'on vit (toutes les régions de Madagascar si c'est
    # le pays choisi) ; pour la diaspora, le pays d'origine et les vendeurs de même origine.
    from regions import currency_for_user, currency_symbol, nearby_label, nearby_q
    near_q = nearby_q(request.user, 'region', 'seller') if request.user.is_authenticated else None
    near = bool(request.GET.get('near')) and near_q is not None
    if near:
        qs = qs.filter(near_q)

    # Un prix n'a de sens que dans une devise : dès qu'un filtre ou un tri par prix est
    # demandé, on ne garde que les annonces dans la devise du visiteur (et on le lui dit).
    def _amount(raw):
        try:
            return max(0, int(raw))
        except ValueError:
            return None
    pmin, pmax = (_amount(price_min) if price_min else None), (_amount(price_max) if price_max else None)
    price_currency = ''
    if pmin is not None or pmax is not None or sort in ('price_asc', 'price_desc'):
        price_currency = currency_for_user(request.user)
        qs = qs.filter(currency=price_currency)
    if pmin is not None:
        qs = qs.filter(Q(price__gte=pmin) | Q(price__isnull=True))
    if pmax is not None:
        qs = qs.filter(price__lte=pmax)

    # Filtre vendeurs vérifiés
    if only_verified:
        qs = qs.filter(seller_verified=True)

    # Filtre type d'annonce (vente / location)
    listing_type = request.GET.get('type', '').strip()
    if listing_type in ('vente', 'location'):
        qs = qs.filter(listing_type=listing_type)

    # Tri — les vendeurs vérifiés sont toujours boostés en tête.
    # Pour 'recent', les annonces bumpées remontent (bumped_at > created_at).
    if sort == 'price_asc':
        qs = qs.order_by('-seller_verified', 'price', F('bumped_at').desc(nulls_last=True), '-created_at')
    elif sort == 'price_desc':
        qs = qs.order_by('-seller_verified', '-price', F('bumped_at').desc(nulls_last=True), '-created_at')
    elif sort == 'popular':
        qs = qs.order_by('-seller_verified', '-views_count', F('bumped_at').desc(nulls_last=True), '-created_at')
    else:
        # Par défaut : bumped_at desc (null en dernier), puis created_at desc
        qs = qs.order_by('-seller_verified', F('bumped_at').desc(nulls_last=True), '-created_at')

    # ── Pagination ────────────────────────────────────────────────────────────
    paginator = Paginator(qs, PAGE_SIZE)
    page_obj  = paginator.get_page(request.GET.get('page'))

    # Chaînes de requête prêtes à l'emploi : pagination (tout sauf `page`) et
    # onglets Tout / À vendre / À louer (tout sauf `page` et `type`).
    params = request.GET.copy()
    params.pop('page', None)
    qs_page = params.urlencode()
    params.pop('type', None)
    qs_tabs = params.urlencode()

    from regions import REGION_CHOICES

    context = {
        'page_obj':        page_obj,
        'categories':      Annonce.CATEGORY_CHOICES,
        'conditions':      Annonce.CONDITION_CHOICES,
        'q':               q,
        'sel_cat':         category,
        'sel_cond':        condition,
        'sel_loc':         location,
        'sel_region':      region,
        'sel_pmin':        price_min,
        'sel_pmax':        price_max,
        'sort':            sort,
        'only_verified':   only_verified,
        'listing_type':    listing_type,
        'total':           paginator.count,
        'region_choices':  REGION_CHOICES,
        'near':            near,
        'near_label':      nearby_label(request.user) if near_q is not None else '',
        'price_currency_symbol': currency_symbol(price_currency) if price_currency else '',
        'user_currency_symbol':  currency_symbol(currency_for_user(request.user)),
        'sel_cat_label':   dict(Annonce.CATEGORY_CHOICES).get(category, ''),
        'qs_page':         qs_page,
        'qs_tabs':         qs_tabs,
        'has_filters':     bool(q or category or condition or region or near or listing_type or only_verified
                                or price_min or price_max or sort != 'recent'),
    }
    return render(request, 'bazar/index.html', context)


# ── Détail d'une annonce ────────────────────────────────────────────────────────

def annonce_detail(request, pk):
    """
    Page de détail d'une annonce.
    URL: /bazar/<pk>/
    """
    annonce = get_object_or_404(
        Annonce.objects
        .select_related('seller', 'seller__seller_verification')
        .prefetch_related('images'),
        pk=pk,
    )

    is_owner = request.user.is_authenticated and request.user == annonce.seller
    # Une annonce en pause ou expirée n'est plus publique : seuls son vendeur et
    # l'équipe la voient encore (« En pause » masque l'annonce, dit le formulaire).
    if annonce.status in ('pause', 'expiree') and not is_owner and not request.user.is_staff:
        raise Http404

    # Incrémenter le compteur de vues (pas pour le vendeur lui-même)
    if not is_owner:
        annonce.increment_views()

    # Annonces similaires (même catégorie, même type, actives, pas la même)
    similaires = (
        Annonce.objects.filter(category=annonce.category, status='active', listing_type=annonce.listing_type)
        .exclude(pk=annonce.pk)
        .select_related('seller')
        .prefetch_related('images')
        [:6]
    )

    # Favori : est-ce que l'utilisateur a déjà sauvegardé cette annonce ?
    try:
        is_saved = (
            request.user.is_authenticated
            and BazarFavori.objects.filter(user=request.user, annonce=annonce).exists()
        )
        fav_count = annonce.favoris.count()
    except Exception:
        # Sécurité si la migration 0006 n'a pas encore été appliquée
        is_saved  = False
        fav_count = 0

    context = {
        'annonce':    annonce,
        'images':     annonce.images.all(),
        'gallery_urls': [img.image.url for img in annonce.images.all()],
        'similaires': similaires,
        'is_owner':   is_owner,
        'is_saved':   is_saved,
        'fav_count':  fav_count,
    }
    return render(request, 'bazar/detail.html', context)


# ── Créer une annonce ───────────────────────────────────────────────────────────

@login_required
def annonce_create(request):
    """
    Formulaire de création d'une nouvelle annonce.
    URL: /bazar/vendre/
    """
    if request.method == 'POST':
        form = AnnonceForm(request.POST, request.FILES)
        if form.is_valid():
            annonce = form.save(commit=False)
            annonce.seller = request.user
            if not request.POST.get('currency'):
                from regions import currency_for_user
                annonce.currency = currency_for_user(request.user)
            # Auto-remplir la région depuis le profil du vendeur
            if not annonce.region:
                annonce.region = getattr(request.user, 'region', '') or ''
            annonce.save()

            # Gérer les images uploadées (multiple files)
            # _heic_to_jpeg convertit silencieusement les photos iPhone si besoin
            limit  = _get_max_images(request.user)
            images, refused = clean_images(request.FILES.getlist('images'), limit)
            for msg in refused:
                messages.warning(request, msg)
            for i, img_file in enumerate(images):
                AnnonceImage.objects.create(
                    annonce=annonce,
                    image=_prepare_image(img_file),
                    is_primary=(i == 0),
                    order=i,
                )

            messages.success(request, _('Votre annonce est publiée.'))
            return redirect('bazar:detail', pk=annonce.pk)
        else:
            messages.error(request, _('Vérifiez les champs signalés.'))
    else:
        from regions import currency_for_user
        form = AnnonceForm(initial={'currency': currency_for_user(request.user)})

    return render(request, 'bazar/create.html', {
        'form':       form,
        'max_images': _get_max_images(request.user),
    })


# ── Modifier une annonce ────────────────────────────────────────────────────────

@login_required
def annonce_edit(request, pk):
    """
    Modifier une annonce existante (vendeur uniquement).
    URL: /bazar/<pk>/modifier/
    """
    annonce = get_object_or_404(Annonce, pk=pk)

    if annonce.seller != request.user:
        messages.error(request, _('Vous ne pouvez pas modifier cette annonce.'))
        return redirect('bazar:detail', pk=annonce.pk)

    if request.method == 'POST':
        form = AnnonceForm(request.POST, request.FILES, instance=annonce)
        if form.is_valid():
            annonce = form.save()

            # Ajouter de nouvelles images
            current_count = annonce.images.count()
            limit         = _get_max_images(request.user)
            new_images, refused = clean_images(request.FILES.getlist('images'), limit - current_count)
            for msg in refused:
                messages.warning(request, msg)
            for i, img_file in enumerate(new_images):
                AnnonceImage.objects.create(
                    annonce=annonce,
                    image=_prepare_image(img_file),
                    is_primary=(current_count == 0 and i == 0),
                    order=current_count + i,
                )

            messages.success(request, _('Annonce mise à jour.'))
            return redirect('bazar:detail', pk=annonce.pk)
        else:
            messages.error(request, _('Vérifiez les champs signalés.'))
    else:
        form = AnnonceForm(instance=annonce)

    return render(request, 'bazar/edit.html', {
        'form':       form,
        'annonce':    annonce,
        'images':     annonce.images.all(),
        'max_images': _get_max_images(request.user),
    })


# ── Supprimer une image ─────────────────────────────────────────────────────────

@login_required
@require_POST
def delete_image(request, img_pk):
    """
    Supprimer une photo d'une annonce (AJAX POST).
    URL: /bazar/image/<img_pk>/supprimer/
    """
    img = get_object_or_404(AnnonceImage, pk=img_pk)
    if img.annonce.seller != request.user:
        return JsonResponse({'error': _('Action non autorisée.')}, status=403)

    annonce_pk = img.annonce.pk
    img.delete()

    # Ré-attribuer la photo principale si nécessaire
    if img.is_primary:
        first = AnnonceImage.objects.filter(annonce_id=annonce_pk).first()
        if first:
            first.is_primary = True
            first.save()

    return JsonResponse({'success': True})


# ── Marquer comme vendue ────────────────────────────────────────────────────────

@login_required
@require_POST
def mark_sold(request, pk):
    """
    Marquer une annonce comme vendue.
    URL: /bazar/<pk>/vendue/
    """
    annonce = get_object_or_404(Annonce, pk=pk)
    if annonce.seller != request.user:
        messages.error(request, _('Action non autorisée.'))
        return redirect('bazar:detail', pk=pk)

    # Une location se clôt en « louée », une vente en « vendue »
    annonce.status = 'louee' if annonce.is_location else 'vendue'
    annonce.save(update_fields=['status'])
    messages.success(request, _('Annonce marquée comme louée.') if annonce.is_location
                     else _('Annonce marquée comme vendue.'))
    return redirect('bazar:mes_annonces')


# ── Supprimer une annonce ───────────────────────────────────────────────────────

@login_required
@require_POST
def annonce_delete(request, pk):
    """
    Supprimer définitivement une annonce.
    URL: /bazar/<pk>/supprimer/
    """
    try:
        annonce = Annonce.objects.get(pk=pk)
    except Annonce.DoesNotExist:
        messages.error(request, _("Cette annonce n'existe pas ou a déjà été supprimée."))
        return redirect('bazar:mes_annonces')

    if annonce.seller != request.user:
        messages.error(request, _('Action non autorisée.'))
        return redirect('bazar:index')

    annonce.delete()
    messages.success(request, _('Annonce supprimée.'))
    return redirect('bazar:mes_annonces')


# ── Bump — remonter une annonce en tête ────────────────────────────────────────

@login_required
@require_POST
def bump_annonce(request, pk):
    """
    Rafraîchit une annonce (la fait remonter en tête des résultats).
    Cooldown : 1 bump toutes les 24 h.
    URL: /bazar/<pk>/bump/
    """
    annonce = get_object_or_404(Annonce, pk=pk)

    if annonce.seller != request.user:
        return JsonResponse({'error': _('Action non autorisée.')}, status=403)

    if annonce.status != 'active':
        return JsonResponse({'error': _('Seules les annonces actives peuvent être remontées.')}, status=400)

    now = timezone.now()
    # Vérifier le cooldown
    if annonce.bumped_at:
        elapsed_h = (now - annonce.bumped_at).total_seconds() / 3600
        if elapsed_h < BUMP_COOLDOWN_H:
            remaining = int(BUMP_COOLDOWN_H - elapsed_h)
            return JsonResponse({
                'error': _('Vous pourrez remonter cette annonce dans %(h)d h.') % {'h': max(1, remaining)},
                'cooldown': True,
                'remaining_h': remaining,
            }, status=429)

    Annonce.objects.filter(pk=pk).update(bumped_at=now)
    return JsonResponse({'success': True, 'bumped_at': now.isoformat()})


# ── Toggle statut — active ↔ pause ─────────────────────────────────────────────

@login_required
@require_POST
def toggle_status(request, pk):
    """
    Bascule le statut d'une annonce entre 'active' et 'pause'.
    AJAX POST. Répond JSON.
    URL: /bazar/<pk>/toggle-statut/
    """
    annonce = get_object_or_404(Annonce, pk=pk)

    if annonce.seller != request.user:
        return JsonResponse({'error': _('Action non autorisée.')}, status=403)

    # Seule la bascule active ↔ pause passe par ici : une annonce vendue, louée ou
    # expirée se republie depuis « Modifier », en connaissance de cause.
    if annonce.status not in ('active', 'pause'):
        return JsonResponse({'error': _('Cette annonce est clôturée : modifiez-la pour la republier.')}, status=400)

    new_status = 'pause' if annonce.status == 'active' else 'active'
    Annonce.objects.filter(pk=pk).update(status=new_status)
    return JsonResponse({
        'success': True,
        'new_status': new_status,
        'label': _('Active') if new_status == 'active' else _('En pause'),
    })


# ── Mes annonces ────────────────────────────────────────────────────────────────

# ── Helper vérification ────────────────────────────────────────────────────────

def _get_max_images(user):
    """Retourne le quota photos selon le statut de vérification du vendeur."""
    try:
        sv = user.seller_verification
        if sv.is_approved:
            if sv.seller_type == SellerVerification.SELLER_TYPE_PRO:
                return MAX_IMAGES_PRO
            return MAX_IMAGES_VERIFIED
    except SellerVerification.DoesNotExist:
        pass
    return MAX_IMAGES


@login_required
def mes_annonces(request):
    """
    Liste des annonces du compte connecté.
    URL: /bazar/mes-annonces/
    """
    qs = (
        Annonce.objects
        .filter(seller=request.user)
        .prefetch_related('images')
        .order_by('-created_at')
    )
    # Récupérer le statut de vérification du compte
    try:
        verification = request.user.seller_verification
    except SellerVerification.DoesNotExist:
        verification = None

    context = {
        'annonces':     qs,
        'count_active': qs.filter(status='active').count(),
        'count_sold':   qs.filter(status__in=('vendue', 'louee')).count(),
        'verification': verification,
    }
    return render(request, 'bazar/mes_annonces.html', context)


# ── Demande de vérification vendeur ────────────────────────────────────────────

@login_required
def request_verification(request):
    """
    Permet à un vendeur de soumettre une demande de vérification.
    Deux types : 'verified' (particulier) et 'pro' (concessionnaire/boutique).
    Si une demande existe déjà et est approuvée/en attente, affiche son statut.
    URL: /bazar/verification/
    """
    try:
        verification = request.user.seller_verification
    except SellerVerification.DoesNotExist:
        verification = None

    if request.method == 'POST':
        new_type = request.POST.get('seller_type', 'verified').strip()
        # Bloquer si en attente — pas de double soumission
        if verification and verification.status == SellerVerification.STATUS_PENDING:
            messages.info(request, _('Vous avez déjà une demande en cours.'))
            return redirect('bazar:mes_annonces')
        # Bloquer si déjà approuvé au même niveau (ou déjà Pro)
        if verification and verification.status == SellerVerification.STATUS_APPROVED:
            if verification.seller_type == SellerVerification.SELLER_TYPE_PRO:
                messages.info(request, _('Votre boutique Pro est déjà active.'))
                return redirect('bazar:mes_annonces')
            if new_type != SellerVerification.SELLER_TYPE_PRO:
                messages.info(request, _('Votre compte est déjà vérifié.'))
                return redirect('bazar:mes_annonces')
            # Sinon : upgrade verified → pro — on continue

        # ── Données communes ──────────────────────────────────────────────────
        seller_type  = request.POST.get('seller_type', 'verified').strip()
        if seller_type not in (SellerVerification.SELLER_TYPE_VERIFIED, SellerVerification.SELLER_TYPE_PRO):
            seller_type = SellerVerification.SELLER_TYPE_VERIFIED
        message_text = request.POST.get('message', '').strip()[:2000]

        # ── Données boutique (uniquement pour type='pro') ─────────────────────
        boutique_name        = ''
        boutique_description = ''
        boutique_category    = ''
        boutique_phone       = ''
        boutique_address     = ''
        boutique_hours       = ''
        boutique_banner_file = None

        if seller_type == SellerVerification.SELLER_TYPE_PRO:
            boutique_name        = request.POST.get('boutique_name', '').strip()[:120]
            boutique_description = request.POST.get('boutique_description', '').strip()[:2000]
            boutique_category    = request.POST.get('boutique_category', '').strip()
            if boutique_category not in dict(SellerVerification.BOUTIQUE_CAT_CHOICES):
                boutique_category = ''
            boutique_phone       = request.POST.get('boutique_phone', '').strip()[:30]
            boutique_address     = request.POST.get('boutique_address', '').strip()[:250]
            boutique_hours       = request.POST.get('boutique_hours', '').strip()[:250]
            boutique_banner_raw  = request.FILES.get('boutique_banner')
            error = ''
            if boutique_banner_raw:
                try:
                    boutique_banner_file = clean_image(boutique_banner_raw)
                except ValidationError as e:
                    error = e.messages[0]
            if not boutique_name:
                error = _('Le nom de la boutique est obligatoire pour une demande Pro.')
            if error:
                messages.error(request, error)
                # On rend la saisie telle quelle (sans rien enregistrer) pour ne pas la perdre
                draft = verification or SellerVerification(seller=request.user)
                draft.seller_type, draft.message = seller_type, message_text
                draft.boutique_name, draft.boutique_description = boutique_name, boutique_description
                draft.boutique_category, draft.boutique_phone = boutique_category, boutique_phone
                draft.boutique_address, draft.boutique_hours = boutique_address, boutique_hours
                return render(request, 'bazar/verification.html', {
                    'verification': verification, 'draft': draft, 'form_open': True,
                })

        if verification:
            # Résoumission après refus — mettre à jour les champs
            verification.seller_type        = seller_type
            verification.status             = SellerVerification.STATUS_PENDING
            verification.message            = message_text
            verification.admin_notes        = ''
            verification.reviewed_at        = None
            verification.reviewed_by        = None
            verification.boutique_name      = boutique_name
            verification.boutique_description = boutique_description
            verification.boutique_category  = boutique_category
            verification.boutique_phone     = boutique_phone
            verification.boutique_address   = boutique_address
            verification.boutique_hours     = boutique_hours
            if boutique_banner_file:
                verification.boutique_banner = boutique_banner_file
            verification.save()
            messages.success(request, _('Demande envoyée. L\'équipe de modération l\'examinera prochainement.'))
        else:
            kw = dict(
                seller=request.user,
                seller_type=seller_type,
                message=message_text,
                boutique_name=boutique_name,
                boutique_description=boutique_description,
                boutique_category=boutique_category,
                boutique_phone=boutique_phone,
                boutique_address=boutique_address,
                boutique_hours=boutique_hours,
            )
            sv = SellerVerification(**kw)
            if boutique_banner_file:
                sv.boutique_banner = boutique_banner_file
            sv.save()
            messages.success(request, _('Demande envoyée. L\'équipe de modération l\'examinera prochainement.'))

        return redirect('bazar:mes_annonces')

    context = {
        'verification': verification,
        'draft': verification,
    }
    return render(request, 'bazar/verification.html', context)


# ── Page publique boutique concessionnaire ──────────────────────────────────────

def boutique_page(request, username):
    """
    Page publique d'un concessionnaire / vendeur pro.
    Affiche la bannière, les infos boutique et toutes ses annonces actives.
    URL: /bazar/boutique/<username>/
    """
    from django.contrib.auth import get_user_model
    User = get_user_model()

    seller = get_object_or_404(User, username=username)

    try:
        verif = seller.seller_verification
    except SellerVerification.DoesNotExist:
        raise Http404

    if not verif.is_pro:
        raise Http404

    annonces_qs = (
        Annonce.objects
        .filter(seller=seller, status='active')
        .prefetch_related('images')
        .order_by(F('bumped_at').desc(nulls_last=True), '-created_at')
    )

    cat_filter = request.GET.get('cat', '').strip()
    if cat_filter:
        annonces_qs = annonces_qs.filter(category=cat_filter)

    if cat_filter not in dict(Annonce.CATEGORY_CHOICES):
        cat_filter = ''
    paginator = Paginator(annonces_qs, PAGE_SIZE)
    page      = paginator.get_page(request.GET.get('page'))

    # Catégories disponibles dans cette boutique (pour le filtre)
    all_annonces = Annonce.objects.filter(seller=seller, status='active')
    cat_dict = dict(Annonce.CATEGORY_CHOICES)
    categories_with_labels = [
        (c, cat_dict.get(c, c))
        for c in all_annonces.values_list('category', flat=True).distinct()
    ]

    return render(request, 'bazar/boutique.html', {
        'boutique_seller':      seller,
        'verif':                verif,
        'page_obj':             page,
        'total':                paginator.count,
        'cat_filter':           cat_filter,
        'categories_with_labels': categories_with_labels,
    })


# ── Favoris ────────────────────────────────────────────────────────────────────

@login_required
@require_POST
def toggle_favori(request, pk):
    """
    AJAX : ajoute ou retire une annonce des favoris de l'utilisateur connecté.
    Retourne JSON { saved: bool, count: int }
    """
    annonce = get_object_or_404(Annonce, pk=pk)
    fav, created = BazarFavori.objects.get_or_create(user=request.user, annonce=annonce)
    if not created:
        fav.delete()
        saved = False
    else:
        saved = True
    count = annonce.favoris.count()
    return JsonResponse({'saved': saved, 'count': count})


@login_required
def mes_favoris(request):
    """
    Page listant les annonces sauvegardées par l'utilisateur connecté.
    """
    try:
        favoris_qs = (
            BazarFavori.objects
            .filter(user=request.user)
            .select_related('annonce__seller')
            .prefetch_related('annonce__images')
        )
        # Exclure les annonces qui ne sont plus publiques (expirées, en pause)
        favoris_qs = [f for f in favoris_qs if f.annonce.status not in ('expiree', 'pause')]
    except Exception:
        favoris_qs = []

    paginator = Paginator(favoris_qs, PAGE_SIZE)
    page      = paginator.get_page(request.GET.get('page'))

    return render(request, 'bazar/favoris.html', {
        'page_obj': page,
        'total':    paginator.count,
    })
