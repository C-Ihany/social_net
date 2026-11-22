from django.shortcuts import render, redirect
from django.http import Http404, HttpResponse, JsonResponse
from django.contrib.auth import login, authenticate, logout
from django.conf import settings
from django.core.paginator import Paginator
from django.template.loader import render_to_string

from django.core.files.storage import default_storage
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST as _require_POST
from django.utils.translation import gettext as _, gettext_lazy
from django.templatetags.static import static as static_url
from django.core.files.storage import FileSystemStorage
import os
from PIL import Image
import json
import base64
import uuid
import requests
import logging
from django.core import files

logger = logging.getLogger(__name__)


from account.forms import RegistrationForm, AccountAuthenticationForm, AccountUpdateForm
from account.models import Account, PhoneVerification, UserBlock
from django.db.models import Q as models_Q
from friend.utils import get_friend_request_or_false
from friend.friend_request_status import FriendRequestStatus
from friend.models import FriendList, FriendRequest

from post.models import Post, Follow
from post.models import Comment as CommentModel, Reaction as ReactionModel, PostMedia
from post.views import _attach_media

# Taille maximale acceptée pour un avatar envoyé en base64.
MAX_AVATAR_BYTES = 10 * 1024 * 1024


def register_view(request, *args, **kwargs):
	user = request.user
	if user.is_authenticated:
		return redirect('post:post-view')

	context = {}
	if request.POST:
		form = RegistrationForm(request.POST)
		accept_terms = request.POST.get('accept_terms')
		if not accept_terms:
			context['registration_form'] = form
			context['terms_error'] = True
		elif form.is_valid():
			account = form.save()
			# Enregistrer la date d'acceptation des CGU
			from django.utils import timezone
			account.cgu_accepted_at = timezone.now()
			account.save(update_fields=['cgu_accepted_at'])
			email = form.cleaned_data.get('email').lower()
			raw_password = form.cleaned_data.get('password1')
			account = authenticate(email=email, password=raw_password)
			# authenticate() peut renvoyer None (compte désactivé, backend
			# indisponible) — login(request, None) lèverait une 500.
			if account is not None:
				login(request, account)
			else:
				logger.warning("register_view : authentification impossible juste après l'inscription de %s", email)
				return redirect('login')
			destination = _safe_redirect_target(request, kwargs.get("next") or request.GET.get("next"))
			if destination:
				return redirect(destination)
			return redirect('post:post-view')
		else:
			context['registration_form'] = form
	else:
		form = RegistrationForm()
		context['registration_form'] = form
	return render(request, 'account/register.html', context)


def login_view(request, *args, **kwargs):
	context = {}
	user = request.user
	if user.is_authenticated:
		return redirect("post:index")

	destination = get_redirect_if_exists(request)

	if request.POST:
		form = AccountAuthenticationForm(request.POST)
		if form.is_valid():
			email = request.POST['email']
			password = request.POST['password']
			user = authenticate(email=email, password=password)
			if user:
				login(request, user)
				if destination:
					return redirect(destination)
				return redirect("post:index")
	else:
		form = AccountAuthenticationForm()

	context['login_form'] = form
	return render(request, "account/login.html", context)


def logout_view(request):
	"""Déconnexion en POST uniquement.

	En GET (anciens liens, application Android, <img src="/logout/"> sur un
	site tiers), on affiche une petite page de confirmation au lieu de
	déconnecter : une requête GET n'est pas protégée contre le CSRF.
	"""
	if request.method == 'POST':
		logout(request)
		return redirect('landing')
	if not request.user.is_authenticated:
		return redirect('landing')
	return render(request, 'account/logout_confirm.html')


def get_redirect_if_exists(request):
	"""Retourne le ?next= de la requête, uniquement s'il pointe vers ce site.

	Sans cette validation, /login/?next=https://evil.example.com redirigeait
	l'utilisateur vers un site tiers juste après une connexion réussie
	(redirection ouverte → hameçonnage crédible).
	"""
	nxt = request.GET.get("next") if request.GET else None
	return _safe_redirect_target(request, nxt)


def _safe_redirect_target(request, url):
	"""Ne renvoie `url` que si elle reste sur le domaine courant."""
	if not url:
		return None
	if not url_has_allowed_host_and_scheme(
		url,
		allowed_hosts={request.get_host()},
		require_https=request.is_secure(),
	):
		return None
	return url


