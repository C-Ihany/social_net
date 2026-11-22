from django.db import models
from django.utils.translation import gettext as _
from functools import cached_property
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager
from django.core.files.storage import FileSystemStorage
from django.db.models.fields.files import ImageFieldFile, ImageField
from django.conf import settings
import os
from django.db.models.signals import post_save
from django.dispatch import receiver
import uuid

from friend.models import FriendList
from django.contrib.auth import get_user_model


class ProfileImageFieldFile(ImageFieldFile):
    """ImageFieldFile qui retourne l'image statique par défaut si aucune photo n'est définie."""
    @property
    def url(self):
        from django.templatetags.static import static
        _default = static('images/profile_pic.png')
        name = str(self.name) if self.name else ''
        if not name or name == 'images/profile_pic.png':
            return _default
        try:
            from django.core.files.storage import FileSystemStorage
            # FileSystemStorage ne lève pas d'exception pour les fichiers manquants.
            # On vérifie l'existence physique pour éviter les 404.
            if isinstance(self.storage, FileSystemStorage):
                import os
                try:
                    full_path = self.storage.path(name)
                    if not os.path.exists(full_path):
                        return _default
                except Exception:
                    return _default
            return super().url
        except Exception:
            return _default


class ProfileImageField(ImageField):
    attr_class = ProfileImageFieldFile


class MyAccountManager(BaseUserManager):
	def create_user(self, email, username, password=None):
		if not email:
			raise ValueError('Users must have an email address')
		if not username:
			raise ValueError('Users must have a username')

		user = self.model(
			email=self.normalize_email(email),
			username=username,
		)

		user.set_password(password)
		user.save(using=self._db)
		return user

	def create_superuser(self, email, username, password):
		user = self.create_user(
			email=self.normalize_email(email),
			password=password,
			username=username,
		)
		user.is_admin = True
		user.is_staff = True
		user.is_superuser = True
		user.save(using=self._db)
		return user


def get_profile_image_filepath(self, filename):
	return f'profile_images/' + str(self.pk) + '/profile_image.png'

def get_default_profile_image():
	return "images/profile_pic.png"


class Account(AbstractBaseUser):
	email 					= models.EmailField(verbose_name="email", max_length=60, unique=True)
	username 				= models.CharField(max_length=30, unique=True)
	date_joined				= models.DateTimeField(verbose_name='date joined', auto_now_add=True)
	# Renseigné par django.contrib.auth au moment du login (signal user_logged_in).
	# NE PAS remettre auto_now=True : le champ serait réécrit à chaque save().
	last_login				= models.DateTimeField(verbose_name='last login', blank=True, null=True)
	is_admin				= models.BooleanField(default=False)
	is_active				= models.BooleanField(default=True)
	is_staff				= models.BooleanField(default=False)
	is_superuser			= models.BooleanField(default=False)
	profile_image			= ProfileImageField(max_length=255, upload_to=get_profile_image_filepath, null=True, blank=True, default=get_default_profile_image)
	hide_email				= models.BooleanField(default=True)
	cover_image				= models.ImageField(
		upload_to='cover_images/',
		null=True, blank=True,
	)
# From Tomi -----------------------------------------------
	bio = models.TextField(blank=True)
	location = models.CharField(max_length=100, blank=True)
	region = models.CharField(
		max_length=30, blank=True, default='',
		verbose_name='Pays de résidence',
		help_text='Où vit le membre : pays d\'Afrique, région, ou diaspora (pour le filtre "Près de chez moi")',
		db_index=True,
	)
	# Pays d'origine : distinct de `region` (où l'on vit). Un membre né au Sénégal
	# qui vit en Europe a region='diaspora' et origin_country='sn' : il retrouve
	# la communauté de son pays d'origine.
	origin_country = models.CharField(
		max_length=2, blank=True, default='',
		verbose_name="Pays d'origine", db_index=True,
	)
	cgu_accepted_at = models.DateTimeField(
		null=True, blank=True,
		verbose_name="CGU & confidentialité acceptées le"
	)
# ── Téléphone ─────────────────────────────────────────────
	phone_number = models.CharField(
		max_length=20, blank=True, default='',
		verbose_name='Numéro de téléphone',
		help_text='Format international E.164 : +indicatif du pays, puis le numéro',
		db_index=True,
	)
	phone_verified = models.BooleanField(
		default=False,
		verbose_name='Téléphone vérifié',
		help_text='Le numéro a été confirmé par SMS.',
	)
