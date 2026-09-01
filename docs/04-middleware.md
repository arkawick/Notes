# 4. Middleware

*The layer every request passes through, and the two CMWEB adds.*

---

## Part A — The Django concept

### What middleware is

Middleware wraps the view. Every request passes through the whole stack on the
way in, and every response passes back through it on the way out:

```
request  →  MW1 → MW2 → MW3 → VIEW
response ←  MW1 ← MW2 ← MW3 ←
```

Use it for anything that must apply to *every* request: authentication, session
handling, CSRF protection, compression, caching, custom headers.

### The modern form

A middleware is a callable that takes `get_response` and returns a callable:

```python
class MyMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # ---- runs BEFORE the view
        response = self.get_response(request)
        # ---- runs AFTER the view
        return response
```

`self.get_response(request)` calls the next middleware down, eventually the
view. Code before it sees the request; code after it sees the response.

`__init__` runs **once at startup**, not per request — a good place for setup,
a bad place for per-request state.

### Extra hooks

Beyond `__call__`, Django calls these if defined:

| Hook | When |
| --- | --- |
| `process_view(request, view_func, view_args, view_kwargs)` | After URL resolution, before the view. Can see the matched view and its kwargs. |
| `process_exception(request, exception)` | The view raised |
| `process_template_response(request, response)` | The response has a `render()` method |

`process_view` is the interesting one: it runs **after** the URLconf has matched,
so it knows which view will handle the request and with what arguments — unlike
`__call__`, which only sees the raw path.

**Returning a response from any hook short-circuits the chain** — the view never
runs. That is how access control middleware works.

### Order matters

`MIDDLEWARE` is a list, and it is a nesting order, not a sequence. The first
entry is outermost: it sees the request first and the response last.

Dependencies follow from this. `AuthenticationMiddleware` needs
`SessionMiddleware` above it, because it reads the user id out of the session.
Get the order wrong and you get confusing failures rather than clear errors.

---

## Part B — CMWEB's stack

From `cmweb-project/cmweb/settings.py`:

| # | Middleware | Origin | Role |
| --- | --- | --- | --- |
| 1 | `CommonMiddleware` | Django | URL normalisation, `APPEND_SLASH` |
| 2 | `SessionMiddleware` | Django | Loads the session (cached in prod) |
| 3 | `SessionTimeoutMiddleware` | 3rd party | Expires idle sessions after `SESSION_EXPIRE_SECONDS` (3600) |
| 4 | `CsrfViewMiddleware` | Django | CSRF protection |
| 5 | `AuthenticationMiddleware` | Django | Puts `request.user` in place |
| 6 | `RemoteUserMiddleware` | Django | Trusts `REMOTE_USER` from Apache |
| 7 | `MessageMiddleware` | Django | Flash messages |
| 8 | `PaginationMiddleware` | 3rd party | Pagination helper |
| 9 | **`PjaxVersionMiddleware`** | **CMWEB** | Stamps a version header |
| 10 | **`PermissionCheckMiddleware`** | **CMWEB** | Site-wide access gate |

`settings_prod.py` wraps the list with caching and compression:

```python
MIDDLEWARE = \
    ['django.middleware.cache.UpdateCacheMiddleware'] + \
    ['django.middleware.gzip.GZipMiddleware'] + \
    list(MIDDLEWARE) + \
    ['django.middleware.cache.FetchFromCacheMiddleware']
```

That is Django's site-wide cache: `FetchFromCache` (innermost, checked last on
the way in) serves a cached page if there is one; `UpdateCache` (outermost)
stores the rendered response. `CACHE_MIDDLEWARE_SECONDS = 600` — **pages are
cached for ten minutes in production**, which explains a lot of "why is my
change not showing" confusion.

### `RemoteUserMiddleware` and the Apache relationship

This is central to how CMWEB authenticates, and it surprises people.

Apache performs LDAP basic authentication for the entire site and passes the
authenticated username to Django in the `REMOTE_USER` environment variable.
`RemoteUserMiddleware` reads it and logs that user in.

**So in production, every request arrives already authenticated.** Django's own
LDAP backends (`users.auth.AuthLDAPBackend`) exist for fetching profile data and
for paths that bypass Apache auth.

The consequence for local development: with no Apache in front, `REMOTE_USER` is
never set, so `RemoteUserMiddleware` sees an anonymous request — and because it
logs out any user not present in `REMOTE_USER`, leaving it enabled locally logs
you out on every request. `local-cmweb` removes it for exactly this reason.

---

## Part C — `PjaxVersionMiddleware`

The entire class:

```python
class PjaxVersionMiddleware(object):
    """Set the X-PJAX-Version header."""

    def __init__(self, get_response):
        """Init module."""
        self.get_response = get_response

    def __call__(self, request):
        """Return X-PJAX version."""
        version = settings.GLOBALS.get('CM_WEB_VERSION', 'unknown')
        md5 = settings.GLOBALS.get('STATIC_MD5', 'unknown')
        response = self.get_response(request)
        response['X-PJAX-Version'] = '{}-{}'.format(version, md5)
        return response
```

### Why it exists

PJAX loads only the content region of a page and swaps it into the current DOM,
so the browser keeps the JavaScript it loaded at first page load. If the server
deploys new JS, a long-lived tab keeps running the old code against new markup.

The PJAX client watches `X-PJAX-Version`. When the value changes mid-session, it
stops doing partial swaps and performs a **full page reload**, picking up the
new assets.

### Where the value comes from

Two halves:

