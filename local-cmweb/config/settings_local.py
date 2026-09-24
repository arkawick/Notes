"""Standalone Django settings for running CMWEB locally against sample data.

This module deliberately does **not** import ``cmweb.settings``. Doing so would
run a ``git describe`` subprocess against a repository that is not present, and
would pull in the OpenSearch, Celery/SQS and LDAP configuration that has no
local equivalent. Everything CMWEB actually reads is redefined here instead, so
neither cmweb-project nor cmweb-app is modified in any way.

Differences from the real ``cmweb.settings`` are marked LOCAL: below.
"""

import os
import sys
from os.path import abspath, dirname, join

# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------
# LOCAL: the real settings derive these from a deployed /srv/www layout with
# cmweb-app checked out at cmweb-project/apps. Here the three repositories sit
# side by side and are wired together on sys.path instead of being moved.
LOCAL_ROOT = dirname(dirname(abspath(__file__)))        # local-cmweb/
WORKSPACE = dirname(LOCAL_ROOT)                         # the folder above it
PROJECT_REPO = join(WORKSPACE, 'cmweb-project')
APP_REPO = join(WORKSPACE, 'cmweb-app')
STUBS = join(LOCAL_ROOT, 'stubs')
VAR = join(LOCAL_ROOT, 'var')

for path in (STUBS, APP_REPO, PROJECT_REPO):
    if path not in sys.path:
        sys.path.insert(0, path)

for directory in (VAR, join(VAR, 'log'), join(VAR, 'cache'),
                  join(VAR, 'repository'), join(VAR, 'static')):
    os.makedirs(directory, exist_ok=True)

# Register 'cmweb' as a bare package whose __init__.py is never executed.
#
# CMWEB's middleware, context processors and JSON serializer live in
# cmweb-project/cmweb/ and are referenced below by dotted path. Importing that
# package normally runs cmweb/__init__.py, which imports cmweb.celery and
# cmweb.settings -- and cmweb/settings.py shells out to `git describe`, creates
# directories next to the repository, and dies with NameError on OPENSEARCH_HOST
# because cmweb/secure.py is (correctly) not committed.
#
# Binding the package with an explicit __path__ lets Python find the submodules
# while skipping __init__.py entirely. None of the three modules we use imports
# anything from the cmweb package itself, so nothing is lost.
import types  # noqa: E402

if 'cmweb' not in sys.modules:
    _cmweb_pkg = types.ModuleType('cmweb')
    _cmweb_pkg.__path__ = [join(PROJECT_REPO, 'cmweb')]
    sys.modules['cmweb'] = _cmweb_pkg

# django-tagging 0.5.0 predates the removal of smart_text. The real settings
# apply the same shim; it must run before any app imports tagging.
import django  # noqa: E402
from django.utils.encoding import smart_str  # noqa: E402
django.utils.encoding.smart_text = smart_str

# --------------------------------------------------------------------------
# GLOBALS -- CMWEB's own configuration dict, read all over the codebase
# --------------------------------------------------------------------------
GLOBALS = {}
# Must stay 'dev': explorer migration 0037 guards a PostgreSQL-only
# "ALTER COLUMN ... TYPE bigint" behind this exact value, because SQLite cannot
# alter column types. Any other value makes `migrate` fail on SQLite.
GLOBALS['CM_WEB_ENVIRONMENT'] = 'dev'
GLOBALS['CM_WEB_NAME'] = 'CMWEB Local'
GLOBALS['CM_WEB_SIDEBAR_COLOR'] = '#3d7c47'
GLOBALS['CM_WEB_RELEASE'] = 'local'
GLOBALS['CM_WEB_VERSION'] = 'local-sample-data'

GLOBALS['PATH_PROJECT'] = join(PROJECT_REPO, 'cmweb')
GLOBALS['PATH_SITE'] = PROJECT_REPO
GLOBALS['PATH_ROOT'] = VAR
GLOBALS['PATH_REPOSITORY'] = join(VAR, 'repository')
GLOBALS['PATH_LABEL_CACHE'] = join(VAR, 'cache')
GLOBALS['PATH_VAR'] = VAR
GLOBALS['PATH_LOG'] = join(VAR, 'log')

# Gerrit project names of the manifests. Kept identical to the real settings --
# the sample data references them, and explorer/constants.py builds
# LABEL_COMPONENT_MAP out of them.
GLOBALS['PLATFORM_MANIFEST'] = 'platform/manifest'
GLOBALS['QSSI_MANIFEST'] = 'platform/qssimanifest'
GLOBALS['VENDOR_MANIFEST'] = 'platform/targetmanifest'
GLOBALS['MSSI_MANIFEST'] = 'platform/mssimanifest'
GLOBALS['MTK_VENDOR_MANIFEST'] = 'platform/vendormanifest'
GLOBALS['AMSS_MANIFEST'] = 'platform/amssmanifest'
GLOBALS['SYSTEM_MANIFEST'] = 'platform/systemmanifest'
GLOBALS['COMPOSITION_MANIFEST'] = 'platform/compositionmanifest'
GLOBALS['PATH_PLATFORM_MANIFEST'] = join(GLOBALS['PATH_REPOSITORY'],
                                         'platform', 'manifest.git')
