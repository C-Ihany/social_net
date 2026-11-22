import logging
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Avg, F, Q
from django.http import Http404, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _

from bazar.uploads import clean_image, clean_images

from .models import (
    LIEU_CATEGORY_CHOICES, LIEU_CATEGORY_ICONS, REGION_CHOICES, REGION_CODES, REGION_LABELS,
    GuideTouristique, LieuAvis, LieuImage, LieuTouristique, region_search_terms,
)

logger = logging.getLogger(__name__)

MAX_LIEU_IMAGES = 8
CATEGORY_LABELS = dict(LIEU_CATEGORY_CHOICES)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _qs(**params):
    """Chaîne de requête (sans « ? ») avec les seuls paramètres renseignés."""
    return urlencode({k: v for k, v in params.items() if v not in ('', None)})


def _int(value, default, lo, hi):
    """Entier borné : une saisie absente, illisible ou hors bornes ne casse pas la vue."""
    try:
        n = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def _region_q(region):
    """Guides dont le texte libre « régions couvertes » cite la région choisie
    (par sa clé ou par son libellé)."""
    q = Q()
    for term in region_search_terms(region):
        q |= Q(regions_covered__icontains=term)
    return q


def _lieu_form(post, lieu=None):
    """
    Valeurs du formulaire « lieu » (proposition ou modification), nettoyées et bornées
    aux longueurs des colonnes. Renvoie (valeurs, message d'erreur ou '').
    """
    def field(name, max_len=None, default=''):
        value = (post.get(name, default) or '').strip()
        return value[:max_len] if max_len else value

    data = {
        'name':        field('name', 200),
        'description': field('description'),
        'category':    field('category', default=lieu.category if lieu else 'nature'),
        'region':      field('region', default=lieu.region if lieu else ''),
        'address':     field('address', 250),
        'best_period': field('best_period', 120),
        'entry_fee':   field('entry_fee', 80),
        'tips':        field('tips'),
    }
    if not data['name'] or not data['description']:
        return data, _('Le nom et la description sont obligatoires.')
    if data['category'] not in CATEGORY_LABELS:
        return data, _('Choisissez une catégorie dans la liste.')
    if data['region'] and data['region'] not in REGION_CODES:
        return data, _('Choisissez un pays ou une région dans la liste.')
    return data, ''


def _add_lieu_images(request, lieu):
    """Enregistre les photos envoyées (contrôlées par Pillow), dans la limite de 8 par lieu."""
    existing = lieu.images.count()
    uploads = request.FILES.getlist('images')
    room = max(0, MAX_LIEU_IMAGES - existing)
    images, errors = clean_images(uploads, room)
    has_primary = lieu.images.filter(is_primary=True).exists()
    for i, img in enumerate(images):
        LieuImage.objects.create(
            lieu=lieu, image=img,
            is_primary=(not has_primary and i == 0),
            order=existing + i,
        )
    for err in errors:
        messages.warning(request, err)
    if len(uploads) > room:
        messages.warning(request, _('Seules %(n)d photos sont conservées par lieu.') % {'n': MAX_LIEU_IMAGES})


# ── Accueil ────────────────────────────────────────────────────────────────────

def tourisme_home(request):
    """Page d'accueil tourisme: lieux en vedette + guides vérifiés"""
    lieux_vedette = (
        LieuTouristique.objects.filter(is_approved=True)
        .prefetch_related('images')
        .order_by('-views_count')[:8]
    )
    guides = (
        GuideTouristique.objects.filter(is_verified=True, is_active=True)
        .select_related('user')
        [:6]
    )
    return render(request, 'tourisme/home.html', {
        'lieux_vedette': lieux_vedette,
        'guides':        guides,
        'categories':    [(k, label, LIEU_CATEGORY_ICONS.get(k, 'place')) for k, label in LIEU_CATEGORY_CHOICES],
    })


# ── Lieux ──────────────────────────────────────────────────────────────────────

