from django.db import models
from django.contrib.auth.models import User


class ArticleComment(models.Model):
    """User comment on a news article (identified by its URL)."""
    article_url = models.URLField(max_length=1000, db_index=True)
    user        = models.ForeignKey(User, on_delete=models.CASCADE, related_name='article_comments')
    text        = models.TextField(max_length=2000)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"{self.user.username} on {self.article_url[:60]}: {self.text[:40]}"


class SavedArticle(models.Model):
    LIKE = 'like'
    BOOKMARK = 'bookmark'
    INTERACTION_CHOICES = [(LIKE, 'Like'), (BOOKMARK, 'Bookmark')]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='saved_articles')
    url = models.URLField(max_length=1000)
    title = models.CharField(max_length=500)
    excerpt = models.TextField(blank=True)
    image_url = models.URLField(max_length=1000, blank=True)
    source_name = models.CharField(max_length=200, blank=True)
    published_at = models.CharField(max_length=50, blank=True)
    category = models.CharField(max_length=100, blank=True)
    interaction_type = models.CharField(max_length=10, choices=INTERACTION_CHOICES)
    saved_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'url', 'interaction_type')
        ordering = ['-saved_at']

    def __str__(self):
        return f"{self.user.username} {self.interaction_type}: {self.title[:60]}"
