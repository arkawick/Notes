# 03 — Models and their role in database interactions

> **Goal:** be able to read any model in `explorer/models.py` and say exactly
> what table, columns, indexes and queries it produces — and know when to reach
> for a manager, a property, or a denormalised column instead.

---

## 1. What a model is

A Django model is a Python class that **is** a database table.

```python
from django.db import models


class Build(models.Model):
    name = models.CharField(max_length=200, unique=True)
    created = models.DateTimeField(auto_now_add=True)
```

From that one class Django derives:

| Derived thing | Value here |
| --- | --- |
| Table name | `<app_label>_<lowercased class name>` -> `builds_build` |
| Primary key | An implicit `id = BigAutoField(primary_key=True)` |
| Columns | `id`, `name`, `created` |
| Indexes | unique index on `name` |
| A manager | `Build.objects` |
| A migration | when you run `makemigrations` |
| An admin form | when registered in `admin.py` |
| Validation rules | `max_length`, `null`, `blank`, `choices` |

This is an **active record**-flavoured ORM: an instance is a row, and the
instance has methods that touch the database (`.save()`, `.delete()`,
`.refresh_from_db()`).

### The three layers you will be moving between

```
  Model class          Build                     the table
  Manager              Build.objects             the entry point to queries
  QuerySet             Build.objects.filter(..)  a lazy, chainable SQL builder
  Model instance       Build(...)                one row
```

---

## 2. Fields

### The common field types

| Field | SQL-ish type | Notes |
| --- | --- | --- |
| `CharField(max_length=N)` | `varchar(N)` | `max_length` is **required** |
| `TextField()` | `text` | No length limit; no `max_length` needed |
| `IntegerField()` / `BigIntegerField()` | `integer` / `bigint` | |
| `DecimalField(max_digits, decimal_places)` | `numeric` | Use for money/scores, not `FloatField` |
| `BooleanField(default=...)` | `boolean` | |
| `DateTimeField()` | `timestamptz` | See `auto_now` vs `auto_now_add` below |
| `SlugField()` | `varchar` + validator | Letters, numbers, underscores, hyphens |
| `JSONField()` | `jsonb` on PostgreSQL | Django 3.1+ |
| `ForeignKey(...)` | `integer` + FK constraint | Many-to-one |
| `OneToOneField(...)` | FK + unique | One-to-one |
| `ManyToManyField(...)` | *a whole extra table* | Many-to-many |

### The options that matter most

| Option | Effect | Common mistake |
| --- | --- | --- |
| `null=True` | The **database** column may be `NULL` | Setting it on `CharField` — Django convention is to use `''`, not two kinds of empty |
| `blank=True` | The **form/validation** layer allows empty | People assume it affects the database. It does not. |
| `default=` | Value used when not supplied | A *callable* (`timezone.now`) not a *call* (`timezone.now()`) |
| `db_index=True` | Adds an index | Free reads, slower writes, more disk |
| `unique=True` | Unique constraint (and an index) | |
| `editable=False` | Hidden from `ModelForm` and admin | Very common in CMWEB for indexed-not-entered data |
| `choices=` | Validation + `get_FOO_display()` | |
| `related_name=` | The reverse accessor name | Omit it and you get `<model>_set` |
| `on_delete=` | **Required** on FKs since Django 2.0 | See below |

### `null` vs `blank`, concretely

```python
notes = models.TextField(blank=True)                 # form may be empty, column is NOT NULL, stores ''
parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL)
                                                     # both: optional in forms AND nullable in DB
```

### `on_delete` — the four you will actually meet

| Value | When the referenced row is deleted |
| --- | --- |
| `CASCADE` | This row is deleted too |
| `SET_NULL` | This FK becomes `NULL` (requires `null=True`) |
| `PROTECT` | Deletion is refused with `ProtectedError` |
| `DO_NOTHING` | Django does nothing; the database constraint decides |

CMWEB's `ManifestBranch` shows a deliberate mix, `explorer/models.py:311`:

```python
class ManifestBranch(Branch):
    latest_label = models.OneToOneField(
        'Label', on_delete=models.SET_NULL,
        related_name='manifest_branch_for_latest', null=True)
    parent = models.ForeignKey('self', on_delete=models.SET_NULL,
                               blank=True, null=True,
                               related_name='child_branches')
    system = models.ForeignKey(
        System, on_delete=models.CASCADE,
        related_name='cmweb_branch_cache', null=True, blank=True)
```

Read that as a set of decisions: *losing the latest build must not delete the
branch* (`SET_NULL`), but *a branch is meaningless without its system*
(`CASCADE`).

### `auto_now` vs `auto_now_add` vs `default`

```python
date_modified = models.DateTimeField(auto_now=True)       # set on EVERY save
date_created  = models.DateTimeField(auto_now_add=True)   # set once, on insert
date_created  = models.DateTimeField(default=timezone.now) # set once, but OVERRIDABLE
```

The third form is what CMWEB uses for `Label.date_created`, and the reason is
important: builds are **imported** with a creation timestamp that comes from
C2D, not from when the row happened to be inserted. `auto_now_add` would
destroy that.

```python
date_created = models.DateTimeField(default=timezone.now, db_index=True)
```

### Self-referential and string references

```python
previous = models.ForeignKey('self', on_delete=models.CASCADE, null=True,
                             blank=True, related_name='next_labels')
latest_label = models.OneToOneField('Label', ...)   # string: class not defined yet
```

Use a string when the target class is defined later in the file (or in another
app: `'explorer.Label'`).

---

## 3. Relations, and what they mean at the SQL level

### Many-to-one: `ForeignKey`

```python
class Branch(models.Model):
    name = models.CharField(max_length=200)
    project = models.ForeignKey(Project, on_delete=models.CASCADE,
                                related_name='branches')
```

- Column added: `project_id` on the `explorer_branch` table.
- Forward: `branch.project` -> one `Project` (a query, unless
  `select_related`).
- Reverse: `project.branches` -> a manager over many `Branch` rows, named by
  `related_name`.

### One-to-one: `OneToOneField`

A `ForeignKey` with `unique=True`, plus a nicer reverse accessor
(`branch.latest_label` gives an object, not a manager).

### Many-to-many: `ManyToManyField`

```python
commits = models.ManyToManyField('Commit', related_name='labels',
                                 blank=True, editable=False)
```

Django silently creates a join table `explorer_label_commits(label_id,
commit_id)`. You never see it as a model — unless you ask for one.

### `through=` — a join table you control

When the relationship itself has attributes, name a *through model*:

```python
components = models.ManyToManyField(ManifestComponent,
                                    related_name='labels',
                                    blank=True,
                                    through=LabelComponentMembership,
                                    editable=False)
sublabels = models.ManyToManyField('self', blank=True,
                                   related_name='labels',
                                   symmetrical=False,
                                   through=LabelMembership,
                                   editable=False)
all_commits = models.ManyToManyField('Commit', editable=False,
                                     related_name='delivered_labels',
                                     through='CommitDelivery')
```

`LabelComponentMembership` is a full model with its own manager and its own
methods (`added()`, `removed()`, `changed()`), because "this repository was at
revision X in this build" is itself a domain fact worth querying.

Note `symmetrical=False` on the self-referential `sublabels`: by default a
self-M2M is symmetric (if A relates to B then B relates to A). A build
containing a sub-build is *not* symmetric, so it must be turned off.

---

## 4. `class Meta` — table-level configuration

```python
class Meta(object):
    ordering = ('-date_created',)
    unique_together = (('name', 'manifest_branch'),)
    verbose_name = 'build'
    get_latest_by = 'date_created'
```

That is `Label.Meta`, and every line does real work:

| Option | Effect |
| --- | --- |
| `ordering` | Default `ORDER BY` on every unqualified queryset |
| `unique_together` | A composite unique constraint (modern equivalent: `constraints = [UniqueConstraint(...)]`) |
| `verbose_name` / `verbose_name_plural` | Display name in admin, forms, error messages |
| `get_latest_by` | Makes `.latest()` and `.earliest()` work with no argument |
| `db_table` | Override the generated table name |
| `abstract = True` | Not a table; only a base class to inherit fields from |
| `indexes` / `constraints` | Explicit multi-column indexes and check constraints |

