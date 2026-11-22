from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def activate_rooms_with_messages(apps, schema_editor):
    """Les conversations qui ont déjà des messages apparaissent dans la liste (avant, seule
    l'amitié les activait : celles avec un non-ami restaient invisibles)."""
    Room = apps.get_model('chat', 'PrivateChatRoom')
    Message = apps.get_model('chat', 'RoomChatMessage')
    Room.objects.filter(is_active=False, pk__in=Message.objects.values('room_id')).update(is_active=True)


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('chat', '0007_conversation_secrete'),
    ]

    operations = [
        migrations.AddField(
            model_name='privatechatroom',
            name='secret_changed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='privatechatroom',
            name='secret_changed_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                    related_name='+', to=settings.AUTH_USER_MODEL),
        ),
        migrations.RunPython(activate_rooms_with_messages, migrations.RunPython.noop),
    ]
