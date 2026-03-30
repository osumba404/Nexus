from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver


class SiteSettings(models.Model):
    site_name = models.CharField(max_length=100, default='Epicenter Nexus')
    site_tagline = models.CharField(max_length=200, default='Your Real-Time News Hub')
    newsdata_api_key = models.CharField(max_length=200, blank=True, help_text='API key from newsdata.io')
    newsapi_key = models.CharField(max_length=200, blank=True, help_text='API key from newsapi.org')
    cache_ttl = models.IntegerField(default=180, help_text='Cache TTL in seconds')
    auto_refresh_seconds = models.IntegerField(default=180, help_text='Auto-refresh interval in seconds')
    logo = models.ImageField(upload_to='branding/', null=True, blank=True)
    hero_banner = models.ImageField(upload_to='branding/', null=True, blank=True)
    default_country = models.CharField(max_length=5, default='ke', help_text='Default country code (e.g. ke for Kenya)')
    default_language = models.CharField(max_length=5, default='en')
    footer_text = models.TextField(default='© 2026 Epicenter Nexus. Powered by 404Evans™')

    class Meta:
        verbose_name = 'Site Settings'
        verbose_name_plural = 'Site Settings'

    def __str__(self):
        return self.site_name

    @classmethod
    def get_settings(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    default_country = models.CharField(max_length=5, default='ke')
    default_categories = models.CharField(
        max_length=500, blank=True, default='',
        help_text='Comma-separated list of preferred categories'
    )
    default_language = models.CharField(max_length=5, default='en')
    saved_keywords = models.CharField(max_length=500, blank=True, default='')

    def __str__(self):
        return f"{self.user.username}'s profile"

    def get_categories_list(self):
        if self.default_categories:
            return [c.strip() for c in self.default_categories.split(',')]
        return []


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.create(user=instance)


@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    if hasattr(instance, 'profile'):
        instance.profile.save()
