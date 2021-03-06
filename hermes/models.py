import os
import operator

from django.contrib.auth.models import User
from django.db import models
from django.utils.text import Truncator, slugify
from django.utils.translation import ugettext as _
from django.db.models.signals import pre_delete
from django.dispatch.dispatcher import receiver

from . import settings


class TimestampedModel(models.Model):
    created_on = models.DateTimeField(_('created on'), auto_now_add=True)
    modified_on = models.DateTimeField(_('modified on'), auto_now=True)

    class Meta:
        abstract = True


class CategoryManager(models.Manager):
    def children_of(self, category, categories=None):
        if categories is None:
            categories = list(self.all())

        children = filter(lambda c: c.parent == category, categories)
        for child in children:
            children.extend(self.children_of(child, categories))

        return children


class Category(models.Model):
    title = models.CharField(_('title'), max_length=100)
    parent = models.ForeignKey('self', blank=True, null=True)
    slug = models.CharField(blank=True, default='', max_length='500')

    objects = CategoryManager()

    class Meta:
        verbose_name = u'category'
        verbose_name_plural = u'categories'

    def save(self, *args, **kwargs):
        self.slug = self._generate_slug()
        super(Category, self).save(*args, **kwargs)

    def __unicode__(self):
        return u" > ".join([category.title for category in self.hierarchy()])

    def __str__(self):
        return self.__unicode__()

    @models.permalink
    def get_absolute_url(self):
        return ('hermes_category_post_list', (), {
            'slug': self.slug,
        })

    def _generate_slug(self):
        return "/".join([slugify(category.title) for category in self.hierarchy()]).lower()

    @property
    def is_root(self):
        """ Returns True if this category has no parent. """
        return self.parent is None

    def parents(self):
        """ Returns a list of all the current category's parents."""
        parents = []

        if self.parent is None:
            return []

        category = self
        while category.parent is not None:
            parents.append(category.parent)
            category = category.parent

        return parents[::-1]

    def hierarchy(self):
        return self.parents() + [self]

    def root_parent(self, category=None):
        """ Returns the topmost parent of the current category. """
        return filter(lambda c: c.is_root, self.hierarchy())[0]


class PostQuerySet(models.query.QuerySet):
    def in_category(self, category_slug):
        category = Category.objects.get(slug=category_slug)
        children = Category.objects.children_of(category)

        return self.filter(category__in=[category] + children)

    def created_on(self, year=None, month=None, day=None):
        clauses = []

        if year:
            clauses.append(models.Q(created_on__year=year))

        if month:
            clauses.append(models.Q(created_on__month=month))

        if day:
            clauses.append(models.Q(created_on__day=day))

        return self.filter(reduce(operator.__and__, clauses))

    def recent(self, limit=None):
        queryset = self.all()
        if limit:
            queryset = queryset[:limit]

        return queryset

    def random(self, limit=None):
        queryset = self.recent().order_by('?')
        if limit:
            queryset = queryset[:limit]

        return queryset


class PostManager(models.Manager):
    def get_queryset(self):
        return PostQuerySet(Post)

    def __getattr__(self, attr, *args):
        try:
            return getattr(self.__class__, attr, *args)
        except AttributeError:
            return getattr(self.get_queryset(), attr, *args)

class Post(TimestampedModel):
    subject = models.CharField(_('subject'), max_length=100)
    slug = models.SlugField(_('slug'), max_length=100, unique=True)
    summary = models.TextField(_('summary'), blank=True, null=True)
    body = models.TextField(_('body'))

    category = models.ForeignKey(Category, related_name="categories")
    author = models.ForeignKey(User)

    objects = PostManager()

    class Meta:
        ordering = ('-modified_on', )

    def __unicode__(self):
        return self.subject

    def __str__(self):
        return self.__unicode__()

    @models.permalink
    def get_absolute_url(self):
        return ('hermes_post_detail', (), {
            'slug': self.slug,
        })

    @property
    def short(self):
        if self.summary:
            return self.summary
        else:
            return Truncator(self.body).words(30)

    @property
    def rendered_summary(self):
        if settings.MARKUP_RENDERER:
            return settings.MARKUP_RENDERER(self.short)
        else:
            return self.short

    @property
    def rendered(self):
        if settings.MARKUP_RENDERER:
            return settings.MARKUP_RENDERER(self.body)
        else:
            return self.body

    @property
    def reading_time(self):
        time = (self.summary.count(' ') + self.body.count(' ')) / 300
        if time == 0:
            time = 1
        return time


def postfile_upload_to(instance, filename):
    return "uploads/hermes/{article}/{filename}".format(
        article=instance.pk,
        filename=filename
    )


class PostFile(models.Model):
    post = models.ForeignKey(Post, related_name='files')
    f = models.FileField(upload_to=postfile_upload_to)

    class Meta:
        verbose_name = "PostFile"
        verbose_name_plural = "PostFiles"

    def __unicode__(self):
        return u'File for {}'.format(self.post)

    def __str__(self):
        return self.__unicode__()

@receiver(pre_delete, sender=PostFile)
def postfile_delete(sender, instance, **kwargs):
    instance.f.delete(False)