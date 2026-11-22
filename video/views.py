import datetime

from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import ensure_csrf_cookie
from django.http import Http404, JsonResponse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.contrib import messages
from django.views.decorators.http import require_POST

from .models import LiveRoom

# Un live est « zombie » quand son hôte ne donne plus signe de vie :
#  - il a diffusé, mais plus aucun battement depuis STALE_LIVE_MINUTES ;
#  - ou la salle a été créée et jamais rejointe depuis STALE_UNSTARTED_HOURS.
# (L'ancien critère, « créé depuis plus de 3 h », coupait aussi les lives
# longs toujours en cours.)
STALE_LIVE_MINUTES = 10
STALE_UNSTARTED_HOURS = 3
CLEANUP_EVERY = 60   # secondes : le widget du fil interroge l'API toutes les 20 s


def _cleanup_stale_rooms(force=False):
    """Termine les lives abandonnés (au plus une fois par minute)."""
    from django.core.cache import cache
    from django.db.models import Q
    if not force and not cache.add('live:cleanup', 1, CLEANUP_EVERY):
        return
    now = timezone.now()
    LiveRoom.objects.filter(status=LiveRoom.STATUS_ACTIVE).filter(
        Q(last_seen__lt=now - datetime.timedelta(minutes=STALE_LIVE_MINUTES))
        | Q(last_seen__isnull=True, created_at__lt=now - datetime.timedelta(hours=STALE_UNSTARTED_HOURS))
    ).update(
        status=LiveRoom.STATUS_ENDED,
        ended_at=timezone.now(),
        viewer_count=0,
        host_channel='',
    )


@login_required(login_url='login')
@ensure_csrf_cookie
def live_list(request):
    """Page principale : liste des lives actifs + formulaire de création."""
    _cleanup_stale_rooms()
    active_rooms = (
        LiveRoom.objects
        .visible_to(request.user)
        .filter(status=LiveRoom.STATUS_ACTIVE)
        .select_related('host', 'group')
        .order_by('-created_at')
    )
    return render(request, 'video/live_list.html', {
        'active_rooms': active_rooms,
    })


@login_required(login_url='login')
@require_POST
def live_create(request):
    """Crée un nouveau live et redirige vers la salle."""
    title    = request.POST.get('title', '').strip()
    group_id = request.POST.get('group_id', None)

    if not title:
        title = _("Live de %(name)s") % {'name': request.user.username}

    group = None
    if group_id:
        try:
            from group.models import Group
            # On ne peut lancer un live que dans un groupe dont on est membre.
            group = Group.objects.get(pk=group_id, memberships__user=request.user)
        except Exception:
            pass

    room = LiveRoom.objects.create(
        host=request.user,
        title=title,
        group=group,
    )
    return redirect('video:live-room', room_id=room.pk)


@login_required(login_url='login')
def live_room(request, room_id):
    """La salle live (hôte ou spectateur)."""
    room = get_object_or_404(LiveRoom.objects.select_related('group'), pk=room_id)
    if not room.can_view(request.user):
        raise Http404

    if room.status == LiveRoom.STATUS_ENDED:
        messages.info(request, _("Ce live est terminé."))
        return redirect('video:live-list')

    is_host = (room.host == request.user)

    return render(request, 'video/live_room.html', {
        'room': room,
        'is_host': is_host,
    })


@login_required(login_url='login')
@require_POST
def live_end(request, room_id):
    """Termine un live (hôte uniquement).
    Supporte deux modes :
    - Formulaire classique → redirection vers la liste
    - navigator.sendBeacon (ping de fin) → réponse 204 No Content (pas de redirection)
    """
    room = get_object_or_404(LiveRoom, pk=room_id, host=request.user)
    room.status       = LiveRoom.STATUS_ENDED
    room.ended_at     = timezone.now()
    room.host_channel = ''
    room.viewer_count = 0
    room.save(update_fields=['status', 'ended_at', 'host_channel', 'viewer_count'])

    # sendBeacon envoie Content-Type multipart/form-data, n'attend pas de redirection
    is_beacon = (request.POST.get('_beacon') == '1' or
                 'multipart' in request.content_type or
                 request.headers.get('X-Requested-With') == 'beacon')
    if is_beacon or request.headers.get('Accept') == '*/*':
        return JsonResponse({'ok': True}, status=200)
    return redirect('video:live-list')


def live_api_active(request):
    """
    JSON : live rooms actives (pour le widget feed / header).
    Accessible sans authentification pour simplifier le polling client.
    """
    _cleanup_stale_rooms()
    rooms = (
        LiveRoom.objects
        .visible_to(request.user)
        .filter(status=LiveRoom.STATUS_ACTIVE)
        .select_related('host', 'group')
        .order_by('-created_at')[:10]
    )
    data = []
    for r in rooms:
        try:
            avatar = r.host.profile_image.url
        except Exception:
            avatar = ''
        data.append({
            'id':           r.pk,
            'title':        r.title,
            'host':         r.host.username,
            'host_avatar':  avatar,
            'viewer_count': r.viewer_count,
            'group':        r.group.name if r.group else None,
            'url':          reverse('video:live-room', args=[r.pk]),
        })
    return JsonResponse({'lives': data})
