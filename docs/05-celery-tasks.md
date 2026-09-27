# 5. Celery and long-running tasks

*Running work outside the request/response cycle.*

---

## Part A — The concept

### The problem

A web request should finish in well under a second. But some work takes minutes:
indexing a build, creating repositories in Gerrit, sending a hundred emails. You
cannot do it inside the view — the browser times out, and the WSGI worker is
blocked the whole time.

The answer is a **task queue**:

```
view → puts a message on a queue → returns immediately
                ↓
        a separate WORKER process picks it up and does the work
                ↓
        the result is stored somewhere the web app can read
```

### Celery's pieces

| Piece | What it is | In CMWEB |
| --- | --- | --- |
| **Task** | A Python function that can run in the background | `@shared_task` functions in `<app>/tasks.py` |
| **Broker** | The message queue | Amazon **SQS** |
| **Worker** | A process that consumes and executes | Separate process on the server |
| **Result backend** | Where return values and status go | The **database**, via `django_celery_results` |

### Defining and calling

```python
from celery import shared_task

@shared_task
def add(x, y):
    """Add two numbers."""
    return x + y
```

Calling it normally (`add(2, 3)`) just runs it inline. To queue it:

```python
add.delay(2, 3)                              # shorthand
add.apply_async(kwargs={'x': 2, 'y': 3},     # full form
                countdown=10)                # wait 10s first
```

Both return an `AsyncResult` carrying a `task_id` you can poll.

### `@shared_task` vs `@app.task`

`@shared_task` does not bind the task to a specific Celery app instance, which
is what you want in a Django app that might be imported before the Celery app
exists. CMWEB uses `@shared_task` exclusively.

### Arguments must be serializable

Task arguments travel over the network as JSON. **You cannot pass a Django model
instance.** Pass the primary key and re-fetch inside the task. CMWEB does this
everywhere:

```python
def create_repositories(pk, user_pk):     # not (request_obj, user_obj)
```

This is also more correct: by the time the worker runs, the database row may
have changed, and you want the current state.

---

## Part B — CMWEB's configuration

`cmweb-project/cmweb/celery.py` is the whole setup:

```python
import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'cmweb.settings_deployed')

app = Celery('cmweb')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()
```

Three things to notice:

1. **`settings_deployed`** — the symlink Ansible creates. Celery workers will
   not start without it, even though `manage.py` defaults to `cmweb.settings`.
2. **`namespace='CELERY'`** — Celery settings are the `CELERY_*` names in
   Django settings.
3. **`autodiscover_tasks()`** — finds `tasks.py` in every installed app
   automatically.

### The setting that changes everything in dev

```python
CELERY_TASK_ALWAYS_EAGER = True     # in cmweb/settings.py
```

When eager, `.delay()` and `.apply_async()` **do not queue anything** — the task
runs immediately, synchronously, in the calling process, and returns an
`EagerResult`.

So in development there is no broker, no worker, nothing to start. But it also
means:

- A task that blocks for 30 seconds blocks your page for 30 seconds.
- Failures surface as exceptions in the request rather than as a failed task.
- Race conditions and serialization bugs are invisible until production.

Only the deployed settings override it. **A task that works in dev can behave
differently in production purely because of this flag.**

---

## Part C — The task inventory

Nine tasks:

| Task | App | Purpose |
| --- | --- | --- |
| `get_or_create_delta_label` | explorer | Build a delta between two arbitrary builds — the heavy one |
| `process_label_completion` | explorer | Fire the `label_complete` signal |
| `send_deltalabel_complete_email` | explorer | Notify the requester |
| `create_repositories` | request | Call Gerrit to actually create repos |
| `notify_dashboards` | dashboards | Fan activity out to subscribers |
| `send_notification_email` | dashboards | Per-notification mail |
| `analyze_zeitgeist_entry` | historian | Time-series analysis |
| `run_command` | base | Generic management-command wrapper |

The simplest, in full:

```python
"""Celery tasks common to all apps."""

from celery import shared_task
from django.core.management import call_command


@shared_task
def run_command(name, *args, **kwargs):
    """Run a management command and return status."""
    return call_command(name, *args, **kwargs)
```

That single task is how the UI triggers any management command
asynchronously.

---

## Part D — The two decorators

```python
@shared_task
@json_result
def create_repositories(pk, user_pk):
    ...
    return r          # a RepositoryRequest instance
```

`backend.tasks.json_result` serialises a returned Django object so it survives
the result backend:

```python
def json_result(func):
    """Serialize a single Django object returned from a task."""
    @wraps(func)
    def _inner(*args, **kwargs):
        return serialize_anything(func(*args, **kwargs), bare=True)
    return _inner
```

**Order matters** — `@shared_task` must be outermost. Decorators apply bottom-up,
so `json_result` wraps the function and `shared_task` registers the wrapped
version.

---

## Part E — Error handling

Every task uses the same shape:

```python
@shared_task
def process_label_completion(pk):
    """Return label after completion."""
    from .models import Label
    try:
        label = Label.objects.get(pk=pk)
        label_complete.send(sender=Label, instance=label)
    except Exception as e:
        process_label_completion.retry(exc=e, countdown=10)
    return label
```

`.retry(exc=e, countdown=10)` re-queues the task after ten seconds. Uniform
across the codebase; no task sets a custom `max_retries`, so Celery's default of
3 applies. After that the task is marked failed.

Note the **import inside the function** — the same circular-import avoidance you
see elsewhere. `tasks.py` is imported very early (via `__init__.py` re-exports),
often before models are ready.

---

## Part F — The user-facing job pipeline

This is how the UI runs something slow and shows progress. Worth following end
to end.

### 1. The browser POSTs