def _visible_posts_for(viewer, author):
	"""Posts de `author` visibles par `viewer`, du plus récent au plus ancien."""
	from post.visibility import visible_posts
	qs = Post.objects.filter(author=author).select_related('author', 'group').order_by("-id")
	return visible_posts(qs, viewer, author=author)


def account_view(request, *args, **kwargs):
	context = {}
	user_id = kwargs.get("user_id")

	try:
		account = Account.objects.get(pk=user_id)
	except Account.DoesNotExist:
		raise Http404("Utilisateur introuvable.")
	if not account.visible_to(request.user):
		# (compte « Pola seulement » : invisible sur le réseau social, même réponse qu'inconnu)
		raise Http404("Utilisateur introuvable.")

	# Posts (first page) — seuls les posts réellement visibles par le visiteur.
	all_posts_qs = _visible_posts_for(request.user, account)
	paginator   = Paginator(all_posts_qs, 6)
	first_page  = paginator.get_page(1)
	posts = list(first_page)

	# Enrich posts with reactions + threaded comments
	from django.db.models import Count
	post_ids = [p.id for p in posts]
	if post_ids:
		reactions_qs = (
			ReactionModel.objects.filter(post_id__in=post_ids)
			.values('post_id', 'reaction_type')
			.annotate(c=Count('id'))
		)
		reactions_by_post = {}
		for row in reactions_qs:
			reactions_by_post.setdefault(row['post_id'], {})[row['reaction_type']] = row['c']

		user_reaction_by_post = {}
		if request.user.is_authenticated:
			user_reactions_qs = ReactionModel.objects.filter(
				post_id__in=post_ids, user=request.user
			).values_list('post_id', 'reaction_type')
			user_reaction_by_post = {pid: rtype for pid, rtype in user_reactions_qs}

		from post.comments_utils import load_comments_grouped
		top_by_post, comment_totals = load_comments_grouped(post_ids, viewer=request.user)

		for post in posts:
			post.user_reaction   = user_reaction_by_post.get(post.id)
			post.reaction_counts = reactions_by_post.get(post.id, {})
			post.total_reactions = sum(post.reaction_counts.values())
			top = top_by_post.get(post.id, [])
			for c in top:
				if not hasattr(c, 'reply_list'):
					c.reply_list = []
			post.page_comments  = top
			post.total_comments = comment_totals.get(post.id, 0)
		_attach_media(posts, post_ids)
	else:
		for post in posts:
			post.user_reaction   = None
			post.reaction_counts = {}
			post.total_reactions = 0
			post.page_comments   = []
			post.total_comments  = 0
			post.media_list      = []

	if account:
		context['profile_user'] = account   # objet Account complet (pour score_fihavanana, etc.)
		context['id'] = account.id
		context['username'] = account.username
		context['email'] = account.email
		context['profile_image'] = account.profile_image.url
		context['hide_email'] = account.hide_email
		context['bio'] = account.bio
		context['location'] = account.location
		context['date_joined'] = account.date_joined
		from regions import REGION_LABELS
		context['region_label'] = REGION_LABELS.get(account.region or '', '')

		# Cover image
		cover_url = None
		if account.cover_image and account.cover_image.name:
			try:
				if isinstance(account.cover_image.storage, FileSystemStorage):
					try:
						if os.path.exists(account.cover_image.storage.path(account.cover_image.name)):
							cover_url = account.cover_image.url
					except Exception:
						pass
				else:
					cover_url = account.cover_image.url
			except Exception:
				pass
		context['cover_image_url'] = cover_url

		try:
			friend_list = FriendList.objects.get(user=account)
		except FriendList.DoesNotExist:
			friend_list = FriendList(user=account)
			friend_list.save()
		friends = friend_list.friends.all()
		context['friends'] = friends
		context['friends_count'] = friends.count()
		context['posts'] = posts
		context['post_count'] = all_posts_qs.count()
		context['posts_has_next'] = first_page.has_next()
		context['posts_next_page'] = 2 if first_page.has_next() else None

		# Photos tab
		from collections import namedtuple
		PhotoItem = namedtuple('PhotoItem', ['url', 'title', 'post_id'])
		photo_list = []
		# Uniquement les photos des posts que le visiteur a le droit de voir :
		# sans ce filtre, les images des brouillons, des posts programmés et
		# des groupes privés étaient exposées à n'importe qui.
		for m in PostMedia.objects.filter(
			post__in=all_posts_qs.order_by().values('id'), media_type='image'
		).select_related('post').order_by('-post__post_date')[:50]:
			media_url = m.url
			if media_url:
				photo_list.append(PhotoItem(url=media_url, title=m.post.title, post_id=m.post_id))

		context['photos'] = photo_list
		context['is_self'] = False
		context['is_friend'] = False
		context['request_sent'] = FriendRequestStatus.NO_REQUEST_SENT.value

		context['is_blocked'] = False
		context['can_see_friends'] = False
		if request.user.is_authenticated:
			context['is_blocked'] = UserBlock.objects.filter(blocker=request.user, blocked=account).exists()
			if request.user == account:
				context['is_self'] = True
				context['can_see_friends'] = True
				# Incoming friend requests for self
				try:
					friend_requests = FriendRequest.objects.filter(receiver=account, is_active=True)
					context['friend_requests'] = friend_requests
				except Exception:
					context['friend_requests'] = []
			else:
				context['is_friend'] = friends.filter(pk=request.user.pk).exists()
				# Même règle que friend.views.friends_list_view : la liste
				# d'amis n'est montrée qu'au membre lui-même et à ses amis.
				context['can_see_friends'] = context['is_friend']

				# Cas 1 : l'autre (account) nous a envoyé une demande → THEM_SENT_TO_YOU = 0
				fr_from_them = get_friend_request_or_false(account, request.user)
				if fr_from_them is not False:
					context['request_sent'] = FriendRequestStatus.THEM_SENT_TO_YOU.value
					context['pending_friend_request_id'] = fr_from_them.id

				else:
					# Cas 2 : nous avons envoyé une demande à l'autre → YOU_SENT_TO_THEM = 1
					fr_from_us = get_friend_request_or_false(request.user, account)
					if fr_from_us is not False:
						context['request_sent'] = FriendRequestStatus.YOU_SENT_TO_THEM.value
						context['pending_friend_request_id'] = fr_from_us.id
					else:
						# Cas 3 : aucune demande en cours
						context['request_sent'] = FriendRequestStatus.NO_REQUEST_SENT.value
						context['pending_friend_request_id'] = None

		if not context['can_see_friends']:
			context['friends'] = friends.none()

	return render(request, 'account/account.html', context)


