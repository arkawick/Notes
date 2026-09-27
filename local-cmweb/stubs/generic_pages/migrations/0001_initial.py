"""Initial schema for the ``generic_pages`` shim app.

Named ``0001_initial`` because ``blog/migrations/0001_initial.py`` in cmweb-app
declares a dependency on ``('generic_pages', '0001_initial')``.
"""

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    """Create the generic page table."""

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='GenericPage',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True,
                                        serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=200)),
                ('slug', models.SlugField(unique=True)),
                ('body', models.TextField(blank=True)),
                ('status', models.IntegerField(
                    choices=[(1, 'Draft'), (2, 'Public')], db_index=True,
                    default=2)),
                ('publish', models.DateTimeField(
                    db_index=True, default=django.utils.timezone.now)),
                ('auto_toc', models.BooleanField(default=False)),
                ('show_published', models.BooleanField(default=False)),
                ('created', models.DateTimeField(auto_now_add=True)),
                ('date_modified', models.DateTimeField(auto_now=True)),
                ('author', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='generic_pages',
                    to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'generic page',
                'verbose_name_plural': 'generic pages',
                'ordering': ('-publish',),
                'get_latest_by': 'publish',
            },
        ),
    ]
