"""Lives : ménage des salles abandonnées et pages (audit 2026-11)."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import LiveRoom
from .views import _cleanup_stale_rooms

User = get_user_model()


class LiveCleanupTests(TestCase):
    def setUp(self):
        cache.clear()
        self.host = User.objects.create_user(email='h@test.mg', username='hote', password='x')
        self.client.force_login(self.host)

    def _room(self, created_ago, last_seen_ago=None):
        room = LiveRoom.objects.create(host=self.host, title='Match')
        now = timezone.now()
        LiveRoom.objects.filter(pk=room.pk).update(
            created_at=now - created_ago,
            last_seen=(now - last_seen_ago) if last_seen_ago is not None else None)
        return room

    def test_long_running_live_is_kept(self):
        room = self._room(timedelta(hours=5), last_seen_ago=timedelta(seconds=30))
        _cleanup_stale_rooms(force=True)
        room.refresh_from_db()
        self.assertEqual(room.status, LiveRoom.STATUS_ACTIVE)

    def test_silent_or_never_started_lives_are_closed(self):
        silent = self._room(timedelta(minutes=40), last_seen_ago=timedelta(minutes=20))
        ghost = self._room(timedelta(hours=4))
        fresh = self._room(timedelta(minutes=5))
        _cleanup_stale_rooms(force=True)
        for room, expected in ((silent, LiveRoom.STATUS_ENDED), (ghost, LiveRoom.STATUS_ENDED), (fresh, LiveRoom.STATUS_ACTIVE)):
            room.refresh_from_db()
            self.assertEqual(room.status, expected)

    def test_cleanup_is_throttled(self):
        _cleanup_stale_rooms()                      # pose le verrou d'une minute
        ghost = self._room(timedelta(hours=4))
        _cleanup_stale_rooms()
        ghost.refresh_from_db()
        self.assertEqual(ghost.status, LiveRoom.STATUS_ACTIVE)

    def test_pages(self):
        r = self.client.get(reverse('video:live-list'))
        self.assertEqual(r.status_code, 200)
        self.assertNotIn('setTimeout(function() { location.reload(); }', r.content.decode())
        self.assertIn('id="live-create-form" method="post"', r.content.decode())
        r = self.client.post(reverse('video:live-create'), {'title': ''})
        room = LiveRoom.objects.get()
        self.assertRedirects(r, reverse('video:live-room', args=[room.pk]), fetch_redirect_response=False)
        self.assertEqual(self.client.get(reverse('video:live-room', args=[room.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse('video:live-api-active')).json()['lives'][0]['url'],
                         reverse('video:live-room', args=[room.pk]))