`Project.Meta` shows why `verbose_name` matters here:

```python
class Meta(object):
    verbose_name = 'Repository'
    verbose_name_plural = 'Repositories'
    ordering = ('-is_manifest', '-importance', 'name',)
```

The class is called `Project` (Gerrit's word), but users say "repository", and
the URL is `/repositories/`. The model carries the translation.

> **Cost warning.** `ordering` applies to *every* query on that model, including
> ones inside subqueries and `.count()`. `Label.Meta.ordering` is
> `('-date_created',)` and `date_created` is indexed (`db_index=True`) — that
> pairing is not an accident. Default ordering on an unindexed column is a
> classic source of slow pages.

---

## 5. Managers and QuerySets

### The manager is the door

`Model.objects` is a `Manager`. Replace it and you change what every piece of
code can say.

```python
class Project(models.Model):
    ...
    objects = ProjectManager()
```

`explorer/managers.py`:

```python
class ProjectManager(CustomQuerysetManager):
    def manifests(self): ...
    def system_manifests(self): ...
    def valid(self): ...
    def code(self): ...
    def review(self): ...
```

So a view writes `Project.objects.system_manifests()` instead of restating the
filter. This is the single highest-value habit in Django: **a named queryset is
a domain concept with a name.**

CMWEB's managers, and what they encode:

| Manager | Model | Notable methods |
| --- | --- | --- |
| `ProjectManager` | `Project` | `manifests()`, `system_manifests()`, `valid()`, `code()`, `review()` |
| `FilteredBranchManager` | `Branch` | `filtered()` — applies the include/exclude rules |
| `ManifestBranchManager` | `ManifestBranch` | `synced()`, `active_for_week()`, `watched()`, `roots()`, `latest_labels()` |
| `LabelManager` | `Label` | `visible()`, `versioned()`, `delta()`, `latest()`, `recommended()`, `rewound()` |
| `CommitManager` | `Commit` | filtering by cherry/revert/internal |
| `LabelComponentMembershipManager` | join model | `added()`, `removed()`, `changed()`, `by_path()` |

### QuerySets are lazy and chainable

```python
qs = Label.objects.versioned()             # no SQL yet
qs = qs.filter(status='OFFICIAL')          # still no SQL
qs = qs.order_by('-date_created')[:20]     # still no SQL
for label in qs:                           # SQL runs HERE
    ...
```

SQL is issued when the queryset is iterated, sliced with a step, `len()`-ed,
`bool()`-ed, pickled, or turned into a list. Anything else just builds the
query.

`LabelList.get_queryset()` in `explorer/views/labels.py` is a clean example of
building up conditionally without ever hitting the database until the template
iterates:

```python
labels = Label.objects.versioned().filter(
    manifest_branch__project__name=self.manifest)
query = get_object_query_from_request(self.request, 'name__istartswith')
labels = labels.filter(query)

if self.kwargs.get('series'):
    labels = labels.filter(series__name=self.kwargs.get('series'))
if self.kwargs.get('branch'):
    labels = labels.filter(manifest_branch__name=self.kwargs.get('branch'))
if self.kwargs.get('status'):
    labels = labels.filter(status=self.kwargs.get('status').upper())
```

### Lookups and spanning relationships

The double underscore is the ORM's whole query language:

```python
Label.objects.filter(manifest_branch__project__name='platform/manifest')
#                    ^^^^^^^^^^^^^^^ ^^^^^^^ ^^^^
#                    FK              FK      column     -> two JOINs

Label.objects.filter(name__istartswith='1.2')     # case-insensitive prefix
Label.objects.filter(date_created__gte=cutoff)    # >=
Label.objects.filter(status__in=['OFFICIAL', 'CUSTOMER'])
Label.objects.exclude(previous__isnull=True)
```

Common lookups: `exact`, `iexact`, `contains`, `icontains`, `startswith`,
`istartswith`, `in`, `gt`, `gte`, `lt`, `lte`, `isnull`, `range`, `year`,
`date`, `regex`.

### `Q` objects for OR / NOT

```python
from django.db.models import Q
Label.objects.filter(Q(status='OFFICIAL') | Q(status='CUSTOMER'))
Label.objects.filter(~Q(status='INTERNAL'))
```

CMWEB's `base.utils.http.get_object_query_from_request()` returns a `Q` object
built from GET parameters, which is why the view can just say
`labels.filter(query)` without knowing what the user searched for.

### Aggregation and annotation

```python
from django.db.models import Count, Max

Label.objects.aggregate(Max('date_created'))         # -> one dict
ManifestBranch.objects.annotate(n=Count('labels'))   # -> a column per row
```

`annotate` adds a computed column to each row of the result; `aggregate`
collapses the whole queryset to a single dict.

### The N+1 problem, and the two fixes

```python
for label in Label.objects.all()[:100]:
    print(label.manifest_branch.project.name)   # 200 extra queries!
```

| Fix | Use for | Mechanism |
| --- | --- | --- |
| `select_related('manifest_branch__project')` | FK / one-to-one, *forward* | One `JOIN`, one query |
| `prefetch_related('commits')` | M2M and reverse FK | A second query + Python-side join |

```python
Label.objects.select_related('manifest_branch__project').prefetch_related('commits')
```

This is the first thing to check when a CMWEB page is slow.

### `only()`, `defer()`, `values()`, `values_list()`

```python
Label.objects.values_list('name', flat=True)     # a flat list of strings, no model objects
Label.objects.only('name', 'date_created')       # model objects, fewer columns
```

`index_labels.py` uses this to avoid materialising models it does not need:

```python
manifests = query.values_list('name', flat=True)
```

---

## 6. Model methods: where domain rules live

Four kinds, and they are not interchangeable.

```python
class Label(models.Model):
    ...

    def __str__(self):                       # 1. representation
        return u'%s %s' % (self.manifest_branch.project.name, self.name)

    def get_absolute_url(self):              # 2. canonical URL, used by admin + templates
        from explorer.templatetags.explorerutils import label_url
        return label_url(self, 'detail')

    def get_previous(self):                  # 3. a domain rule
        if not self.previous:
            return self.seek_previous()
        return self.previous

    def save(self, update_counts=False, label_completion=False, **kwargs):
        ...                                  # 4. lifecycle hook
        super().save(**kwargs)
```

### `@property` vs method

A `@property` is called without parentheses from Python *and* from templates.
A plain method is called without parentheses from templates but *with* them
from Python. Django templates cannot pass arguments, so:

- zero-argument method or property -> callable from a template
- method with arguments -> needs a template tag or filter

That is why `explorer/templatetags/explorerutils.py` exists.

### Overriding `save()`

Two real examples:

```python
class ExcludedBranchRule(models.Model):
    def save(self, *args, **kwargs):
        """Set created date field before saving new objects."""
        if not self.id:
            self.created_on = timezone.now()
        return super(ExcludedBranchRule, self).save(*args, **kwargs)
```

```python
class Label(models.Model):
    def save(self, update_counts=False, label_completion=False, **kwargs):
        ...
```

Note the second signature: extra *keyword-only-ish* arguments added to `save()`.
This is legal but has a sharp edge — **`save()` is not called by bulk
operations**. `QuerySet.update()`, `bulk_create()`, `bulk_update()` and
`loaddata` all bypass it. That is exactly why loading CMWEB's 21,929-row
fixture with signals attached is both slow and semantically wrong: the fixture
already contains post-save results.

---

## 7. Model inheritance: three kinds

| Kind | Declared by | Tables produced | Use when |
| --- | --- | --- | --- |
| **Abstract base** | `class Meta: abstract = True` | One per child | Sharing field definitions |
| **Multi-table (MTI)** | Subclassing a concrete model | One per class, linked by an implicit one-to-one | The parent is itself a real thing |
| **Proxy** | `class Meta: proxy = True` | None (reuses parent's) | Different default manager/ordering only |

CMWEB uses **all three**.

### MTI: `ManifestBranch(Branch)`

```python
class Branch(models.Model):
    name = models.CharField(max_length=200)
    project = models.ForeignKey(Project, on_delete=models.CASCADE,
                                related_name='branches')


class ManifestBranch(Branch):
    review_label = models.CharField(max_length=100, default='code-review')
    latest_label = models.OneToOneField('Label', ...)
    parent = models.ForeignKey('self', ...)
    ...
```

Two tables: `explorer_branch` and `explorer_manifestbranch`, joined on
`branch_ptr_id`. Consequences you must know:

- Every `ManifestBranch` query does an implicit `JOIN`.
- `Branch.objects.all()` includes rows that are really manifest branches;
  `branch.manifestbranch` reaches the child (raising if there isn't one).
- Saving a `ManifestBranch` writes to **two** tables.

This is the right modelling choice here — a manifest branch *is* a git branch,
with extra facts — but MTI is the expensive form of inheritance, and it is the
reason a few branch pages carry extra joins.

### Abstract base: `request.Request`

`cmweb-app/request/models.py:60`:

```python
class Request(ConcurrentTransitionMixin, models.Model):
    state = FSMField(default='NEW', protected=True, null=False, db_index=True)
    arch_state = FSMField(default='NEW', protected=True, null=False, ...)
    swp_state = FSMField(default='NEW', protected=True, null=False, ...)

    class Meta:
        abstract = True
```

`BranchRequest` and `RepositoryRequest` each get their own table with all those
columns copied in. No join, no shared table, no way to query "all requests" in
one go — the trade-off you accept for abstract bases.

---

## 8. Two CMWEB-specific patterns to respect

### A. Denormalised counters

```python
# COUNT(*) caching for templates
components_count = models.IntegerField(null=True, editable=False)
commits_count = models.IntegerField(null=True, editable=False)
member_commits_count = models.IntegerField(null=True, editable=False)
app_commits_count = models.IntegerField(null=True, editable=False)
all_commits_count = models.IntegerField(null=True, editable=False)
issues_count = models.IntegerField(null=True, editable=False)
all_issues_count = models.IntegerField(null=True, editable=False)
decoupled_apps_count = models.IntegerField(null=True, editable=False)
```

These are **not** maintained by signals. They are recomputed by
`Label.update_counts()`, which the indexing pipeline calls. If you add a commit
to a label by hand in the shell, `commits_count` will be wrong until something
recomputes it.

**Rule:** when you write new indexing code that changes a label's membership,
call `update_counts()`. When you read a count in a template, use the
denormalised field. When you need a guaranteed-correct count in a management
command, use `.count()`.

### B. Indexing status flags

```python
components_incomplete = models.BooleanField(default=True)
commits_incomplete = models.BooleanField(default=True)
sublabels_incomplete = models.BooleanField(default=True)
decoupled_incomplete = models.BooleanField(default=True)
incomplete = models.BooleanField(default=True)
```

These drive two things: whether the indexer will pick a label up again, and
whether the UI shows it as partial. They default to `True` — a freshly created
`Label` is assumed *not* fully indexed until something proves otherwise. Do not
flip them to `False` unless the corresponding data really is complete.

### C. `apps.get_model()` instead of imports

Look at the top of any CMWEB view or management command:

```python
from django.apps import apps

Parameter = apps.get_model('base', 'parameter')
Label = apps.get_model('explorer', 'label')
ManifestBranch = apps.get_model('explorer', 'manifestbranch')
```

instead of `from explorer.models import Label`. The reason is circular imports:
with 21 apps that reference each other, module-level model imports create
import cycles. `apps.get_model()` resolves lazily from the app registry, after
everything is loaded.

**Follow this in new indexing and view code.** It is the house style and it
exists for a concrete reason.

### D. Writes go to a named alias

`cmweb-app/explorer/management/indexing.py:56` and four other places:

```python
using = getattr(settings, 'DATABASE_ALIAS_FOR_WRITE', DEFAULT_DB_ALIAS)
...
obj.save(using=using)
```

Production once fronted a read replica (`cmweb-project/cmweb/routers.py`,
`MasterSlaveRouter`, currently disabled). The indexing pipeline still writes
through the alias rather than the default one. Chapter 07 covers multi-database
routing.

---

## 9. Signals

A publish/subscribe hook on model lifecycle events.

```python
from django.db.models.signals import post_save
from django.dispatch import receiver


@receiver(post_save, sender=Label)
def on_label_saved(sender, instance, created, **kwargs):
    ...
```

Built-in signals: `pre_save`, `post_save`, `pre_delete`, `post_delete`,
`m2m_changed`, `pre_migrate`, `post_migrate`.

CMWEB also defines a custom one, `explorer/signals.py`:

```python
import django.dispatch

label_complete = django.dispatch.Signal("instance")
```

### When *not* to use signals

Signals make control flow invisible. Prefer an explicit method call when the
caller is in your own codebase. Use a signal when the *sender* must not know
about the *receiver* — cross-app decoupling, or reacting to third-party models.

And be aware of the escape hatch: `local-cmweb/scripts/load_sample_data.py`
detaches every model signal for the duration of the fixture load, because the
fixture is already-indexed data and replaying it would re-fire indexing
(reaching JIRA and M+ per issue, and writing a django-reversion revision per
row). Load time drops from 10+ minutes to about 90 seconds. That is the cost of
signals, measured.

---

## 10. Transactions

```python
from django.db import transaction

with transaction.atomic():
    label.save()
    label.commits.add(*commits)
```

Everything inside the block commits together or not at all. By default Django
runs in autocommit — each `save()` is its own transaction. Wrap multi-step
writes in `atomic()` when a half-applied result would be wrong.

`ConcurrentTransitionMixin` (used by `request.Request` with `django-fsm`) is a
related idea at the application level: optimistic locking, so two people cannot
advance the same request through a state machine simultaneously.

---

## 11. Try it

```powershell
cd local-cmweb
.venv\Scripts\python.exe manage.py shell
```

**A. See the SQL a queryset produces:**

```python
from explorer.models import Label
qs = Label.objects.versioned().filter(status='OFFICIAL')
print(qs.query)                     # the SQL, without running it
```

**B. Count the queries a loop costs:**

```python
from django.db import connection, reset_queries
from django.conf import settings
settings.DEBUG = True               # query logging only happens when DEBUG

reset_queries()
for lb in Label.objects.all()[:10]:
    _ = lb.manifest_branch.project.name
print(len(connection.queries))      # N+1

reset_queries()
qs = Label.objects.select_related('manifest_branch__project')[:10]
for lb in qs:
    _ = lb.manifest_branch.project.name
print(len(connection.queries))      # 1
```

**C. Prove the denormalised counter can drift:**

```python
lb = Label.objects.first()
lb.commits_count, lb.commits.count()      # normally equal
```

**D. Inspect the multi-table inheritance:**

```python
from explorer.models import Branch, ManifestBranch
mb = ManifestBranch.objects.first()
print(ManifestBranch.objects.filter(pk=mb.pk).query)   # note the JOIN
b = Branch.objects.get(pk=mb.pk)
b.manifestbranch                                        # reach the child
```

**E. Read a manager and use it:**

```python
from explorer.models import Project
Project.objects.manifests().values_list('name', flat=True)
Project.objects.valid().count()
```

**F. Look at the through model:**

```python
from explorer.models import LabelComponentMembership as LCM
m = LCM.objects.first()
m.label, m.component, m.previous()
```

---

## 12. Check yourself

1. What is the difference between `null=True` and `blank=True`? When would you
   use both?
2. Why does `Label.date_created` use `default=timezone.now` rather than
   `auto_now_add=True`?
3. What SQL does `Label.objects.filter(manifest_branch__project__name='x')`
   produce, roughly?
4. When is SQL actually sent for a queryset?
5. Which of `select_related` and `prefetch_related` works on a `ManyToManyField`,
   and why can't the other one?
6. Name three operations that write to the database *without* calling
   `Model.save()`.
7. `ManifestBranch` inherits from `Branch`. How many tables, and what is the
   cost of every `ManifestBranch` query?
8. Why does `sublabels` need `symmetrical=False`?
9. `Label.commits_count` exists alongside the `commits` M2M. What maintains it,
   and what happens if you add a commit in the shell?
10. Why does CMWEB use `apps.get_model('explorer', 'label')` instead of
    `from explorer.models import Label`?
11. `Label.incomplete` defaults to `True`. Why is that the safe default?
12. Give one reason to prefer an explicit method call over a `post_save`
    signal, and one reason to prefer the signal.
