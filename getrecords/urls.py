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

    # v2 of COTD caching
    path('cached/api/challenges/<int:challenge_id>/records/maps/<str:map_uid>', views.cached_api_challenges_id_records_maps_uid),
    # tmp for ingestion
    path('get_all/challenges/<int:challenge_id>/records/maps/<str:map_uid>', views.get_all_cotd_results),
    path('cached/api/challenges/<int:challenge_id>/records/maps/<str:map_uid>/players', views.cached_api_challenges_id_records_maps_uid_players),
    path('cached/api/cup-of-the-day/current', views.cached_api_cotd_current),

    # kr5 results
    path('kr5/results', views.get_kr5_cached_doc),
    path('kr5/maps', views.get_kr5_maps_cached_doc),
    path('kr5/map/<int:map_number>', views.get_kr5_map_lb_cached_doc),

    # old archivist stuff
    path('upload/ghost/<str:map_uid>/<int:score>', views.ghost_upload, name='upload-ghost'),
    path('upload/ghost/<str:map_uid>/-<int:score>', views.ghost_upload, name='upload-ghost'),
    path(f'register/token/{ARCHIVIST_PLUGIN_ID}', views.register_token_archivist, name='register-token-archivist'),
    path(f'register/token/{MAP_MONITOR_PLUGIN_ID}', views.register_token_mm, name='register-token-mm'),

    # tmx proxy stuff
    path(f'tmx/<int:map_id>/next', views.tmx_next_map),
    path(f'tmx/<int:map_id>/prev', views.tmx_prev_map),
    path(f'tmx/<int:map_id>/count_prior', views.tmx_count_at_map),
    path(f'mapsearch2/search', views.tmx_compat_mapsearch2, name='tmx_compat_mapsearch2'),
    path(f'api/maps', views.tmx_compat_random_api2, name='tmx_compat_random_api2'),
    path(f'api/maps/<int:trackid>', views.api_tmx_get_map, name='tmx_get_map'),
    path(f'maps/download/<int:mapid>', views.map_dl, name='map_dl'),
    path(f'mapgbx/<int:mapid>', views.map_dl, name='map_dl'),
    path(f'mapgbx/<int:mapid>/', views.map_dl, name='map_dl'),
    path(f'api/maps/get_map_info/multi/<str:mapids>', views.tmx_maps_get_map_info_multi),
    path(f'api/meta/tags', views.tmx_api_tags_gettags_refresh),
    path(f'api/tags/gettags', views.tmx_api_tags_gettags_refresh),
    path(f'api/tags/gettags/refresh', views.tmx_api_tags_gettags_refresh),
    path(f'tmx/unbeaten_ats', views.unbeaten_ats),
    path(f'tmx/unbeaten_ats/leaderboard', views.unbeaten_ats_lb),
    path(f'tmx/unbeaten_ats/<int:trackid>', views.get_unbeaten_at_details, name='get_unbeaten_at_details'),
    path(f'tmx/recently_beaten_ats', views.recently_beaten_ats),
    path(f'tmx/track_ids_to_uid', views.track_ids_to_uid),
    path(f'tmx/uid_to_tid_map', views.tmx_uid_to_tid_map),
    # path(f'debug/nb_dup_tids', views.debug_nb_dup_tids),
    path(f'debug/nb_track_types', views.debug_nb_track_types),

    path(f'e++/icons/convert/webp', views.convert_webp_to_png),
    path(f'e++/icons/convert/rgba', views.convert_rgba_to_png),
    path(f'e++/lm-analysis/convert/webp', views.lm_conversion_req),

    path(f'tmx/convert_webp', views.convert_tmx_webp_thumbnail),
]