def account_search_view(request):
	"""Ancienne page /search/ : une seule page de résultats, /recherche/.

	La recherche du menu mobile arrivait ici, celle de la barre de bureau sur
	/recherche/ (posts, annonces, membres) : deux pages différentes pour la
	même action. L'adresse est gardée en redirection pour les anciens liens.
	"""
	from django.urls import reverse
	from urllib.parse import urlencode
	query = request.GET.get('q', '').strip()
	url = reverse('recherche')
	if query:
		url += '?' + urlencode({'q': query})
	return redirect(url)


def edit_account_view(request, *args, **kwargs):
	if not request.user.is_authenticated:
		return redirect('login')
	user_id = kwargs.get('user_id')
	try:
		account = Account.objects.get(pk=user_id)
	except Account.DoesNotExist:
		raise Http404("Utilisateur introuvable.")
	if request.user != account:
		return redirect('account:edit', user_id=request.user.pk)

	context = {}
	if request.POST:
		form = AccountUpdateForm(request.POST, request.FILES, instance=request.user)
		if form.is_valid():
			form.save()
			return redirect('account:view', user_id=account.id)
		else:
			context['form'] = form
	else:
		form = AccountUpdateForm(
			initial={
				'email':      account.email,
				'username':   account.username,
				'hide_email': account.hide_email,
				'bio':        account.bio,
				'location':   account.location,
				'region':     account.region,
				'region_label': __import__('regions').REGION_LABELS.get(account.region or '', ''),
			}
		)
	context['form'] = form
	context['DATA_UPLOAD_MAX_MEMORY_SIZE'] = settings.DATA_UPLOAD_MAX_MEMORY_SIZE
	from regions import REGION_CHOICES
	context['region_choices'] = REGION_CHOICES
	context['blocked_users'] = Account.objects.filter(blocks_received__blocker=request.user).order_by('username')
	# Confirmation du numéro : tous les pays, et le moyen de recevoir le code
	context['phone_countries'] = country_choices(get_language() or 'fr')
	context['phone_country'] = otp_codes.guess_region(request)
	context['phone_channels'] = otp_channels()
	return render(request, 'account/edit_account.html', context)


