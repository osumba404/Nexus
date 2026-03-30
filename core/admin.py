from django.contrib import admin
from django.utils.html import format_html
from .models import SiteSettings, UserProfile


@admin.register(SiteSettings)
class SiteSettingsAdmin(admin.ModelAdmin):
    fieldsets = (
        ('Branding', {
            'fields': ('site_name', 'site_tagline', 'logo', 'hero_banner', 'footer_text')
        }),
        ('API Keys', {
            'fields': ('newsdata_api_key', 'newsapi_key'),
            'classes': ('collapse',),
            'description': 'Keep these secret. They are used server-side only.'
        }),
        ('Defaults', {
            'fields': ('default_country', 'default_language')
        }),
        ('Performance', {
            'fields': ('cache_ttl', 'auto_refresh_seconds')
        }),
    )

    def has_add_permission(self, request):
        # Only allow one settings object
        return not SiteSettings.objects.exists()

    def logo_preview(self, obj):
        if obj.logo:
            return format_html('<img src="{}" height="50" />', obj.logo.url)
        return '(no logo)'
    logo_preview.short_description = 'Logo Preview'


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'default_country', 'default_language')
    search_fields = ('user__username', 'user__email')
    list_filter = ('default_country', 'default_language')
