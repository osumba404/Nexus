from django.contrib import admin
from django.core.cache import cache
from django.contrib import messages


# No news models are stored in the database.
# The admin panel provides cache management actions.

class NewsCacheAdmin(admin.ModelAdmin):
    """Placeholder for future cache administration."""
    pass


# Custom admin site header
admin.site.site_header = 'Epicenter Nexus Administration'
admin.site.site_title = 'Nexus Admin'
admin.site.index_title = 'Platform Management'