def save_temp_profile_image_from_base64String(imageString, user):
	"""Écrit l'image envoyée en base64 dans un fichier temporaire propre à l'utilisateur.

	Le nom de fichier était auparavant une constante partagée
	(temp_profile_image.png) : deux recadrages simultanés écrivaient dans le
	même fichier et l'un des utilisateurs se retrouvait avec la photo de
	l'autre en avatar. Le nom inclut désormais l'identifiant du compte et un
	suffixe aléatoire.
	"""
	os.makedirs(settings.TEMP, exist_ok=True)
	image = base64.b64decode(imageString, validate=False)
	if len(image) > MAX_AVATAR_BYTES:
		raise ValueError("Image trop volumineuse (max 10 Mo).")
	filename = f'temp_profile_{user.pk}_{uuid.uuid4().hex}.png'
	url = os.path.join(settings.TEMP, filename)
	with open(url, 'wb') as f:
		f.write(image)
	return url


@_require_POST
def crop_image(request, *args, **kwargs):
	user = request.user
	if not user.is_authenticated:
		return JsonResponse({'result': 'error', 'exception': _('Connexion requise.')}, status=401)

	imageString = request.POST.get("image")
	if not imageString:
		return JsonResponse({'result': 'error', 'exception': _('Aucune image reçue.')}, status=400)

	url = None
	try:
		url = save_temp_profile_image_from_base64String(imageString, user)
		with Image.open(url) as img:
			img.load()

			cropX = int(float(str(request.POST.get("cropX"))))
			cropY = int(float(str(request.POST.get("cropY"))))
			cropWidth = int(float(str(request.POST.get("cropWidth"))))
			cropHeight = int(float(str(request.POST.get("cropHeight"))))

			if cropX < 0: cropX = 0
			if cropY < 0: cropY = 0

			cropped_img = img.crop((cropX, cropY, cropX + cropWidth, cropY + cropHeight))
			cropped_img = cropped_img.convert('RGB').resize((200, 200), Image.LANCZOS)
		cropped_img.save(url, format='PNG')

		user.profile_image.delete(save=False)

		# Le fichier était laissé ouvert : sous Windows le descripteur
		# empêchait ensuite la suppression du fichier temporaire.
		with open(url, 'rb') as fh:
			user.profile_image.save(
				get_profile_image_filepath(user, url),
				files.File(fh),
			)
		user.save()

		return JsonResponse({
			'result': 'success',
			'cropped_profile_image': user.profile_image.url,
		})
	except Exception as e:
		# Ne pas renvoyer le détail de l'exception au client (chemins serveur,
		# détails d'implémentation) — il est journalisé côté serveur.
		logger.exception("crop_image a échoué pour l'utilisateur %s : %s", user.pk, e)
		return JsonResponse({
			'result': 'error',
			'exception': _("Le recadrage de l'image a échoué."),
		}, status=400)
	finally:
		if url:
			try:
				os.remove(url)
			except OSError:
				pass


def get_profile_image_filepath(user, filename):
	return f'profile_images/{user.pk}/profile_image.png'