GLOBALS['DECOUPLED_APPS'] = 'platform/vendor/semc/build/decoupled-apps'
GLOBALS['DECOUPLED_MANIFEST'] = 'platform/applicationmanifest'
GLOBALS['DECOUPLED_DELIVERIES'] = ['vendor/semc/build/decoupled-deliveries/',
                                   'vendor/semc/build/post-config']
GLOBALS['INSTALLABLE_APPS'] = 'platform/vendor/semc/build/installable-apps'
GLOBALS['BOOT_PACKAGES'] = 'platform/vendor/semc/build/boot-packages'
GLOBALS['PLD_PACKAGES'] = 'platform/vendor/semc/build/pld-packages'
GLOBALS['EXTERNAL_PACKAGES'] = 'semctools/external-packages'
GLOBALS['COMPOSITION_CONFIG'] = 'platform/vendor/semc/build/composition-config'

# LOCAL: unreachable hosts. Nothing should contact them; they are set to
# .invalid so an accidental call fails fast and obviously.
GLOBALS['GERRIT_SERVER'] = 'gerrit.local.invalid'
GLOBALS['GIT_SERVER'] = 'git.local.invalid'
GLOBALS['GERRIT_PLUS_SERVER'] = 'gerrit-plus.local.invalid'
GLOBALS['JIRA_SERVER'] = 'jira.local.invalid'
GLOBALS['LDAP_SERVER'] = 'ldap://ldap.local.invalid'
GLOBALS['LDAP_BASE_DN'] = 'dc=local,dc=invalid'
GLOBALS['PROXY_SERVER'] = ''
GLOBALS['PROXIES'] = {}
GLOBALS['GERRIT_DEBUG'] = True

GLOBALS['CACHE_TIMEOUT'] = 60 * 10
GLOBALS['CACHE_LONG_TIMEOUT'] = None
GLOBALS['ADMIN_EMAIL'] = 'nobody@local.invalid'
GLOBALS['ADMIN_NAME'] = 'local admin'
GLOBALS['STATIC_MD5'] = 'local'

CORE_ADMIN_SG = 'somc-sw-cmweb'
JENKINS_SERVERS = []

ISSUE_TREND_PROJECTS = ['eDream', 'FirefoxOS']
ISSUE_TREND_MANIFESTS = ['platform/manifest', 'quic/lf/manifest']
ISSUE_TREND_EXCLUDED_DISCIPLINES = [r'^S1_APQ8064', r'^Electronics$',
                                    r'^HW Fusion 3$', r'^eDream$']
ISSUE_TREND_EXCLUDED_TAGS = ['.', 'Rel Team', 'Will not deliver']

APPS_DIR = APP_REPO
FIXTURE_DIRS = (APP_REPO,)

# --------------------------------------------------------------------------
# Core Django
# --------------------------------------------------------------------------
DEBUG = True
ALLOWED_HOSTS = ['*']
SECRET_KEY = 'local-development-only-not-a-real-secret-key'
ROOT_URLCONF = 'config.urls_local'
WSGI_APPLICATION = 'config.wsgi_local.application'
ADMINS = ()
MANAGERS = ADMINS

# LOCAL: SQLite instead of PostgreSQL/RDS.
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': join(VAR, 'cmweb_local.sqlite3'),
    }
}
DATABASE_ALIAS_FOR_WRITE = 'default'
DATABASE_ROUTERS = ()
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

TIME_ZONE = 'UTC'
LANGUAGE_CODE = 'en-us'
USE_I18N = False
USE_L10N = True
USE_TZ = True
FEED_SITE_ID = 1
SITE_ID = 1

MEDIA_ROOT = join(VAR, 'media')
MEDIA_URL = '/media/'
STATIC_ROOT = join(VAR, 'static')
STATIC_URL = '/static/'
STATICFILES_DIRS = (join(PROJECT_REPO, 'static'),)
STATICFILES_FINDERS = (
    'django.contrib.staticfiles.finders.FileSystemFinder',
    'django.contrib.staticfiles.finders.AppDirectoriesFinder',
    'compressor.finders.CompressorFinder',
)

MIDDLEWARE = [
    'django.middleware.common.CommonMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django_session_timeout.middleware.SessionTimeoutMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    # LOCAL: RemoteUserMiddleware is dropped -- there is no Apache in front
    # doing LDAP basic auth, so it would log everyone out on every request.
    'django.contrib.messages.middleware.MessageMiddleware',
    'django_pagination_bootstrap.middleware.PaginationMiddleware',
    'cmweb.middleware.PjaxVersionMiddleware',
    'config.middleware_local.LocalPermissionMiddleware',
]

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [join(PROJECT_REPO, 'templates')],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.template.context_processors.media',
                'django.template.context_processors.static',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'cmweb.context_processors.settings',
                'cmweb.context_processors.preferences',
                'cmweb.context_processors.sql_queries',
                'cmweb.context_processors.debug',
            ],
        },
    },
]

