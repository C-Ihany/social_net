"""
Corrections de l'audit 2026-11 (fil) : brouillons publiables, capsules Vintana
réellement scellées, tendances sans fuite, carte de post commune.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from account.models import UserBlock
from group.models import Group, GroupMembership
from .models import Post, Repost
from .views import get_trending_hashtags

User = get_user_model()

STATIC = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}
SECRET = 'motsecretdelacapsule'


@override_settings(STORAGES=STATIC)
class Base(TestCase):
    def setUp(self):
        cache.clear()
        self.me = User.objects.create_user(email='me@test.mg', username='me', password='x')
        self.other = User.objects.create_user(email='o@test.mg', username='other', password='x')
        self.client.force_login(self.me)


class DraftTests(Base):
    def test_publish_now_keeps_body_and_publishes(self):
        post = Post.objects.create(author=self.me, title='Brouillon', body='<p>corps</p>', status='draft')
        r = self.client.post(reverse('post:publish-draft', args=[post.pk]))
        self.assertRedirects(r, reverse('post:post-detail', args=[post.pk]), fetch_redirect_response=False)
        post.refresh_from_db()
        self.assertEqual(post.status, 'published')
        self.assertEqual(post.body, '<p>corps</p>')

    def test_publish_is_owner_only_and_post_only(self):
        post = Post.objects.create(author=self.other, title='x', body='y', status='draft')
        self.assertEqual(self.client.post(reverse('post:publish-draft', args=[post.pk])).status_code, 404)
        mine = Post.objects.create(author=self.me, title='x', body='y', status='draft')
        self.assertEqual(self.client.get(reverse('post:publish-draft', args=[mine.pk])).status_code, 405)
        post.refresh_from_db()
        self.assertEqual(post.status, 'draft')

    def test_edit_form_can_publish_a_draft(self):
        post = Post.objects.create(author=self.me, title='B', body='corps', status='draft')
        self.client.post(reverse('post:edit-post', args=[post.pk]), {'title': 'B', 'body': 'corps'})
        post.refresh_from_db()
        self.assertEqual(post.status, 'draft')
        self.client.post(reverse('post:edit-post', args=[post.pk]), {'title': 'B', 'body': 'corps', 'action': 'publish'})
        post.refresh_from_db()
        self.assertEqual(post.status, 'published')

    def test_drafts_page_and_delete_now(self):
        post = Post.objects.create(author=self.me, title='B', body='corps', status='draft')
        html = self.client.get(reverse('post:mes-brouillons')).content.decode()
        self.assertIn(reverse('post:publish-draft', args=[post.pk]), html)
        self.assertNotIn('name="action" value="publish"', html)
        r = self.client.post(reverse('post:delete-post-now', args=[post.pk]))
        self.assertEqual(r.status_code, 302)
        self.assertFalse(Post.objects.filter(pk=post.pk).exists())
        theirs = Post.objects.create(author=self.other, title='x', body='y')
        self.assertEqual(self.client.post(reverse('post:delete-post-now', args=[theirs.pk])).status_code, 404)

    def test_add_post_ajax_returns_redirect(self):
        r = self.client.post(reverse('post:addPost'), {'title': 'T', 'body': 'b', 'ajax': '1', 'action': 'draft'})
        self.assertEqual(r.json()['redirect'], reverse('post:mes-brouillons'))


class VintanaSealTests(Base):
    def _capsule(self, **kw):
        data = dict(author=self.other, title='Pour plus tard', post_type=Post.VINTANA,
                    body='<div class="vintana-body"><p>%s #scelle</p></div>' % SECRET,
                    reveal_date=timezone.now() + timedelta(days=30))
        data.update(kw)
        return Post.objects.create(**data)

    def test_detail_page_does_not_reveal(self):
        post = self._capsule()
        r = self.client.get(reverse('post:post-detail', args=[post.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertNotIn(SECRET, r.content.decode())
        self.assertIn('pc-vintana-locked', r.content.decode())
        # … même pour son auteur
        self.client.force_login(self.other)
        self.assertNotIn(SECRET, self.client.get(reverse('post:post-detail', args=[post.pk])).content.decode())

    def test_revealed_capsule_is_readable(self):
        post = self._capsule(reveal_date=timezone.now() - timedelta(minutes=1))
        self.assertIn(SECRET, self.client.get(reverse('post:post-detail', args=[post.pk])).content.decode())

    def test_hashtag_search_and_trends_skip_sealed(self):
        self._capsule()
        self.assertNotIn(SECRET, self.client.get(reverse('post:hashtag', args=['scelle'])).content.decode())
        r = self.client.get(reverse('recherche'), {'q': SECRET})
        self.assertNotIn('Pour plus tard', r.content.decode())
        tags = get_trending_hashtags(limit=25, hours=24, with_preview=True)
        self.assertFalse([t for t in tags if t['slug'] == 'scelle'])

    def test_default_title_is_neutral(self):
        when = (timezone.localtime() + timedelta(days=3)).strftime('%Y-%m-%dT%H:%M')
        r = self.client.post(reverse('post:vintana-create'), {'message': SECRET + ' <b>x</b>', 'reveal_date': when},
                             HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertTrue(r.json()['ok'])
        post = Post.objects.get(author=self.me, post_type=Post.VINTANA)
        self.assertNotIn(SECRET, post.title)
        self.assertIn('&lt;b&gt;', post.body)        # saisie échappée


class TrendsLeakTests(Base):
    def test_drafts_and_private_groups_are_not_trending(self):
        Post.objects.create(author=self.other, title='t', body='brouillon #fuitebrouillon', status='draft')
        g = Group.objects.create(name='Privé', creator=self.other, privacy=Group.PRIVATE)
        GroupMembership.objects.create(user=self.other, group=g, role=GroupMembership.ADMIN)
        Post.objects.create(author=self.other, title='t', body='secret #fuitegroupe', group=g)
        Post.objects.create(author=self.other, title='t', body='public #visible')
        slugs = {t['slug'] for t in get_trending_hashtags(limit=25, hours=24, with_preview=True)}
        self.assertIn('visible', slugs)
        self.assertNotIn('fuitebrouillon', slugs)
        self.assertNotIn('fuitegroupe', slugs)
        self.assertEqual(self.client.get(reverse('post:tendances')).status_code, 200)


class SharedCardTests(Base):
    def setUp(self):
        super().setUp()
        self.post = Post.objects.create(author=self.other, title='Bonjour', body='<p>texte #salut</p>')

    def test_detail_and_hashtag_use_the_shared_card(self):
        for url in (reverse('post:post-detail', args=[self.post.pk]), reverse('post:hashtag', args=['salut'])):
            html = self.client.get(url).content.decode()
            self.assertIn('id="post-%d"' % self.post.pk, html)
            self.assertIn('window.VZ_CARD', html)
            self.assertIn('vzPostMenu(this)', html)
            self.assertNotIn('/view/', html)                 # ancienne adresse de profil inexistante
            self.assertNotIn('reaction_type', html)          # mauvais nom de paramètre
            self.assertNotIn('SOCIAL NET', html)

    def test_reaction_parameter_and_toggle(self):
        url = reverse('post:react-post')
        r = self.client.post(url, {'post_id': self.post.pk, 'reaction': 'heart'})
        self.assertEqual(r.json()['user_reaction'], 'heart')
        r = self.client.post(url, {'post_id': self.post.pk, 'reaction': 'heart'})
        self.assertIsNone(r.json()['user_reaction'])
        self.assertEqual(self.client.post(url, {'post_id': 'abc', 'reaction': 'like'}).status_code, 404)

    def test_feed_knows_my_reposts(self):
        from friend.models import FriendList
        fl, _c = FriendList.objects.get_or_create(user=self.me)
        fl.friends.add(self.other)
        Repost.objects.create(user=self.me, post=self.post)
        html = self.client.get(reverse('post:post-view') + '?tab=feed').content.decode()
        self.assertIn('data-reposted="1"', html)
        self.assertNotIn('>groupe<', html)
        self.assertNotIn('href="#"', html.split('rsb-footer-links')[1].split('</div>')[0])

    def test_card_script_is_centralised(self):
        from pathlib import Path
        from django.conf import settings
        js = (Path(settings.BASE_DIR) / 'static' / 'js' / 'vz-post-card.js').read_text()
        for name in ('window.sendReaction', 'window.submitComment', 'window.submitReply',
                     'window.deleteComment', 'window.vzPostDelete', 'reaction: reactionType'):
            self.assertIn(name, js)
        html = self.client.get(reverse('post:post-view') + '?tab=feed').content.decode()
        self.assertNotIn('function sendReaction', html)
        self.assertNotIn('rwOpen', html)

    def test_mentions_hide_blocked_and_inactive(self):
        User.objects.create_user(email='z1@test.mg', username='zed_ok', password='x')
        blocked = User.objects.create_user(email='z2@test.mg', username='zed_bloque', password='x')
        off = User.objects.create_user(email='z3@test.mg', username='zed_off', password='x')
        off.is_active = False
        off.save(update_fields=['is_active'])
        UserBlock.objects.create(blocker=self.me, blocked=blocked)
        names = {u['username'] for u in self.client.get(reverse('post:mention-autocomplete'), {'q': 'zed'}).json()['users']}
        self.assertEqual(names, {'zed_ok'})

    def test_product_picker_has_no_broken_onclick(self):
        html = self.client.get(reverse('post:addPost')).content.decode()
        self.assertNotIn('JSON.stringify(p.ref)', html)
        self.assertIn("item.getAttribute('data-ref')", html)


class PagesRenderTests(Base):
    def test_pages_render(self):
        Post.objects.create(author=self.me, title='B', body='corps', status='draft')
        mine = Post.objects.create(author=self.me, title='À moi', body='x')
        names = ['post:mes-brouillons', 'post:mes-favoris-posts', 'post:tendances', 'post:addPost',
                 'post:kabary-create', 'post:vintana-create', 'post:video-feed', 'post:index', 'recherche']
        for name in names:
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)
        self.assertEqual(self.client.get(reverse('recherche'), {'q': 'moi'}).status_code, 200)
        self.assertEqual(self.client.get(reverse('post:edit-post', args=[mine.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse('post:delete-post', args=[mine.pk])).status_code, 200)
