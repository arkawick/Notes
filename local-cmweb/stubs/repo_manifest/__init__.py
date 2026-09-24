"""Shim for the internal ``repo-manifest`` package.

Real package: parses repo XML manifests into project objects. Enough of the
surface is implemented here to parse a manifest file, because manifest parsing
is pure XML handling with no internal service behind it.
"""

from xml.dom import minidom

from _shim import ShimNotAvailable  # noqa: F401  (re-exported for callers)


class ManifestError(Exception):
    """Base error for manifest handling."""


class ManifestParseError(ManifestError):
    """Raised when a manifest cannot be parsed."""


class Project(object):
    """One ``<project>`` element of a repo manifest."""

    def __init__(self, name=None, path=None, revision=None, groups=None,
                 remote=None, upstream=None, **kwargs):
        """Store the attributes CMWEB reads off a manifest project."""
        self.name = name
        self.path = path if path is not None else name
        self.revision = revision
        self.groups = groups or []
        self.remote = remote
        self.upstream = upstream
        self.copyfiles = kwargs.get('copyfiles', [])
        self.linkfiles = kwargs.get('linkfiles', [])
        for key, value in kwargs.items():
            if not hasattr(self, key):
                setattr(self, key, value)

    def __repr__(self):
        """Return a debug representation."""
        return '<Project {}@{}>'.format(self.name, self.revision)


class RepoXmlManifest(object):
    """A parsed repo XML manifest.

    ``projects`` is a dict keyed by project name, matching how
    ``explorer/management/indexing.py`` uses it.
    """

    def __init__(self, data=None):
        """Parse ``data`` (an XML string or file-like object)."""
        self.projects = {}
        self.remotes = {}
        self.default = {}
        self.manifest = None
        if data is None:
            return
        if hasattr(data, 'read'):
            data = data.read()
        if isinstance(data, bytes):
            data = data.decode('utf-8', 'replace')
        try:
            self.manifest = minidom.parseString(data)
        except Exception as exc:
            raise ManifestParseError(str(exc))
        self._load()

    def _load(self):
        """Populate remotes, defaults and projects from the parsed DOM."""
        for node in self.manifest.getElementsByTagName('default'):
            for key, value in node.attributes.items():
                self.default[key] = value
        for node in self.manifest.getElementsByTagName('remote'):
            attrs = dict(node.attributes.items())
            if 'name' in attrs:
                self.remotes[attrs['name']] = attrs
        for node in self.manifest.getElementsByTagName('project'):
            attrs = dict(node.attributes.items())
            name = attrs.get('name')
            if not name:
                continue
            groups = attrs.get('groups', '')
            self.projects[name] = Project(
                name=name,
                path=attrs.get('path', name),
                revision=attrs.get('revision', self.default.get('revision')),
                groups=[g for g in groups.split(',') if g],
                remote=attrs.get('remote', self.default.get('remote')),
                upstream=attrs.get('upstream'),
            )

    def __contains__(self, name):
        """Return True if ``name`` is a project in this manifest."""
        return name in self.projects

    def __iter__(self):
        """Iterate over the projects."""
        return iter(self.projects.values())

    def toxml(self):
        """Return the manifest XML, if one was parsed."""
        if self.manifest is None:
            return ''
        return self.manifest.toxml()
