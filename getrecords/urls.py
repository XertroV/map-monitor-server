from django.urls import path

from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('map/<str:map_uid>/nb_players', views.get_nb_players, name='get-nb-players'),
    path('map/<str:map_uid>/nb_players/refresh', views.refresh_nb_players, name='refresh-nb-players'),
    path('map/<str:map_uid>/<int:score>/refresh', views.get_surround_score, name='get-surround-score'),
    path('upload/ghost/<str:map_uid>/<int:score>', views.ghost_upload, name='upload-ghost'),
]
