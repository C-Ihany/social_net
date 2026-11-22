"""Corrections de l'audit 2026-11 (groupes)."""
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta

from post.models import Post
from .models import Group, GroupEvent, GroupMembership

User = get_user_model()
STATIC = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}


@override_settings(STORAGES=STATIC)
class GroupCorrectionsTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = User.objects.create_user(email='a@test.mg', username='admin_g', password='x')
        self.out = User.objects.create_user(email='o@test.mg', username="o'brien", password='x')
        self.group = Group.objects.create(name="L'atelier", creator=self.admin, privacy=Group.PRIVATE)
        GroupMembership.objects.create(user=self.admin, group=self.group, role=GroupMembership.ADMIN)
        self.event = GroupEvent.objects.create(group=self.group, organizer=self.admin, title='Fête',
                                               event_date=timezone.now() + timedelta(days=2))

    def test_event_attend_requires_membership_and_post(self):
        url = reverse('group:event-attend', args=[self.group.slug, self.event.pk])
        self.client.force_login(self.out)
        self.assertEqual(self.client.post(url).status_code, 403)
        self.assertEqual(self.event.attendees.count(), 0)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertTrue(self.client.post(url).json()['attending'])

    def test_invite_search_ignores_email(self):
        self.client.force_login(self.admin)
        url = reverse('group:invite-search', args=[self.group.slug])
        self.assertEqual(self.client.get(url, {'q': 'o@test'}).json()['users'], [])
        self.assertEqual(len(self.client.get(url, {'q': 'brien'}).json()['users']), 1)

    def test_detail_renders_with_pager_and_shared_card(self):
        for i in range(12):
            Post.objects.create(author=self.admin, title='p%d' % i, body='b', group=self.group)
        self.client.force_login(self.admin)
        r = self.client.get(reverse('group:detail', args=[self.group.slug]))
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertIn('vz-pager', html)
        self.assertIn('?page=2', html)
        self.assertIn('window.VZ_CARD', html)
        self.assertIn('data-pin-url=', html)            # épingler depuis le menu ⋯ (tactile compris)
        self.assertNotIn('reaction_type', html)
        self.assertIn('value="Live dans L&#x27;atelier"', html)   # plus d'escapejs dans un attribut HTML
        self.assertNotIn('/view/', html)
        self.assertEqual(self.client.get(reverse('group:detail', args=[self.group.slug]) + '?page=2').status_code, 200)

    def test_other_pages_render(self):
        self.client.force_login(self.admin)
        for url in (reverse('group:list'), reverse('group:create'), reverse('group:edit', args=[self.group.slug]),
                    reverse('group:delete', args=[self.group.slug]), reverse('group:list') + '?tab=mine'):
            self.assertEqual(self.client.get(url).status_code, 200, url)
        self.client.force_login(self.out)
        r = self.client.get(reverse('group:detail', args=[self.group.slug]))
        self.assertTemplateUsed(r, 'group/group_private.html')
        r = self.client.post(reverse('group:join', args=[self.group.slug]), follow=True)
        self.assertEqual(r.status_code, 200)

    def test_charter_tab_and_route_are_gone(self):
        from django.urls import NoReverseMatch
        self.client.force_login(self.admin)
        html = self.client.get(reverse('group:detail', args=[self.group.slug])).content.decode()
        self.assertNotIn('Dina', html)
        self.assertNotIn('gd-tab-dina', html)
        self.assertNotIn('Dina', self.client.get(reverse('group:edit', args=[self.group.slug])).content.decode())
        with self.assertRaises(NoReverseMatch):
            reverse('group:dina-save', args=[self.group.slug])

    def test_local_tab_uses_origin_country_for_diaspora(self):
        self.out.region, self.out.origin_country = 'diaspora', 'sn'
        self.out.save(update_fields=['region', 'origin_country'])
        Group.objects.create(name='Dakar ensemble', creator=self.admin, region='sn')
        Group.objects.create(name='Nairobi ensemble', creator=self.admin, region='ke')
        self.client.force_login(self.out)
        html = self.client.get(reverse('group:list') + '?tab=local').content.decode()
        self.assertIn('Dakar ensemble', html)
        self.assertNotIn('Nairobi ensemble', html)
