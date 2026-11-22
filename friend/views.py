from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
import json

from django.http import Http404
from django.utils.translation import gettext as _

from account.models import Account
from friend.models import FriendRequest, FriendList


def _json(payload, status=200):
	return JsonResponse(payload, status=status)


@login_required(login_url='login')
@require_POST
def send_friend_request(request, *args, **kwargs):
	user = request.user
	user_id = request.POST.get("receiver_user_id")
	if not user_id:
		return _json({'response': _("Impossible d’envoyer la demande d’ami.")}, status=400)

	try:
		receiver = Account.objects.get(pk=user_id)
	except (Account.DoesNotExist, ValueError):
		# Un identifiant inconnu ou non numérique levait une exception
		# non interceptée → erreur 500.
		return _json({'response': _("Ce membre est introuvable.")}, status=404)
	if not receiver.visible_to(user):
		return _json({'response': _("Ce membre est introuvable.")}, status=404)

	if receiver == user:
		return _json({'response': _("Vous ne pouvez pas vous envoyer une demande d’ami.")}, status=400)

	from account.models import UserBlock
	if UserBlock.is_blocked_between(user, receiver):
		return _json({'response': _("Cette action n’est pas disponible.")}, status=403)

	already_sent = FriendRequest.objects.filter(
		sender=user, receiver=receiver, is_active=True
	).exists()
	if already_sent:
		return _json({'response': _("Vous avez déjà envoyé une demande d’ami à cette personne.")})

	FriendRequest.objects.create(sender=user, receiver=receiver)
	return _json({'response': "Friend request sent."})


@login_required(login_url='login')
def friend_requests(request, *args, **kwargs):
	user = request.user
	user_id = kwargs.get("user_id")
	try:
		account = Account.objects.get(pk=user_id)
	except (Account.DoesNotExist, ValueError):
		raise Http404("Membre introuvable.")

	if account != user:
		# Les demandes d'ami d'un autre membre : on renvoie vers les siennes.
		return redirect('friend:friend-requests', user_id=user.pk)

	return render(request, "friend/friend_requests.html", {
		'friend_requests': FriendRequest.objects.filter(receiver=account, is_active=True).select_related('sender'),
	})


@login_required(login_url='login')
@require_POST
def accept_friend_request(request, *args, **kwargs):
	"""Accepte une demande d'ami.

	POST obligatoire : la vue répondait auparavant au GET, si bien qu'un
	simple <img src="/friend/friend_request_accept/12/"> sur un site tiers
	faisait accepter la demande à l'insu de l'utilisateur (le middleware CSRF
	ne contrôle pas les requêtes GET).
	"""
	friend_request_id = kwargs.get("friend_request_id")
	try:
		friend_request = FriendRequest.objects.get(pk=friend_request_id)
	except (FriendRequest.DoesNotExist, ValueError):
		return _json({'response': _("Cette demande d’ami est introuvable.")}, status=404)

	if friend_request.receiver != request.user:
		return _json({'response': _("Cette demande ne vous est pas adressée.")}, status=403)
	# Une demande annulée, refusée ou désactivée par un blocage ne peut plus
	# être acceptée : sans ce contrôle, elle créait quand même l'amitié.
	if not friend_request.is_active:
		return _json({'response': _("Cette demande d’ami n’est plus en attente.")}, status=409)
	from account.models import UserBlock
	if UserBlock.is_blocked_between(request.user, friend_request.sender):
		return _json({'response': _("Cette action n’est pas disponible.")}, status=403)

	friend_request.accept()
	return _json({'response': "Friend request accepted."})


@login_required(login_url='login')
@require_POST
def remove_friend(request, *args, **kwargs):
	user_id = request.POST.get("receiver_user_id")
	if not user_id:
		return _json({'response': _("Impossible de retirer cet ami.")}, status=400)

	try:
		removee = Account.objects.get(pk=user_id)
	except (Account.DoesNotExist, ValueError):
		return _json({'response': _("Ce membre est introuvable.")}, status=404)

	friend_list, _created = FriendList.objects.get_or_create(user=request.user)
	# Pas amis : rien à retirer (et surtout aucune notification envoyée à un inconnu).
	if not friend_list.is_mutual_friend(removee):
		return _json({'response': _("Ce membre ne fait pas partie de vos amis.")}, status=400)
	friend_list.unfriend(removee)
	return _json({'response': "Successfully removed that friend."})


@login_required(login_url='login')
@require_POST
def decline_friend_request(request, *args, **kwargs):
	"""Refuse une demande d'ami. POST obligatoire (voir accept_friend_request)."""
	friend_request_id = kwargs.get("friend_request_id")
	try:
		friend_request = FriendRequest.objects.get(pk=friend_request_id)
	except (FriendRequest.DoesNotExist, ValueError):
		return _json({'response': _("Cette demande d’ami est introuvable.")}, status=404)

	if friend_request.receiver != request.user:
		return _json({'response': _("Cette demande ne vous est pas adressée.")}, status=403)
	if not friend_request.is_active:
		return _json({'response': _("Cette demande d’ami n’est plus en attente.")}, status=409)

	friend_request.decline()
	return _json({'response': "Friend request declined."})


@login_required(login_url='login')
@require_POST
def cancel_friend_request(request, *args, **kwargs):
	user_id = request.POST.get("receiver_user_id")
	if not user_id:
		return _json({'response': _("Impossible d’annuler cette demande.")}, status=400)

	try:
		receiver = Account.objects.get(pk=user_id)
	except (Account.DoesNotExist, ValueError):
		return _json({'response': _("Ce membre est introuvable.")}, status=404)

	friend_requests_qs = FriendRequest.objects.filter(
		sender=request.user, receiver=receiver, is_active=True
	)
	# `.first().cancel()` levait une AttributeError (None) quand il n'y avait
	# aucune demande active — erreur 500 au lieu d'un message clair.
	if not friend_requests_qs.exists():
		return _json({'response': _("Aucune demande en attente à annuler.")}, status=404)

	# Il ne devrait y avoir qu'une seule demande active ; on les annule toutes.
	for friend_req in friend_requests_qs:
		friend_req.cancel()
	return _json({'response': "Friend request canceled."})


@login_required(login_url='login')
def friends_list_view(request, *args, **kwargs):
	user = request.user
	user_id = kwargs.get("user_id")

	try:
		this_user = Account.objects.get(pk=user_id)
	except (Account.DoesNotExist, ValueError):
		raise Http404("Membre introuvable.")
	if not this_user.visible_to(user):
		raise Http404("Membre introuvable.")

	friend_list, _created = FriendList.objects.get_or_create(user=this_user)

	# Il faut être ami pour voir la liste d'amis de quelqu'un : sinon, retour à son profil.
	if user != this_user and not friend_list.friends.filter(pk=user.pk).exists():
		from django.contrib import messages
		messages.info(request, _("Seuls ses amis peuvent voir la liste d’amis de ce membre."))
		return redirect('account:view', user_id=this_user.pk)

	auth_user_friend_list, _created = FriendList.objects.get_or_create(user=user)
	# Amis communs en un seul ensemble d'ids (plus une requête par ami)
	my_friend_ids = set(auth_user_friend_list.friends.values_list('id', flat=True))
	friends = [
		(friend, friend.id in my_friend_ids)
		for friend in friend_list.friends.all()
	]

	return render(request, "friend/friend_list.html", {
		'this_user': this_user,
		'is_own_list': user == this_user,
		'friends':   friends,
	})