def lieux_list(request):
    """Liste de tous les lieux touristiques approuvés"""
    qs = LieuTouristique.objects.filter(is_approved=True).prefetch_related('images')

    q        = request.GET.get('q', '').strip()
    category = request.GET.get('cat', '').strip()
    region   = request.GET.get('region', '').strip()

    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(description__icontains=q))
    if category:
        qs = qs.filter(category=category)
    if region:
        qs = qs.filter(region=region)

    qs = qs.order_by('-views_count', '-created_at')
    paginator = Paginator(qs, 12)
    page_obj  = paginator.get_page(request.GET.get('page'))

    # Liens des puces de catégorie : construits ici pour que la chaîne de requête
    # soit toujours valide (« ? » puis « & »), quels que soient les filtres actifs.
    def cat_url(cat):
        query = _qs(q=q, region=region, cat=cat)
        return '?' + query if query else request.path

    return render(request, 'tourisme/lieux_list.html', {
        'page_obj':   page_obj,
        'categories': LIEU_CATEGORY_CHOICES,
        'cat_links':  [(k, label, cat_url(k), k == category) for k, label in LIEU_CATEGORY_CHOICES],
        'all_cats_url': cat_url(''),
        'regions':    REGION_CHOICES,
        'q':          q,
        'sel_cat':    category,
        'sel_region': region,
        'sel_cat_label':    CATEGORY_LABELS.get(category, category),
        'sel_region_label': REGION_LABELS.get(region, region),
        'filters_qs': _qs(q=q, cat=category, region=region),
        'total':      paginator.count,
    })


def lieu_detail(request, slug):
    """Page de détail d'un lieu touristique"""
    lieu = get_object_or_404(LieuTouristique, slug=slug)

    # Auteur et staff peuvent voir les lieux non encore approuvés
    is_owner = request.user.is_authenticated and (
        lieu.added_by == request.user or request.user.is_staff
    )
    if not lieu.is_approved and not is_owner:
        raise Http404

    # Soumission d'un avis (POST)
    avis_error = ''
    if request.method == 'POST' and request.user.is_authenticated:
        if request.POST.get('action', 'avis') == 'avis':
            rating  = _int(request.POST.get('rating', 5), 0, 0, 5)
            comment = request.POST.get('comment', '').strip()[:4000]
            if rating < 1 or not comment:
                avis_error = _('Veuillez renseigner un commentaire et une note valide.')
            else:
                try:
                    LieuAvis.objects.update_or_create(
                        lieu=lieu, author=request.user,
                        defaults={
                            'rating':  rating,
                            'comment': comment,
                            'visited_at': request.POST.get('visited_at') or None,
                        },
                    )
                    messages.success(request, _('Merci pour votre avis !'))
                    return redirect('tourisme:lieu_detail', slug=slug)
                except (ValidationError, ValueError):
                    avis_error = _('La date de visite n\'est pas valide.')
                except Exception:
                    logger.exception('lieu_detail: avis non enregistré (lieu %s)', lieu.pk)
                    avis_error = _('Erreur lors de l\'enregistrement de votre avis.')

    if lieu.is_approved and request.method == 'GET':
        LieuTouristique.objects.filter(pk=lieu.pk).update(views_count=F('views_count') + 1)

    # Guides qui couvrent ce lieu
    guides = lieu.guides.filter(is_verified=True, is_active=True).select_related('user')[:4]

    # Lieux similaires
    similaires = (
        LieuTouristique.objects.filter(is_approved=True, category=lieu.category)
        .exclude(pk=lieu.pk)
        .prefetch_related('images')[:4]
    )

    # Avis utilisateurs
    avis_list = lieu.avis.select_related('author').order_by('-created_at')[:20]
    stats = lieu.avis.aggregate(v=Avg('rating'))
    avis_count = lieu.avis.count()
    avg_rating = round(stats['v'] or 0, 1) if avis_count else None

    # Avis de l'utilisateur courant (pour pré-remplir le formulaire)
    user_avis = None
    if request.user.is_authenticated:
        user_avis = lieu.avis.filter(author=request.user).first()

    # Posts liés à ce lieu
    from post.models import Post as PostModel
    lieu_posts = (
        PostModel.objects.filter(lieu=lieu, status='published')
        .select_related('author')
        .order_by('-id')[:6]
    )

    return render(request, 'tourisme/lieu_detail.html', {
        'lieu':        lieu,
        'images':      lieu.images.all(),
        'guides':      guides,
        'similaires':  similaires,
        'avis_list':   avis_list,
        'avis_count':  avis_count,
        'avg_rating':  avg_rating,
        'avg_stars':   int(round(avg_rating)) if avg_rating else 0,
        'user_avis':   user_avis,
        'avis_error':  avis_error,
        'lieu_posts':  lieu_posts,
        'is_owner':    is_owner,
    })