def global_search_api(request):
	"""API endpoint for the header search bar (returns JSON)."""
	query = request.GET.get('q', '').strip()
	if not query or len(query) < 2:
		return JsonResponse({'users': [], 'posts': [], 'hashtags': [], 'annonces': []})

	from django.db.models import Q
	from post.models import Hashtag
	from bazar.models import Annonce

	# Users
	users_qs = Account.objects.filter(Q(username__icontains=query)).exclude(pola_mode=Account.POLA_ONLY)[:6]
	users = []
	for u in users_qs:
		try:
			avatar = u.profile_image.url
		except Exception:
			avatar = static_url('images/profile_pic.png')
		users.append({'id': u.id, 'username': u.username, 'avatar': avatar})

	# Hashtags
	hashtags_qs = Hashtag.objects.filter(tag__icontains=query)[:4]
	hashtags = [{'id': h.id, 'tag': h.tag, 'count': h.count} for h in hashtags_qs]

	# Posts
	# visible_posts() : ni brouillons, ni posts de groupes privés, ni auteurs bloqués.
	from post.visibility import visible_posts
	posts_qs = visible_posts(
		Post.objects.filter(Q(title__icontains=query) | Q(body__icontains=query)).select_related('author'),
		request.user,
	)[:5]
	posts = [{'id': p.id, 'title': p.title or (p.body or '')[:60], 'author': p.author.username} for p in posts_qs]

	# Annonces bazar
	annonces_qs = Annonce.objects.filter(
		Q(title__icontains=query), status='active'
	).prefetch_related('images')[:4]
	annonces = []
	for a in annonces_qs:
		img_url = None
		try:
			first_img = a.images.first()
			if first_img:
				img_url = first_img.image.url
		except Exception:
			pass
		annonces.append({'id': a.id, 'title': a.title, 'price': a.formatted_price if a.price else None, 'img': img_url})

	return JsonResponse({'users': users, 'posts': posts, 'hashtags': hashtags, 'annonces': annonces})


def profile_posts_more(request, *args, **kwargs):
	"""API pour l'infinite scroll sur la page profil."""
	user_id = kwargs.get('user_id')
	try:
		account = Account.objects.get(pk=user_id)
	except Account.DoesNotExist:
		return JsonResponse({'posts_html': '', 'has_next': False})
	if not account.visible_to(request.user):
		return JsonResponse({'posts_html': '', 'has_next': False})

	# ?page=abc levait une ValueError non interceptée (500).
	try:
		page_num = int(request.GET.get('page', 2))
	except (TypeError, ValueError):
		page_num = 2
	all_posts_qs = _visible_posts_for(request.user, account)
	paginator = Paginator(all_posts_qs, 6)
	page = paginator.get_page(page_num)
	posts = list(page)

	# Enrich
	from django.db.models import Count
	post_ids = [p.id for p in posts]
	if post_ids:
		reactions_qs = (
			ReactionModel.objects.filter(post_id__in=post_ids)
			.values('post_id', 'reaction_type')
			.annotate(c=Count('id'))
		)
		reactions_by_post = {}
		for row in reactions_qs:
			reactions_by_post.setdefault(row['post_id'], {})[row['reaction_type']] = row['c']

		user_reaction_by_post = {}
		if request.user.is_authenticated:
			user_reactions_qs = ReactionModel.objects.filter(
				post_id__in=post_ids, user=request.user
			).values_list('post_id', 'reaction_type')
			user_reaction_by_post = {pid: rtype for pid, rtype in user_reactions_qs}

		from post.comments_utils import load_comments_grouped
		top_by_post, comment_totals = load_comments_grouped(post_ids, viewer=request.user)
		for post in posts:
			post.user_reaction   = user_reaction_by_post.get(post.id)
			post.reaction_counts = reactions_by_post.get(post.id, {})
			post.total_reactions = sum(post.reaction_counts.values())
			top = top_by_post.get(post.id, [])
			for c in top:
				if not hasattr(c, 'reply_list'):
					c.reply_list = []
			post.page_comments  = top
			post.total_comments = comment_totals.get(post.id, 0)
		_attach_media(posts, post_ids)
	else:
		for post in posts:
			post.user_reaction = None
			post.reaction_counts = {}
			post.total_reactions = 0
			post.page_comments = []
			post.total_comments = 0
			post.media_list = []

	posts_html = render_to_string(
		'post/post_cards_fragment.html',
		{'posts_of_the_page': posts, 'request': request},
		request=request,
	)
	return JsonResponse({
		'posts_html': posts_html,
		'has_next': page.has_next(),
		'next_page': page_num + 1 if page.has_next() else None,
	})


