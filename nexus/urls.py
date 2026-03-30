from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from core.views import signup

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/signup/', signup, name='signup'),
    path('accounts/', include('django.contrib.auth.urls')),
    path('', include('news.urls', namespace='news')),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