@login_required
def lieu_edit(request, slug):
    """Modifier un lieu soumis par l'utilisateur courant."""
    lieu = get_object_or_404(LieuTouristique, slug=slug)

    # Seul l'auteur ou un staff peut modifier
    if lieu.added_by != request.user and not request.user.is_staff:
        return HttpResponseForbidden(_('Vous ne pouvez pas modifier ce lieu.'))

    error = ''
    form = {f: getattr(lieu, f) for f in
            ('name', 'description', 'category', 'region', 'address', 'best_period', 'entry_fee', 'tips')}
    if request.method == 'POST':
        form, error = _lieu_form(request.POST, lieu)
        if not error:
            for key, value in form.items():
                setattr(lieu, key, value)
            # Un lieu déjà publié, modifié par son auteur, repasse par la modération :
            # sinon le texte et les photos validés pourraient être remplacés librement.
            back_to_review = lieu.is_approved and not request.user.is_staff
            if back_to_review:
                lieu.is_approved = False
            lieu.save()

            # Suppression d'images cochées (identifiants entiers uniquement)
            delete_ids = [int(x) for x in request.POST.getlist('delete_images') if str(x).isdigit()]
            if delete_ids:
                lieu.images.filter(pk__in=delete_ids).delete()

            _add_lieu_images(request, lieu)

            # Toujours une photo principale s'il reste des photos
            if not lieu.images.filter(is_primary=True).exists():
                first = lieu.images.order_by('order', 'pk').first()
                if first:
                    first.is_primary = True
                    first.save(update_fields=['is_primary'])

            if back_to_review:
                messages.success(request, _('Modifications enregistrées. Le lieu sera de nouveau visible après validation par un administrateur.'))
            else:
                messages.success(request, _('Lieu mis à jour.'))
            return redirect('tourisme:lieu_detail', slug=lieu.slug)

    return render(request, 'tourisme/lieu_edit.html', {
        'lieu':       lieu,
        'form':       form,
        'images':     lieu.images.all(),
        'categories': LIEU_CATEGORY_CHOICES,
        'regions':    REGION_CHOICES,
        'error':      error,
    })


@login_required
def lieu_submit(request):
    """Proposer un nouveau lieu touristique (en attente d'approbation admin)."""
    error = ''
    form = {'category': 'nature'}
    if request.method == 'POST':
        form, error = _lieu_form(request.POST)
        if not error:
            lieu = LieuTouristique.objects.create(added_by=request.user, is_approved=False, **form)
            _add_lieu_images(request, lieu)
            messages.success(request, _('Votre lieu a été envoyé ! Il sera visible après validation par un administrateur.'))
            return redirect('tourisme:lieu_detail', slug=lieu.slug)

    return render(request, 'tourisme/lieu_submit.html', {
        'form':       form,
        'categories': LIEU_CATEGORY_CHOICES,
        'regions':    REGION_CHOICES,
        'error':      error,
    })


def lieu_autocomplete(request):
    """API JSON — recherche rapide de lieux (create-box + lieux_list)."""
    q      = request.GET.get('q', '').strip()
    region = request.GET.get('region', '').strip()
    cat    = request.GET.get('cat', '').strip()
    if len(q) < 2:
        return JsonResponse({'results': []})
    qs = LieuTouristique.objects.filter(is_approved=True).filter(
        Q(name__icontains=q) | Q(description__icontains=q)
    )
    if region:
        qs = qs.filter(region=region)
    if cat:
        qs = qs.filter(category=cat)
    results = list(qs.values('id', 'name', 'region', 'category', 'slug')[:8])
    for r in results:
        r['region_label'] = REGION_LABELS.get(r['region'], '')
        r['category_label'] = str(CATEGORY_LABELS.get(r['category'], ''))
        r['icon'] = LIEU_CATEGORY_ICONS.get(r['category'], 'place')
    return JsonResponse({'results': results})


# ── Guides ─────────────────────────────────────────────────────────────────────

def _guides_queryset(q, region, verified_only=False):
    qs = GuideTouristique.objects.filter(is_active=True).select_related('user')
    if verified_only:
        qs = qs.filter(is_verified=True)
    if q:
        qs = qs.filter(
            Q(user__username__icontains=q) |
            Q(bio__icontains=q) | Q(specialities__icontains=q) |
            Q(languages__icontains=q)
        )
    if region:
        qs = qs.filter(_region_q(region))
    return qs.order_by('-is_verified', '-created_at')


