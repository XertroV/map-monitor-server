from django.urls import path

from getrecords.openplanet import ARCHIVIST_PLUGIN_ID, MAP_MONITOR_PLUGIN_ID

from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('map/<str:map_uid>/nb_players', views.get_nb_players, name='get-nb-players'),
    path('map/<str:map_uid>/nb_players/refresh', views.refresh_nb_players, name='refresh-nb-players'),
    path('map/<str:map_uid>/<int:score>/refresh', views.get_surround_score, name='get-surround-score'),
    path('challenges/<int:challenge_id>/records/maps/<str:map_uid>', views.get_cotd_leaderboards, name='get-cotd-leaderboard'),
    path('api/challenges/<int:challenge_id>/records/maps/<str:map_uid>', views.get_cotd_leaderboards, name='api-get-cotd-leaderboard'),
    path('upload/ghost/<str:map_uid>/<int:score>', views.ghost_upload, name='upload-ghost'),
    path('upload/ghost/<str:map_uid>/-<int:score>', views.ghost_upload, name='upload-ghost'),
    path(f'register/token/{ARCHIVIST_PLUGIN_ID}', views.register_token_archivist, name='register-token-archivist'),
    path(f'register/token/{MAP_MONITOR_PLUGIN_ID}', views.register_token_mm, name='register-token-mm'),
    path(f'mapsearch2/search', views.tmx_compat_mapsearch2, name='tmx_compat_mapsearch2'),
    path(f'maps/download/<int:mapid>', views.map_dl, name='map_dl'),
    path(f'api/maps/get_map_info/multi/<str:mapids>', views.tmx_maps_get_map_info_multi),
    path(f'api/tags/gettags', views.tmx_api_tags_gettags),
]