def update_cover_image(request):
	"""AJAX endpoint pour changer la photo de couverture."""
	if not request.user.is_authenticated:
		return JsonResponse({'error': _('Non authentifié.')}, status=401)
	if request.method != 'POST':
		return JsonResponse({'error': _('Méthode non autorisée.')}, status=405)

	cover_file = request.FILES.get('cover')
	if not cover_file:
		return JsonResponse({'error': _('Aucun fichier reçu.')}, status=400)

	allowed_mime = {
		'image/jpeg', 'image/jpg', 'image/png', 'image/webp',
		'image/gif', 'image/heic', 'image/heif', 'image/bmp', 'image/tiff',
	}
	mime = (cover_file.content_type or '').split(';')[0].strip().lower()
	if mime not in allowed_mime:
		return JsonResponse({'error': _('Format non supporté (jpeg, png, webp, gif, heic…).')}, status=400)

	if cover_file.size > 10 * 1024 * 1024:
		return JsonResponse({'error': _('Fichier trop volumineux (max 10 Mo).')}, status=400)

	# L'extension était reprise du nom de fichier envoyé par le client : un
	# fichier « image/png » nommé payload.html était stocké tel quel sur le
	# bucket public et servi en text/html (XSS stocké sur le domaine média).
	# On la déduit désormais du type MIME validé ci-dessus.
	_EXT_BY_MIME = {
		'image/jpeg': '.jpg', 'image/jpg': '.jpg', 'image/png': '.png',
		'image/webp': '.webp', 'image/gif': '.gif', 'image/bmp': '.bmp',
		'image/tiff': '.tiff', 'image/heic': '.heic', 'image/heif': '.heif',
	}
	try:
		import uuid
		from post.media_utils import compress_image
		ext = _EXT_BY_MIME.get(mime, '.jpg')
		cover_file.seek(0)
		if mime != 'image/gif':                 # GIF animé conservé tel quel
			compressed = compress_image(cover_file)
			if compressed is not cover_file:
				cover_file, ext = compressed, '.webp'
		filename = f"cover_images/{uuid.uuid4().hex}{ext}"
		account = request.user
		if account.cover_image and account.cover_image.name:
			try:
				account.cover_image.delete(save=False)
			except Exception:
				pass
		account.cover_image.save(filename, cover_file, save=True)
		url = account.cover_image.url
		return JsonResponse({'ok': True, 'url': url})
	except Exception as e:
		logger.exception("update_cover_image FAILED: %s", e)
		return JsonResponse({'error': _("L'envoi de l'image a échoué.")}, status=500)


# ─────────────────────────────────────────────────────────────────────────────
# Vérification du numéro de téléphone, et connexion par numéro (code SMS ou WhatsApp)
# ─────────────────────────────────────────────────────────────────────────────

from django.views.decorators.http import require_POST
from django.utils import timezone
from datetime import timedelta
import secrets
from django.utils.translation import get_language
from account.sms import country_choices, format_phone_display, otp_channels
from account import otp as otp_codes


def _json_body(request):
	"""Corps JSON de la requête, ou {} s'il est absent/invalide.

	json.loads() sur un corps malformé levait une JSONDecodeError non
	interceptée : erreur 500 déclenchable par n'importe quel client.
	"""
	try:
		return json.loads(request.body or '{}') or {}
	except (ValueError, UnicodeDecodeError):
		return {}


@require_POST
def phone_send_otp(request):
	"""
	Envoie un code pour confirmer le numéro du compte connecté.
	POST /account/phone/envoyer-code/
	Body (JSON ou form) : { "phone": "+49 1512 3456789", "country": "DE", "channel": "sms" | "whatsapp" }
	(« country » : le pays choisi, pour un numéro écrit sans indicatif ; « channel » est facultatif :
	sans lui, le premier moyen proposé.)
	"""
	if not request.user.is_authenticated:
		return JsonResponse({'error': _('Connexion requise.')}, status=401)

	data = request.POST or _json_body(request)
	channel = otp_codes.pick_channel(data.get('channel', ''))
	phone_e164 = otp_codes.read_phone(data.get('phone', ''), data.get('country', ''))
	if not phone_e164:
		return JsonResponse({'error': _INVALID_PHONE}, status=400)
	# Un numéro déjà confirmé par un autre compte ne peut pas l'être une 2e fois : sinon, la
	# connexion par numéro ne saurait plus quel compte ouvrir.
	if Account.objects.filter(phone_number=phone_e164, phone_verified=True).exclude(pk=request.user.pk).exists():
		return JsonResponse({'error': _('Ce numéro est déjà lié à un autre compte.')}, status=400)
	refused = otp_codes.channel_refused(phone_e164, channel)
	if refused:
		return JsonResponse({'error': refused}, status=400)
	if otp_codes.too_many_sends(phone_e164):
		return JsonResponse({
			'error': _('Trop de tentatives. Attendez 1 heure avant de demander un nouveau code.')
		}, status=429)
	error = otp_codes.issue_code(request.user, phone_e164, 'verify', channel)
	if error:
		return JsonResponse({'error': error}, status=500)
	return JsonResponse({
		'ok': True,
		'phone': phone_e164,
		'phone_display': format_phone_display(phone_e164),
		'valid_minutes': PhoneVerification.OTP_VALID_MINUTES,
		'channel': channel,
	})