def guides_autocomplete(request):
    """API JSON — recherche rapide de guides touristiques."""
    q      = request.GET.get('q', '').strip()
    region = request.GET.get('region', '').strip()
    if len(q) < 2 and not region:
        return JsonResponse({'results': []})
    try:
        results = []
        for g in _guides_queryset(q, region)[:8]:
            try:
                avatar = g.photo.url if g.photo else g.user.profile_image.url
            except Exception:
                avatar = '/static/images/default_profile_image.png'
            results.append({
                'id':          g.pk,
                'name':        g.display_name,
                'is_verified': g.is_verified,
                'specialities': (g.specialities or '')[:60],
                'avatar':      avatar,
                'prix_jour':   int(g.prix_jour) if g.prix_jour else None,
            })
        return JsonResponse({'results': results})
    except Exception:
        # Le détail part dans les journaux, jamais dans la réponse publique.
        logger.exception('guides_autocomplete: recherche impossible')
        return JsonResponse({'results': [], 'error': 'server_error'}, status=500)


def guides_list(request):
    """Liste des guides touristiques (les vérifiés d'abord)"""
    verified_only = request.GET.get('verified', '')
    region        = request.GET.get('region', '').strip()
    q             = request.GET.get('q', '').strip()

    paginator = Paginator(_guides_queryset(q, region, bool(verified_only)), 12)
    page_obj  = paginator.get_page(request.GET.get('page'))
    verified  = '1' if verified_only else ''

    return render(request, 'tourisme/guides_list.html', {
        'page_obj':      page_obj,
        'regions':       REGION_CHOICES,
        'verified_only': verified_only,
        'sel_region':    region,
        'q':             q,
        'total':         paginator.count,
        'filters_qs':    _qs(q=q, region=region, verified=verified),
        # Bascule « vérifiés » : même recherche, filtre inversé
        'verified_toggle_url': '?' + _qs(q=q, region=region, verified='' if verified else '1'),
    })


def guide_profile(request, pk):
    """Page profil d'un guide touristique"""
    guide = get_object_or_404(GuideTouristique.objects.select_related('user'), pk=pk)
    is_owner = request.user.is_authenticated and request.user == guide.user

    # Les lieux encore en attente de validation ne sont pas publics (leur lien renvoie 404)
    lieux = guide.lieux_favoris.prefetch_related('images')
    if not (is_owner or request.user.is_staff):
        lieux = lieux.filter(is_approved=True)

    return render(request, 'tourisme/guide_profile.html', {
        'guide':    guide,
        'lieux':    list(lieux),
        'is_owner': is_owner,
    })


@login_required
def guide_register(request):
    """Devenir guide touristique (créer ou modifier son profil)"""
    guide = None
    try:
        guide = request.user.guide_profile
    except GuideTouristique.DoesNotExist:
        pass

    error = ''
    if request.method == 'POST':
        data = request.POST

        def text(name, max_len=None):
            value = (data.get(name, '') or '').strip()
            return value[:max_len] if max_len else value

        is_new = guide is None
        if is_new:
            guide = GuideTouristique(user=request.user)

        guide.bio              = text('bio')
        guide.languages        = text('languages', 250)
        guide.regions_covered  = text('regions_covered', 2000)
        guide.transport_modes  = text('transport_modes', 250)
        guide.specialities     = text('specialities', 250)
        guide.conditions       = text('conditions', 4000)
        guide.phone            = text('phone', 30)
        # Bornes des colonnes : entier court positif, prix sur 10 chiffres au plus
        guide.prix_jour        = _int(data.get('prix_jour'), 0, 0, 9_999_999_999) or None
        guide.years_experience = _int(data.get('years_experience'), 0, 0, 60)
        guide.max_group_size   = _int(data.get('max_group_size'), 10, 1, 100)

        photo = None
        if not guide.bio:
            error = _('La présentation est obligatoire.')
        elif request.FILES.get('photo'):
            try:
                photo = clean_image(request.FILES['photo'])
            except ValidationError as e:
                error = e.messages[0]

        if not error:
            if photo is not None:
                guide.photo = photo
            guide.save()
            messages.success(request, _('Votre profil de guide est enregistré et visible dans la liste des guides. Le badge « Guide vérifié » est attribué après contrôle par un administrateur.'))
            return redirect('tourisme:guide_profile', pk=guide.pk)
        if is_new:
            # Rien n'est enregistré : on garde les valeurs saisies pour réafficher le formulaire
            guide.pk = None

    return render(request, 'tourisme/guide_register.html', {
        'guide':    guide,
        'is_new':   guide is None or guide.pk is None,
        'regions':  REGION_CHOICES,
        'error':    error,
    })
