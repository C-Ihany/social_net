DEFAULT_ROOM_CHAT_MESSAGE_PAGE_SIZE = 10

MSG_TYPE_MESSAGE = 0  # Standard text message
MSG_TYPE_ENTER   = 1  # User joined the room
MSG_TYPE_LEAVE   = 2  # User left the room
MSG_TYPE_FILE    = 3  # File / media attachment
MSG_TYPE_TYPING  = 4  # Someone is typing...

# WebRTC call signaling
MSG_TYPE_CALL_OFFER  = 5  # Caller → Callee  (SDP offer + call mode)
MSG_TYPE_CALL_ANSWER = 6  # Callee → Caller  (SDP answer)
MSG_TYPE_CALL_ICE    = 7  # Either side       (ICE candidate)
MSG_TYPE_CALL_REJECT = 8  # Callee refused
MSG_TYPE_CALL_END    = 9  # Either side hung up

# Badge non-lu temps-réel
MSG_TYPE_UNREAD_NOTIF = 10  # Notification badge non-lu → sidebar

# Réactions emoji
MSG_TYPE_REACTION = 11  # Toggle emoji reaction sur un message

# Conversation secrète (chiffrement de bout en bout) activée ou coupée
MSG_TYPE_SECRET = 12

# Ce que le serveur montre à la place d'un message chiffré (il ne peut pas le lire)
SECRET_PREVIEW      = '🔒 Message chiffré'
SECRET_FILE_PREVIEW = '🔒 Fichier chiffré'
