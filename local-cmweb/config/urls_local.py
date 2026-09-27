"""Root URLconf for local CMWEB.

Mirrors ``cmweb/urls.py`` from cmweb-project, including its sitetree navigation,
with two changes marked LOCAL: below. The original is left untouched.
"""

from django.urls import path, include, re_path
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.views.generic.base import RedirectView
from rpc4django import views

from sitetree.sitetreeapp import register_dynamic_trees, compose_dynamic_tree
from sitetree.utils import tree, item

from blog.feeds import CommentsFeed
from users.views import RedirectToUrl

admin.autodiscover()
favicon_view = RedirectView.as_view(
    url='/static/images/favicon.ico', permanent=True)

urlpatterns = [
    path(r'grappelli/', include('grappelli.urls')),
    path(r'admin/', admin.site.urls),
    path(r'aod/', include('aod.urls')),
    re_path(r'^comments/rss/$', CommentsFeed()),
    path(r'comments/', include('django_comments.urls')),
    path(r'gerritproxy/', include('gerritproxy.urls')),
    path(r'packages/', include('packages.urls')),
    path(r'commit_message_checker/', include('commit_message_checker.urls')),
    re_path(r'rpc/?', views.serve_rpc_request),
    # LOCAL: 'search/' dropped -- the search app needs an OpenSearch cluster.
    path(r'api/', include('api.urls')),
    path(r'api/a/', include(('api.urls', 'api'), 'apia')),
    re_path(r'^(explorer/)?', include('explorer.urls')),
    path(r'schedule/', include('schedule.urls')),
    path(r'harvest/', include('harvest.urls')),
    path(r'rebase/', include('rebase.urls')),
    path(r'historian/', include('historian.urls')),
    path(r'vendors/', include('vendorsync.urls')),
    path(r'request/', include('request.urls')),
    path(r'news/', include('blog.urls')),
    path(r'ta/', include('type_approval.urls')),
    path(r'backend/', include('backend.urls')),
    path(r'product_packages/', include('product_packages.urls')),
    re_path(r'^accounts/login/?$', RedirectToUrl.as_view()),
    re_path(r'^accounts/logout/?$', auth_views.LogoutView.as_view(),
            name='logout'),
    path(r'', include('issues.urls')),
    path(r'', include('users.urls')),
    path(r'', include('dashboards.urls')),
    path(r'', include('base.urls')),
    path(r'', include('generic_pages.urls')),
    re_path(r'^favicon.ico$', favicon_view),
]

register_dynamic_trees(
    compose_dynamic_tree((
        tree('section_nav', items=(
            item('cmweb', '/', hint="nav nav-stacked", children=(
                item("Automate", "#", url_as_pattern=False, children=(
                    item("Branch Scheduler", "/schedule/branches/",
                         url_as_pattern=False),
                    item("harvest.Cherry", "harvest_cherry_list"),
                    item("harvest.CherrypickPolicy", "harvest_policy_list"),
                    item("rebase.RebaseRecord", "rebase_record_list"),
                    item("rebase.RebasePolicy", "rebase_policy_list"),
                )),
                item("Browse", "#", url_as_pattern=False, children=(
                    item("explorer.ManifestBranch", "/branches/week/",
                         url_as_pattern=False),
                    item("explorer.Label", "explorer_label_list"),
                    item("explorer.Commit", "explorer_commit_list"),
                    item("Delta Builder", "explorer_label_delta_builder"),
                    item("issues.Issue", "issues_issue_list"),
                    item("packages.Package", "packages_package_list"),
                    item("explorer.Project", "explorer_project_list"),
                    item("dashboards.SWProject", "dashboards_swproject_list"),
                    item("AOD SystemFamilies", "aod_systemfamilies"),
                    item("AOD Systems", "aod_systems"),
                    item("users.Profile", "profile_list"),
                    item("vendorsync.Release", "vendorsync_index"),
                )),
                item("Visualise", "#", url_as_pattern=False, children=(
                    item("Family Tree", "historian_familytree"),
                    item("Timeline", "historian_timeline"),
                    item("Delivery Tags", "Delivery_Tag"),
                )),
                item("Request", "#", url_as_pattern=False, children=(
                    item("Branch requests", "request_branch_list"),
                    item("request.RepositoryRequest",
                         "request_repository_list")
                )),
                item("Blog", "#", url_as_pattern=False, children=(
                    item("Tips", "/news/categories/tips/",
                         url_as_pattern=False),
                    item("CMWEB", "/news/categories/cm-web/",
                         url_as_pattern=False),
                )),
                item("Preferences", "/settings/preferences",
                     url_as_pattern=False),
            )),
        )),
        tree('footer_nav', items=(
            item('footer_nav', '/', hint="list-inline pull-right", children=(
                item("API", "/api/", url_as_pattern=False),
                item("Administration", "/admin/", url_as_pattern=False),
                item("Server Status", "/status/", url_as_pattern=False),
            )),
        )),
    )),
    reset_cache=True
)
