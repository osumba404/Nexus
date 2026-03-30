from django.urls import path
from . import views

app_name = 'news'

urlpatterns = [
    path('', views.home, name='home'),
    path('feed/', views.news_feed, name='feed'),
    path('trending/', views.trending, name='trending'),
    path('my-feed/', views.my_feed, name='my_feed'),
    path('preferences/', views.save_preferences, name='save_preferences'),
]