# ── Messagerie de Pola (l'assistant de bureau) ─────────────
	# Un utilisateur de Pola choisit, dans Pola, d'être :
	#  « pola »      : Pola seulement — INVISIBLE sur le réseau social (ni profil public, ni
	#                  recherche, ni suggestions) ; seuls les utilisateurs de Pola qui ont son
	#                  numéro peuvent lui écrire ;
	#  « community » : Pola + communauté Vazimba — un membre comme les autres ;
	#  ''            : pas un utilisateur de la messagerie de Pola.
	POLA_ONLY, POLA_COMMUNITY = 'pola', 'community'
	pola_mode = models.CharField(
		max_length=10, blank=True, default='', db_index=True,
		choices=[('', '—'), ('pola', 'Pola seulement (invisible sur Vazimba)'),
		         ('community', 'Pola + communauté Vazimba')],
		verbose_name='Messagerie de Pola',
	)
# ---------------------------------------------------------
	USERNAME_FIELD = 'email'
	REQUIRED_FIELDS = ['username']

	objects = MyAccountManager()

	@property
	def hidden(self):
		"""Vrai pour un compte « Pola seulement » : il n'apparaît nulle part sur le réseau social."""
		return self.pola_mode == self.POLA_ONLY

	def visible_to(self, viewer):
		"""Ce compte peut-il être vu par `viewer` (profil, stories, demande d'ami, nouvelle
		conversation) ? Toujours, sauf un compte « Pola seulement » : seulement lui-même et ceux
		avec qui il a déjà une conversation (ouverte depuis Pola, par son numéro)."""
		if not self.hidden:
			return True
		if viewer is None or not getattr(viewer, 'is_authenticated', False):
			return False
		if viewer.pk == self.pk:
			return True
		from chat.models import PrivateChatRoom
		return PrivateChatRoom.objects.filter(
			models.Q(user1=self, user2_id=viewer.pk) | models.Q(user2=self, user1_id=viewer.pk)).exists()

	def __str__(self):
		return self.username

	def get_profile_image_filename(self):
		from pathlib import PurePosixPath
		image_path = str(self.profile_image)
		prefix = f'profile_images/{self.pk}/'
		try:
			idx = image_path.index(prefix)
			return image_path[idx:]
		except ValueError:
			return image_path

	def has_perm(self, perm, obj=None):
		return self.is_admin

	def has_module_perms(self, app_label):
		# Retournait True pour TOUT compte : un utilisateur passé is_staff
		# voyait alors l'ensemble des applications dans l'admin Django.
		# On aligne sur has_perm().
		return self.is_admin

	@cached_property
	def score_fihavanana(self):
		"""Score de solidarité communautaire.
		Calculé en une passe SQL par instance — mis en cache pour la durée de la requête
		(cached_property évite de recalculer si le template l'appelle plusieurs fois).
		"""
		try:
			from post.models import Post, Comment, Reaction, Repost
			from friend.models import FriendList

			# Posts publiés : +5 chacun, quel que soit leur type
			post_score = Post.objects.filter(author=self).count() * 5

			# Commentaires (+2), réactions reçues (+3) — 2 COUNT SQL
			comment_score  = Comment.objects.filter(author=self).count() * 2
			reaction_score = Reaction.objects.filter(post__author=self).count() * 3

			# Reposts (+4)
			try:
				repost_score = Repost.objects.filter(post__author=self).count() * 4
			except Exception:
				repost_score = 0

			# Amis (+3)
			try:
				fl = FriendList.objects.get(user=self)
				friend_score = fl.friends.count() * 3
			except Exception:
				friend_score = 0

			# Groupes (+2)
			try:
				from group.models import GroupMembership
				group_score = GroupMembership.objects.filter(user=self).count() * 2
			except Exception:
				group_score = 0

			total = post_score + comment_score + reaction_score + repost_score + friend_score + group_score
			return max(0, total)
		except Exception:
			return 0

	@property
	def fihavanana_level(self):
		"""Niveau de solidarité basé sur le score."""
		score = self.score_fihavanana
		if score >= 500:
			return (_('Leader'), '🌟', '#f59e0b')
		elif score >= 200:
			return (_('Bienfaiteur'), '💛', '#10b981')
		elif score >= 80:
			return (_('Solidaire'), '💙', '#3b82f6')
		elif score >= 30:
			return (_('Ami'), '💚', '#22c55e')
		else:
			return (_('Visiteur'), '🤍', '#94a3b8')


