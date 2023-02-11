from django.urls import path

from . import views

urlpatterns = [
    path('mapalitics/Mapalitics.Script.txt', views.get_ml_script, name='get-mapalitics-ml-script'),
    path('mapalitics/<str:wsid>/Mapalitics.Script.txt', views.get_user_ml_script, name='get-mapalitics-ml-script-for-user'),
    path('mapalitics/event', views.post_mapalitics_event),
]
