from ZOOT.ratelimit import ratelimit
from django.urls import path

from chat.views import (
	private_chat_room_view,
	create_or_return_private_chat,
	upload_chat_file,
	send_story_reply,
	call_reject_push,
	get_ice_servers,
	chat_file,
	set_secret,
)

app_name = 'chat'

urlpatterns = [
	path('',                           private_chat_room_view,         name='private-chat-room'),
	path('create_or_return_private_chat', create_or_return_private_chat, name='create-or-return-private-chat'),
	path('upload_file/',               ratelimit('30/m')(upload_chat_file), name='upload-chat-file'),
	path('story-reply/',               send_story_reply,               name='story_reply'),
	path('call-reject-push/',          call_reject_push,               name='call-reject-push'),
	path('ice-servers/',               get_ice_servers,                name='ice-servers'),
	# Un fichier du chat privé : seulement pour les deux personnes de la conversation.
	# Conversation secrète (chiffrement de bout en bout) : activer / couper
	path('secret/',                    ratelimit('20/m')(set_secret),  name='secret'),
	path('fichier/<int:msg_id>/',      ratelimit('120/m', methods=('GET',))(chat_file), name='file'),
]