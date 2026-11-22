"""Corrections de l'audit 2026-11 (stories) : lien assaini, blocages, stories expirées."""
from datetime import timedelta

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from account.models import Account, UserBlock
from stories.models import Story, StoryReaction, StoryReply
from stories.views import _clean_story_link


class StoryCorrectionsTests(TestCase):
    def setUp(self):
        cache.clear()
        self.me = Account.objects.create_user(email='moi@test.mg', username='moi', password='pw12345678')
        self.other = Account.objects.create_user(email='lui@test.mg', username='lui', password='pw12345678')
        self.client.force_login(self.me)

    def _story(self, user, **kw):
        return Story.objects.create(user=user, story_type='text', caption='Salama', **kw)

    def test_link_must_be_http_or_internal(self):
        self.assertEqual(_clean_story_link('javascript:alert(1)'), '')
        self.assertEqual(_clean_story_link('data:text/html,x'), '')
        self.assertEqual(_clean_story_link('//evil.example/x'), '')
        self.assertEqual(_clean_story_link('https://exemple.org/a'), 'https://exemple.org/a')
        self.assertEqual(_clean_story_link('/bazar/12/'), '/bazar/12/')
        r = self.client.post(reverse('stories:create'), {'story_type': 'text', 'caption': 'x', 'link': 'javascript:alert(1)'})
        self.assertEqual(r.json()['story']['link'], '')

    def test_old_unsafe_link_is_not_rendered(self):
        self._story(self.other, link='javascript:alert(1)')
        self.assertNotIn('javascript:alert', self.client.get(reverse('stories:page')).content.decode())
        groups = self.client.get(reverse('stories:feed')).json()['groups']
        self.assertEqual(groups[0]['stories'][0]['link'], '')

    def test_blocked_accounts_are_hidden_both_ways(self):
        story = self._story(self.other)
        UserBlock.objects.create(blocker=self.other, blocked=self.me)
        self.assertEqual(self.client.get(reverse('stories:feed')).json()['groups'], [])
        self.assertNotIn('openViewer(%d' % story.pk, self.client.get(reverse('stories:page')).content.decode())
        self.assertEqual(self.client.get(reverse('stories:profile', args=[self.other.pk])).json()['stories'], [])
        self.assertEqual(self.client.post(reverse('stories:reply', args=[story.pk]), {'message': 'coucou'}).status_code, 404)
        self.assertEqual(self.client.post(reverse('stories:react', args=[story.pk]), {'emoji': '🔥'}).status_code, 404)
        self.assertFalse(StoryReply.objects.exists() or StoryReaction.objects.exists())

    def test_expired_story_cannot_be_answered(self):
        story = self._story(self.other)
        Story.objects.filter(pk=story.pk).update(expires_at=timezone.now() - timedelta(minutes=1))
        self.assertEqual(self.client.post(reverse('stories:reply', args=[story.pk]), {'message': 'coucou'}).status_code, 404)
        self.assertEqual(self.client.post(reverse('stories:react', args=[story.pk]), {'emoji': '🔥'}).status_code, 404)

    def test_active_story_still_works(self):
        story = self._story(self.other)
        self.assertTrue(self.client.post(reverse('stories:reply', args=[story.pk]), {'message': 'coucou'}).json()['ok'])
        self.assertTrue(self.client.post(reverse('stories:react', args=[story.pk]), {'emoji': '🔥'}).json()['ok'])
        self.assertEqual(self.client.get(reverse('stories:page')).status_code, 200)
