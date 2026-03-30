from django.contrib import admin
from .models import SavedArticle

admin.site.site_header = 'Epicenter Nexus Administration'
admin.site.site_title = 'Nexus Admin'
admin.site.index_title = 'Platform Management'


@admin.register(SavedArticle)
class SavedArticleAdmin(admin.ModelAdmin):
    list_display = ('user', 'interaction_type', 'source_name', 'category', 'saved_at', 'short_title')
    list_filter = ('interaction_type', 'category', 'saved_at')
    search_fields = ('user__username', 'title', 'source_name')
    readonly_fields = ('saved_at',)

    def short_title(self, obj):
        return obj.title[:80]
    short_title.short_description = 'Title'