```
POST /backend/tasks/apply/<task_name>/
```

### 2. The view queues it

`backend/views.py`:

```python
def backend_task_apply_view(request, task_name):
    """Call celery backend tasks and return response."""
    try:
        task = tasks[task_name]           # Celery's task registry
    except KeyError:
        raise Http404('apply: no such task')
    kwargs = request.POST if request.method == 'POST' else request.GET
    kwargs = {k: v for k, v in kwargs.items()}
    result = task.apply_async(kwargs=kwargs)
    if isinstance(result, EagerResult):
        TaskResult.objects.store_result(
            'json', 'utf8', result.task_id, result.result, result.status,
            task_name=task_name, task_kwargs=kwargs)
    response = {'ok': 'true', 'task_id': result.task_id}
    return HttpResponse(json.dumps(response),
                        content_type='application/json')
```

The `EagerResult` branch is the dev accommodation: eager tasks bypass the result
backend, so the view writes the row itself and the polling endpoint still works.

> This is why `task_name` matters, and why the `__init__.py` re-exports exist —
> the lookup is by the registered name.

### 3. The requester is recorded

```python
def record_task_requester(view):
    """Return the requester for the apply view."""
    @wraps(view)
    def _inner(request, *args, **kwargs):
        ret = view(request, *args, **kwargs)
        task_id = json.loads(ret.content.decode('utf-8')).get('task_id', None)
        if task_id and request.user.is_authenticated and request.user.profile:
            UserTaskRequest.objects.create(user=request.user, task_id=task_id)
        return ret
    return _inner
```

A decorator wrapping the view, applied in the URLconf. `UserTaskRequest` is the
entire model — two fields:

```python
class UserTaskRequest(models.Model):
    """Records a requested task for a user."""

    user = models.ForeignKey('auth.User', on_delete=models.CASCADE)
    task_id = models.SlugField(max_length=36, unique=True)
```

### 4. The browser polls

```
GET /backend/tasks/<task_id>/status
```

returns `{"task": {"id": …, "status": …, "result": …}}` read from `TaskResult`.

### 5. Progress reporting

Tasks push progress into the result backend as they go:

```python
get_or_create_delta_label.backend.mark_as_started(
    get_or_create_delta_label.request.id,
    progress='Indexing repositories')
```

`self.request.id` is Celery's per-execution context. Note the guard
`if get_or_create_delta_label.request.id:` — when eager, there is no request id,
so the same function serves both paths.

### 6. Apache must not cache it

The vhost has explicit `no-store` blocks:

```apache
<LocationMatch "^/backend/tasks/.*/status$">
    Header Set Cache-Control "max-age=0, no-store, no-cache, must-revalidate"
    ...
```

Without them, production's ten-minute page cache would freeze the progress
display at the first response. See
[07-apache-deployment.md](07-apache-deployment.md).

---

## Part G — Signals, and why saving a Label is expensive

Django **signals** are an in-process publish/subscribe mechanism — a sender
emits, and any number of receivers react. `explorer/signals.py` defines one:

```python
label_complete = django.dispatch.Signal("instance")
```

The chain when a build finishes indexing:

```
Label.save()                                     explorer/models.py:1417
   └─ process_label_completion.apply_async(...)  a Celery task
        └─ label_complete.send(...)              the signal
             └─ vendorsync/__init__.py handlers  ~400 lines
                  ├─ handle_android_release()
                  ├─ index_about_html()
                  ├─ handle_amss_release()
                  ├─ handle_au_release()
                  ├─ handle_build_au_release()   ← calls Gerrit REST
                  └─ handle_mediatek_release()   ← calls Gerrit REST
```

**So saving a `Label` can trigger network I/O and a cascade of writes.**

Two practical consequences:

1. In dev (eager), `label.save()` runs that entire chain synchronously inside
   your request.
2. Bulk-loading already-indexed data re-fires the whole chain per row, which is
   both very slow and semantically wrong — the results are already in the data.
   That is precisely why `local-cmweb/scripts/load_sample_data.py` mutes model
   signals during `loaddata`, taking the fixture load from 10+ minutes to ~85
   seconds.

---

## Part H — Running workers

In production, workers are separate processes:

```bash
cd cmweb-project
DJANGO_SETTINGS_MODULE=cmweb.settings_deployed \
  ../ENV/bin/celery -A cmweb worker -l info
```

Locally there is no broker and nothing to run — eager mode covers it.

**Adding a new task** means the worker must be **restarted** to pick it up.
Workers import task modules at startup; a new or renamed task is invisible to a
running worker.

---

## Writing a task

```python
"""Celery tasks for myapp."""

from __future__ import absolute_import

from celery import shared_task

from backend.tasks import json_result


@shared_task
@json_result
def refresh_thing(pk):
    """Refresh a `Thing` and return it."""
    from .models import Thing          # import inside: avoid circular imports
    try:
        thing = Thing.objects.get(pk=pk)
        thing.refresh()
        thing.save()
        return thing
    except Exception as e:
        refresh_thing.retry(exc=e, countdown=10)
```

And re-export it so autodiscovery registers the name, in `myapp/__init__.py`:

```python
"""My app."""

from __future__ import absolute_import

from .tasks import refresh_thing

__all__ = ['refresh_thing']
```

```
[ ] @shared_task outermost, @json_result under it
[ ] arguments are pks/strings, never model instances
[ ] models imported inside the function
[ ] retry(exc=e, countdown=10) on failure
[ ] re-exported in __init__.py if triggered by name
[ ] worker restarted after adding it
[ ] tested with CELERY_TASK_ALWAYS_EAGER off, if behaviour depends on async
```

**Next:** [06-migrations.md](06-migrations.md)
