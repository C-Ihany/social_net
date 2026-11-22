from ZOOT.ratelimit import ratelimit
from .video_feed import video_feed_view, video_feed_more
from django.urls import path, register_converter
from django.views.generic import RedirectView


class HashtagConverter:
    """Hashtag avec accents (#randonnée, #Fianarantsoa) : le convertisseur
    `slug` n'accepte que l'ASCII et faisait planter le fil entier dès qu'un
    post contenait un tag accentué (NoReverseMatch au rendu)."""
    regex = r'[\w-]{1,40}'

    def to_python(self, value):
        return value

    def to_url(self, value):
        return value


register_converter(HashtagConverter, 'hashtag')

from .views import (
    Index,
    AddPostView,
    post_feed_view,
    post_feed_more,
    UpdatePostView,
    DeletePostView,
    like_post,
    react_post,
    hashtag_view,
    tendances_view,
    mention_autocomplete,
    follow,
    unfollow,
    add_comment,
    new_comments,
    delete_comment,
    post_detail,
    repost_post,
    report_content,
    bookmark_post,
    hide_post,
    mes_brouillons,
    mes_favoris_posts,
    reactions_who,
    publish_draft,
    delete_post_now,
)
from .products import my_products

app_name = 'post'

urlpatterns = [
    path('index/',        Index,                    name='index'),
    path('',              post_feed_view,           name='post-view'),
    path('add-post/',     ratelimit('10/m')(AddPostView.as_view()), name='addPost'),
    path('edit-post/<int:pk>/',   UpdatePostView.as_view(), name='edit-post'),
    path('delete-post/<int:pk>/', DeletePostView.as_view(), name='delete-post'),
    path('delete-post/<int:pk>/now/', delete_post_now,   name='delete-post-now'),
    path('publish/<int:pk>/',     publish_draft,            name='publish-draft'),
    path('like/',         ratelimit('60/m')(like_post), name='like-post'),
    path('follow/',       follow,                   name='follow'),
    path('unfollow/',     unfollow,                 name='unfollow'),
    path('comment/<int:post_id>/add/',       ratelimit('15/m')(add_comment), name='add-comment'),
    path('comment/<int:post_id>/new/',       new_comments,   name='new-comments'),
    path('comment/<int:comment_id>/delete/', delete_comment, name='delete-comment'),
    path('feed/more/',         post_feed_more,        name='feed-more'),
    path('react/',             ratelimit('60/m')(react_post), name='react-post'),
    path('hashtag/<hashtag:tag>/', hashtag_view,         name='hashtag'),
    path('mention/autocomplete/', mention_autocomplete, name='mention-autocomplete'),
    path('bookmark/',          bookmark_post,         name='bookmark'),
    path('hide/',              hide_post,             name='hide'),
    path('brouillons/',        mes_brouillons,        name='mes-brouillons'),
    path('sauvegardes/',       mes_favoris_posts,     name='mes-favoris-posts'),
    path('repost/',            ratelimit('20/m')(repost_post), name='repost'),
    # Pages de création Kabary / Vintana retirées (2026-11). Les deux noms de
    # route restent le temps que templates/base.html et snippets/header.html
    # (hors de ce module) cessent de les citer : ils renvoient à « Créer un post ».
    path('kabary/create/',     RedirectView.as_view(pattern_name='post:addPost', permanent=False), name='kabary-create'),
    path('vintana/create/',    RedirectView.as_view(pattern_name='post:addPost', permanent=False), name='vintana-create'),
    path('tendances/',         tendances_view,        name='tendances'),
    path('videos/',            video_feed_view,       name='video-feed'),
    path('videos/more/',       video_feed_more,       name='video-feed-more'),
    path('products/mine/',     my_products,           name='my-products'),
    path('signaler/',          ratelimit('10/h')(report_content), name='report-content'),
    path('<int:post_id>/reactions/', reactions_who,  name='reactions-who'),
    path('<int:post_id>/',           post_detail,    name='post-detail'),
]
