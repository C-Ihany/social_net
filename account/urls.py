from django.urls import path, include
from ZOOT.ratelimit import ratelimit
from .views import (
    account_view, edit_account_view, crop_image,
    global_search_api, profile_posts_more, update_cover_image,
    phone_send_otp, phone_verify_otp, toggle_block, delete_account_view,
)

app_name = 'account'

urlpatterns = [
    path('supprimer/',                 delete_account_view, name="delete"),
    path('bloquer/<int:user_id>/',     toggle_block,        name="block"),
    path('<int:user_id>/',                  account_view,        name="view"),
    path('<int:user_id>/edit/',             edit_account_view,   name="edit"),
    path('<int:user_id>/edit/cropImage',    crop_image,          name="crop_image"),
    path('<int:user_id>/posts/more/',       profile_posts_more,  name="profile-posts-more"),
    path('search/api/',                 global_search_api,   name="search-api"),
    path('cover/update/',              update_cover_image,  name="update-cover"),
    # ── Vérification téléphone ─────────────────────────────────────────────
    # (par adresse IP en plus : un compte n'est pas une limite, on en crée un autre)
    path('phone/envoyer-code/',        ratelimit('6/h', key='ip')(phone_send_otp),    name="phone-send-otp"),
    path('phone/verifier/',            ratelimit('20/h', key='ip')(phone_verify_otp), name="phone-verify-otp"),
]