from django.urls import path

from . import views

urlpatterns = [
    path('itemrefresh/create_map', views.create_map, name='create_map'),
]