@require_POST
def phone_verify_otp(request):
	"""
	Vérifie le code saisi par l'utilisateur connecté, et confirme son numéro.
	POST /account/phone/verifier/
	Body (JSON ou form) : { "phone": "+491512345678", "country": "DE", "code": "123456" }
	"""
	if not request.user.is_authenticated:
		return JsonResponse({'error': _('Connexion requise.')}, status=401)

	data  = request.POST or _json_body(request)
	phone_e164 = otp_codes.read_phone(data.get('phone', ''), data.get('country', ''))
	if not phone_e164:
		return JsonResponse({'error': _('Numéro invalide.')}, status=400)
	otp, error = otp_codes.check_code(phone_e164, 'verify', data.get('code'), user=request.user)
	if error:
		return JsonResponse({'error': error}, status=400)

	Account.objects.filter(pk=request.user.pk).update(
		phone_number=phone_e164,
		phone_verified=True,
	)
	# Mettre à jour l'instance en mémoire (important pour la réponse de contexte)
	request.user.phone_number = phone_e164
	request.user.phone_verified = True

	return otp_codes.remember_country(JsonResponse({
		'ok': True,
		'phone_display': format_phone_display(phone_e164),
		'message': _('Numéro vérifié avec succès !'),
	}), phone_e164)


_INVALID_PHONE = gettext_lazy("Numéro invalide. Choisissez votre pays, ou écrivez le numéro avec l'indicatif "
                  "(+…). Il faut un numéro de mobile.")


# Ce qu'on répond quand un code est demandé, QUE LE NUMÉRO AIT UN COMPTE OU NON : sinon la
# page dirait à n'importe qui quels numéros sont inscrits sur Vazimba.
_CODE_SENT = gettext_lazy("Si ce numéro est lié à un compte Vazimba, un code vient d'y être envoyé.")
_CODE_SENT_EMAIL = gettext_lazy("Si ce numéro est lié à un compte Vazimba, un code vient d'être envoyé à l'adresse "
                    "e-mail de ce compte (regardez aussi dans les indésirables).")


def phone_login_view(request):
	"""Connexion avec son numéro de téléphone et un code reçu par SMS ou WhatsApp.

	1. GET : le formulaire du numéro (et le choix SMS / WhatsApp) ;
	2. POST step=numero : envoi du code (si un compte a ce numéro confirmé) ;
	3. POST step=code : vérification, puis connexion.
	Seuls les comptes dont le numéro a été confirmé peuvent se connecter ainsi.
	"""
	if request.user.is_authenticated:
		return redirect("post:index")
	channels = otp_codes.channels_for('login')
	context = {'channels': channels, 'step': 'numero', 'countries': country_choices(get_language() or 'fr'),
	           'country': otp_codes.guess_region(request)}
	if request.method == 'POST' and request.POST.get('step') == 'numero':
		channel = otp_codes.pick_channel(request.POST.get('channel', ''), 'login')
		country = request.POST.get('country', '')
		phone = otp_codes.read_phone(request.POST.get('phone', ''), country)
		context.update(channel=channel, phone_raw=request.POST.get('phone', ''), country=country or context['country'])
		refused = otp_codes.channel_refused(phone, channel) if phone else None
		if not phone:
			context['error'] = _INVALID_PHONE
		elif refused:
			context['error'] = refused
		elif otp_codes.too_many_sends(phone):
			context['error'] = _('Trop de codes demandés pour ce numéro. Réessayez dans une heure.')
		else:
			account = otp_codes.account_for_phone(phone)
			error = otp_codes.issue_code(account, phone, 'login', channel) if account else None
			if error:
				context['error'] = error
			else:
				request.session['phone_login'] = phone
				context.update(step='code', info=_CODE_SENT_EMAIL if channel == 'email' else _CODE_SENT,
				               phone_display=format_phone_display(phone))
	elif request.method == 'POST' and request.POST.get('step') == 'code':
		phone = request.session.get('phone_login')
		if not phone:
			context['error'] = _('Recommencez : indiquez votre numéro.')
		else:
			otp, error = otp_codes.check_code(phone, 'login', request.POST.get('code'))
			if error:
				context.update(step='code', error=error, phone_display=format_phone_display(phone))
			else:
				request.session.pop('phone_login', None)
				user = otp.user
				if not user.is_active:
					context['error'] = _('Ce compte est désactivé.')
				else:
					login(request, user, backend='account.backends.CaseInsensitiveModelBackend')
					destination = get_redirect_if_exists(request)
					return otp_codes.remember_country(redirect(destination or "post:index"), phone)
	return render(request, "account/phone_login.html", context)