INSTALLED_APPS = [
    # CMWEB apps (unchanged from the real settings except where noted)
    'base',
    'inlines',
    'aod',
    'explorer',
    'harvest',
    'users',
    'blog',
    'historian',
    'request',
    'rebase',
    'gerritproxy',
    'commit_message_checker',
    'issues',
    'dashboards',
    # LOCAL: 'search' omitted -- it is an OpenSearch-only app with no models.
    'packages',
    'cmjenkins',
    'schedule',
    'type_approval',
    'api',
    'backend',
    'vendorsync',
    'product_packages',

    # Prerequisites
    'compressor',
    'django_extensions',
    'django_filters',
    'django_fsm',
    'generic_pages',
    'grappelli',
    'django_pagination_bootstrap',
    'reversion',
    'sitetree',
    'tagging',
    'rest_framework',
    # Kept: the backend app imports django_celery_results.models.TaskResult at
    # module level, and the models need no broker -- results just go to the DB.
    'django_celery_results',
    # LOCAL: omitted -- 'django_opensearch_dsl' (no OpenSearch),
    # 'rest_framework_swagger' and 'rpc4django' (shimmed at the URL level only).

    # Django apps
    'django.contrib.auth',
    'django_comments',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.sites',
    'django.contrib.messages',
    'django.contrib.admin',
    'django.contrib.staticfiles',
    'django.contrib.humanize',
    'crispy_forms',
]

# --------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------
# LOCAL: LDAP backends are dropped entirely -- the shim would decline every
# login anyway. Local users authenticate against the Django user table.
AUTHENTICATION_BACKENDS = ['django.contrib.auth.backends.ModelBackend']
AUTH_DEFAULT_SERVICE_USERNAME = ''
AUTH_DEFAULT_SERVICE_PASSWORD = ''
LDAP_ENABLED_BY_DEFAULT = False

from urllib.parse import quote  # noqa: E402
ABSOLUTE_URL_OVERRIDES = {
    'users.profile': lambda o: '/users/%s' % quote(o.user.username),
}

LOGIN_REDIRECT_URL = '/'
LOGIN_URL = '/admin/login/'
SESSION_EXPIRE_SECONDS = 60 * 60 * 24
SESSION_EXPIRE_AFTER_LAST_ACTIVITY = True

# --------------------------------------------------------------------------
# Cache, mail, misc
# --------------------------------------------------------------------------
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
    },
}
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
SERVER_EMAIL = 'cmweb-local@local.invalid'
DEFAULT_FROM_EMAIL = SERVER_EMAIL
SMTP_SERVER = ''

SERIALIZATION_MODULES = {'json': 'cmweb.urljsonserializer'}
DATA_UPLOAD_MAX_NUMBER_FIELDS = None

CRISPY_TEMPLATE_PACK = 'bootstrap3'
CRISPY_ALLOWED_TEMPLATE_PACKS = ('bootstrap3',)

GRAPPELLI_ADMIN_TITLE = GLOBALS['CM_WEB_NAME'] + ' Admin'

REST_FRAMEWORK = {
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.DjangoModelPermissionsOrAnonReadOnly'
    ],
    'DEFAULT_FILTER_BACKENDS': [
        'django_filters.rest_framework.backends.DjangoFilterBackend',
        'rest_framework.filters.SearchFilter',
        'rest_framework.filters.OrderingFilter',
    ],
    'DEFAULT_RENDERER_CLASSES': (
        'rest_framework.renderers.JSONRenderer',
        'rest_framework.renderers.BrowsableAPIRenderer',
    ),
    'DEFAULT_PAGINATION_CLASS':
        'rest_framework.pagination.LimitOffsetPagination',
    'PAGE_SIZE': 70,
}
SWAGGER_SETTINGS = {'VALIDATOR_URL': None}

# LOCAL: run every Celery task inline; there is no broker.
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

# LOCAL: compression off. The real settings compress offline with a YUI jar
# that needs a JRE; leaving it on would make every page raise on a missing
# manifest entry.
COMPRESS_ENABLED = False
COMPRESS_OFFLINE = False
COMPRESS_OUTPUT_DIR = 'compressed'

IS_WSGI = False

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'default': {
            'format': '%(asctime)s [%(levelname)s] %(module)s: %(message)s',
        },
    },
    'handlers': {
        'console': {
            'level': 'INFO',
            'class': 'logging.StreamHandler',
            'formatter': 'default',
        },
    },
    'loggers': {
        'django.request': {'handlers': ['console'], 'level': 'ERROR'},
    },
    'root': {'handlers': ['console'], 'level': 'ERROR'},
}
