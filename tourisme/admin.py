from django.contrib import admin
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from django.utils.translation import gettext as _

from .models import LieuTouristique, LieuImage, GuideTouristique


def notify_lieu_approved(lieu, by_user=None):
    """Notification in-app (+ push si configuré) à l'auteur d'un lieu qui vient d'être
    approuvé. Ne casse jamais l'admin en cas d'erreur."""
    author = lieu.added_by
    if author is None or (by_user is not None and author.pk == by_user.pk):
        return False
    try:
        from notification.models import Notification, PushSubscription
        url = reverse('tourisme:lieu_detail', kwargs={'slug': lieu.slug})
        verb = _('Votre lieu « %(name)s » a été approuvé : il est maintenant visible par tous.') % {'name': lieu.name}
        Notification.objects.create(
            target=author, from_user=by_user, verb=verb[:255], redirect_url=url,
            content_type=ContentType.objects.get_for_model(lieu), object_id=str(lieu.pk),
        )
        PushSubscription.send_notification(author, _('Vazimba Tourisme'), verb, url)
        return True
    except Exception:
        return False


class LieuImageInline(admin.TabularInline):
    model = LieuImage
    extra = 3
    fields = ('image', 'caption', 'is_primary', 'order')


@admin.register(LieuTouristique)
class LieuTouristiqueAdmin(admin.ModelAdmin):
    list_display  = ('name', 'category', 'region', 'is_approved', 'views_count', 'created_at')
    list_filter   = ('is_approved', 'category', 'region')
    list_editable = ('is_approved',)
    search_fields = ('name', 'description')
    prepopulated_fields = {'slug': ('name',)}
    inlines = [LieuImageInline]
    actions = ['approve_lieux', 'unapprove_lieux']

    def save_model(self, request, obj, form, change):
        """Prévient l'auteur quand son lieu passe à « approuvé » (fiche ou liste modifiable)."""
        was_approved = False
        if change and obj.pk:
            was_approved = bool(LieuTouristique.objects.filter(pk=obj.pk).values_list('is_approved', flat=True).first())
        super().save_model(request, obj, form, change)
        if obj.is_approved and not was_approved:
            notify_lieu_approved(obj, request.user)

    def approve_lieux(self, request, qs):
        lieux = list(qs.filter(is_approved=False).select_related('added_by'))
        qs.update(is_approved=True)
        for lieu in lieux:
            lieu.is_approved = True
            notify_lieu_approved(lieu, request.user)
        self.message_user(request, f'{len(lieux)} lieu(x) approuvé(s).')
    approve_lieux.short_description = 'Approuver'

    def unapprove_lieux(self, request, qs):
        qs.update(is_approved=False)
    unapprove_lieux.short_description = 'Désapprouver'


@admin.register(GuideTouristique)
class GuideTouristiqueAdmin(admin.ModelAdmin):
    list_display  = ('display_name_col', 'is_verified', 'is_active', 'prix_jour', 'years_experience', 'created_at')
    list_filter   = ('is_verified', 'is_active')
    list_editable = ('is_verified', 'is_active')
    search_fields = ('user__username', 'user__first_name', 'bio', 'specialities')
    raw_id_fields = ('user',)

    def display_name_col(self, obj):
        return str(obj)
    display_name_col.short_description = 'Guide'