# ── Blocage d'un utilisateur ────────────────────────────────────────────────
@require_POST
def toggle_block(request, user_id):
	"""POST /account/bloquer/<id>/ — bloque ou débloque, renvoie {ok, blocked}."""
	if not request.user.is_authenticated:
		return JsonResponse({'ok': False, 'error': 'auth'}, status=401)
	try:
		other = Account.objects.get(pk=user_id)
	except (Account.DoesNotExist, ValueError):
		return JsonResponse({'ok': False, 'error': 'introuvable'}, status=404)
	if other == request.user:
		return JsonResponse({'ok': False, 'error': 'self'}, status=400)
	existing = UserBlock.objects.filter(blocker=request.user, blocked=other)
	if existing.exists():
		existing.delete()
		return JsonResponse({'ok': True, 'blocked': False})
	UserBlock.objects.create(blocker=request.user, blocked=other)
	# Un bloqué n'est plus un ami ni un demandeur
	try:
		mine, _c = FriendList.objects.get_or_create(user=request.user)
		theirs, _c = FriendList.objects.get_or_create(user=other)
		mine.friends.remove(other); theirs.friends.remove(request.user)
		FriendRequest.objects.filter(
			models_Q(sender=request.user, receiver=other) | models_Q(sender=other, receiver=request.user),
			is_active=True,
		).update(is_active=False)
	except Exception:
		logger.exception("toggle_block: nettoyage amitié")
	return JsonResponse({'ok': True, 'blocked': True})


# ── Suppression du compte ───────────────────────────────────────────────────
DELETE_WORD = 'SUPPRIMER'   # mot à recopier, identique dans les trois langues


def delete_account_view(request):
	"""GET : page de confirmation. POST (mot de passe) : suppression définitive.

	URL publique exigée par Google Play pour la suppression de compte.
	Suppression en cascade ; si une contrainte protège des données (commandes
	Resto d'un restaurateur), le compte est anonymisé et désactivé à la place.
	"""
	if not request.user.is_authenticated:
		return redirect(f"{settings.LOGIN_URL}?next={request.path}")
	error = None
	# Compte sans mot de passe (créé depuis Pola, connexion par numéro) : il ne
	# pouvait jamais confirmer. Il recopie le mot SUPPRIMER à la place.
	has_password = request.user.has_usable_password()
	if request.method == 'POST':
		if has_password:
			confirmed = request.user.check_password(request.POST.get('password', ''))
			if not confirmed:
				error = 'wrong_password'
		else:
			confirmed = request.POST.get('confirm_word', '').strip().upper() == DELETE_WORD
			if not confirmed:
				error = 'wrong_word'
		if confirmed:
			user = request.user
			logout(request)
			try:
				user.delete()
			except Exception:
				logger.exception("delete_account: cascade impossible, anonymisation")
				uid = user.pk
				user.email = f'supprime-{uid}@vazimba.invalid'
				user.username = f'compte-supprime-{uid}'
				user.bio = ''; user.location = ''
				user.phone_number = ''; user.phone_verified = False
				user.is_active = False
				user.set_unusable_password()
				try:
					if user.profile_image and 'default' not in str(user.profile_image):
						user.profile_image.delete(save=False)
					if user.cover_image:
						user.cover_image.delete(save=False)
				except Exception:
					pass
				user.save()
			return render(request, 'account/delete_account_done.html')
	return render(request, 'account/delete_account.html', {
		'error': error, 'has_password': has_password, 'delete_word': DELETE_WORD,
	})
