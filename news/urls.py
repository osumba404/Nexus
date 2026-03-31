from django.urls import path
from . import views

app_name = 'news'

urlpatterns = [
    path('', views.home, name='home'),
    path('feed/', views.news_feed, name='feed'),
    path('trending/', views.trending, name='trending'),
    path('my-feed/', views.my_feed, name='my_feed'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('interact/', views.toggle_interaction, name='toggle_interaction'),
    path('preferences/', views.save_preferences, name='save_preferences'),
    path('article/', views.article_detail, name='article_detail'),
    path('article/comment/', views.post_comment, name='post_comment'),
    path('article/comment/<int:pk>/delete/', views.delete_comment, name='delete_comment'),
]