- `CM_WEB_VERSION` — from `git describe` in `settings.py`
- `STATIC_MD5` — hashes read out of `static/compressed/manifest.json`, the
  django-compressor output:

```python
with open(join(STATIC_ROOT, 'compressed', 'manifest.json')) as f:
    ...
    GLOBALS['STATIC_MD5'] = '-'.join(hashes)
```

So **running `make static` changes the header and invalidates every client's
PJAX session.** That is intentional. It also means a deploy that skips
`make static` can leave clients running stale JavaScript against new templates —
worth knowing when a deploy behaves oddly in browsers but fine in curl.

Note this is read at import time, so a recompression requires a process restart
to take effect.

---

## Part D — `PermissionCheckMiddleware`

The site-wide access gate, and the one you must understand before adding any
public endpoint. It is the **only `process_view` hook in the codebase**.

### The lists

```python
EXEMPT_URLS = ['accounts/', 'request/']

NO_AUTH_URLS = ['.+/trigger-config/?$', '.+/xml(/all)?/?$',
                'builds/(.+/)?rss/?$', 'projects/.+/rss/?$',
                'activity/rss/?$', 'rpc/?$', 'api/(?!a/).*$',
                'register$', 'access-denied$']
```

### The logic

1. **Exempt paths** (`accounts/`, `request/`) → allowed unconditionally. This is
   how people outside the CM team file branch and repository requests without
   access to the rest of CMWEB.

2. **HTTP Basic header present** → base64-decode it, take the username, look it
   up in `auth_user`:

   ```python
   auth_key = re.sub('Basic ', '', request.META.get('HTTP_AUTHORIZATION'))
   username = codecs.decode(auth_key.encode(), 'base64').decode().split(':')
   ...
   request_user = User.objects.filter(username=username)
   ```

   > **The password is never checked here.** This is only safe because Apache
   > has already authenticated the request against LDAP. It is a strong reason
   > never to expose the app without that front end — running it directly on a
   > public port would let anyone assume any identity by sending a Basic header.

3. **Anonymous users** → allowed only if the path matches `NO_AUTH_URLS`
   (feeds, `rpc/`, `api/`, `register`, `access-denied`). Otherwise redirected to
   `/access-denied`.

4. **Authenticated users** → require the `users.view_all_pages` permission.
   Without it, redirected to the branch-request list.

### Two details worth knowing

**`api/(?!a/).*$`** is a negative lookahead: it matches `/api/…` but *not*
`/api/a/…`. The root URLconf mounts the same API URLconf twice:

```python
path(r'api/',   include('api.urls')),
path(r'api/a/', include(('api.urls', 'api'), 'apia')),
```

`/api/` is the anonymous read-only namespace; `/api/a/` requires login. One
regex character implements that split.

**The `inplace` special case**: if the *referer* matches an exempt or no-auth
pattern and `view_kwargs['inplace'] == 'inplace'`, the request is allowed. This
lets in-place editing widgets work on otherwise-public request pages — and it is
only possible because `process_view` can see `view_kwargs`, which `__call__`
cannot.

### Adding a public endpoint

**Three edits, not one:**

1. The URLconf — add the route.
2. `NO_AUTH_URLS` in `cmweb/middleware.py` — let Django's gate through.
3. The Apache vhost — add a `Require all granted` block, or Apache's LDAP auth
   rejects the request before Django ever sees it.

Miss any and the endpoint is unreachable, with a different symptom each time.
See [07-apache-deployment.md](07-apache-deployment.md).

---

## Part E — Locally

`local-cmweb` changes two things, both in `config/settings_local.py`:

**`RemoteUserMiddleware` removed** — no Apache means no `REMOTE_USER`, and
leaving it in logs you out every request.

**`PermissionCheckMiddleware` replaced** by
`config/middleware_local.py::LocalPermissionMiddleware`, which signs every
request in as a local superuser:

```python
def __call__(self, request):
    """Authenticate the request, then hand off down the chain."""
    if AUTOLOGIN and not request.user.is_authenticated:
        user = self._local_user()
        if user is not None:
            login(request, user, backend=BACKEND)
    return self.get_response(request)
```

This reproduces production's *assumption* — that requests arrive
authenticated — rather than its mechanism. Without it the site is unbrowsable,
because nearly every view sits behind `users.view_all_pages`.

Set `CMWEB_LOCAL_AUTOLOGIN=0` (or `.\run.ps1 -Anonymous`) to disable it and see
production's behaviour for an unprivileged user: redirected to the branch-request
list.

---

## Writing middleware

```python
"""Custom middleware for myapp."""

import logging


class TimingMiddleware(object):
    """Log how long each request took."""

    def __init__(self, get_response):
        """Store the next handler in the chain."""
        self.get_response = get_response

    def __call__(self, request):
        """Time the request and log the result."""
        import time
        started = time.time()
        response = self.get_response(request)
        logging.info('%s took %.3fs', request.path, time.time() - started)
        return response
```

Register it in `MIDDLEWARE`, minding placement:

```
[ ] added to MIDDLEWARE at the right depth
[ ] __init__ takes get_response and stores it
[ ] __call__ calls self.get_response(request) exactly once
[ ] returning a response early is intentional (it skips the view)
[ ] docstrings on class and methods
[ ] considered the prod cache wrapper — a cached page skips inner middleware
```

That last point is subtle: with `FetchFromCacheMiddleware` active, a cache hit
returns before inner middleware runs. Middleware that must see *every* request
belongs above the cache layer.

**Next:** [05-celery-tasks.md](05-celery-tasks.md)