@receiver(post_save, sender=Account)
def user_save(sender, instance, created, **kwargs):
    # Uniquement à la création : évite une requête inutile à chaque save().
    if created:
        FriendList.objects.get_or_create(user=instance)


# ─────────────────────────────────────────────────────────────────────────────
# Vérification OTP par SMS
# ─────────────────────────────────────────────────────────────────────────────
import secrets
import string

class PhoneVerification(models.Model):
    """Code OTP envoyé par SMS pour vérifier un numéro de téléphone."""

    user = models.ForeignKey(
        Account,
        on_delete=models.CASCADE,
        related_name='phone_verifications',
        verbose_name='Utilisateur',
        null=True, blank=True,      # (inscription depuis Pola : le compte n'existe pas encore)
    )
    phone = models.CharField(
        max_length=20,
        verbose_name='Numéro en cours de vérification',
        help_text='Format E.164 (+indicatif du pays, puis le numéro)',
    )
    # L'EMPREINTE du code (HMAC avec la clé secrète du site), jamais le code lui-même : quelqu'un
    # qui lirait la base (sauvegarde, accès à l'hébergeur) ne pourrait pas s'en servir.
    code = models.CharField(
        max_length=64,
        verbose_name='Empreinte du code',
    )
    # « verify » : confirmer le numéro d'un compte ; « login » : se connecter avec son numéro ;
    # « signup » : créer un compte depuis Pola avec son numéro.
    purpose    = models.CharField(max_length=10, default='verify', verbose_name='But')
    # « sms » ou « whatsapp »
    channel    = models.CharField(max_length=10, default='sms', verbose_name='Envoyé par')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Créé le')
    attempts   = models.PositiveSmallIntegerField(default=0, verbose_name='Tentatives')
    verified   = models.BooleanField(default=False, verbose_name='Validé')

    class Meta:
        verbose_name = 'Vérification téléphone'
        verbose_name_plural = 'Vérifications téléphone'
        ordering = ['-created_at']

    def __str__(self):
        who = self.user.username if self.user_id else '(inscription)'
        return f'{who} — {self.phone} ({"OK" if self.verified else "en attente"})'

    # Durée de validité en minutes
    OTP_VALID_MINUTES = 10
    # Max tentatives de saisie avant invalidation
    MAX_ATTEMPTS = 5
    # Max envois par numéro par heure
    MAX_SENDS_PER_HOUR = 3

    @classmethod
    def generate_code(cls):
        # secrets (et non random) : un OTP doit être imprévisible.
        return ''.join(secrets.choice(string.digits) for _ in range(6))

    @staticmethod
    def digest(phone, code):
        """L'empreinte d'un code pour un numéro (c'est elle qu'on garde, puis qu'on compare)."""
        import hashlib
        import hmac
        from django.conf import settings
        return hmac.new(settings.SECRET_KEY.encode(), f'{phone}:{code}'.encode(), hashlib.sha256).hexdigest()

    def matches(self, code):
        """Le code saisi est-il le bon ? (comparaison en temps constant)"""
        return secrets.compare_digest(self.code, self.digest(self.phone, code))

    @property
    def is_expired(self):
        from django.utils import timezone
        from datetime import timedelta
        return timezone.now() > self.created_at + timedelta(minutes=self.OTP_VALID_MINUTES)


class UserBlock(models.Model):
	"""`blocker` ne veut plus voir `blocked` ni en entendre parler : posts et
	commentaires masqués dans les deux sens, plus de message privé ni de
	demande d'ami possible entre les deux."""
	blocker    = models.ForeignKey(Account, on_delete=models.CASCADE, related_name='blocks_made')
	blocked    = models.ForeignKey(Account, on_delete=models.CASCADE, related_name='blocks_received')
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		unique_together = ('blocker', 'blocked')
		indexes = [models.Index(fields=['blocked', 'blocker'], name='userblock_reverse_idx')]

	def __str__(self):
		return f'{self.blocker} ⛔ {self.blocked}'

	@staticmethod
	def hidden_user_ids(user):
		"""Ids à masquer pour `user` : ceux qu'il a bloqués et ceux qui l'ont bloqué."""
		if not getattr(user, 'is_authenticated', False):
			return set()
		ids = set(UserBlock.objects.filter(blocker=user).values_list('blocked_id', flat=True))
		ids |= set(UserBlock.objects.filter(blocked=user).values_list('blocker_id', flat=True))
		return ids

	@staticmethod
	def is_blocked_between(a, b):
		return UserBlock.objects.filter(
			models.Q(blocker=a, blocked=b) | models.Q(blocker=b, blocked=a)
		).exists()
