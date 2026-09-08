#!/usr/bin/env python3
"""Compare the project sets of two static repo manifests.

Prints one TAB separated record per project that is not provably identical in
both manifests:

    <STATE>\t<name>\t<path_1>\t<path_2>\t<revision_1>\t<revision_2>

STATE is one of:

    ADDED     project exists only in manifest 2
    REMOVED   project exists only in manifest 1
    MOVED     same revision, but the checkout path changed
    CHANGED   the pinned revision differs, or at least one side is not an
              immutable SHA-1.  A branch or tag name can resolve to different
              commits even when the string is identical, so those projects can
              never be assumed equal and are always compared.

Missing values are printed as '-'.

Projects that are absent from this output are pinned to the same SHA-1 in both
manifests and therefore have identical content in both labels; they do not need
to be synced or diffed.
"""

import re
import sys
import xml.etree.ElementTree as ET

SHA1_RE = re.compile(r'^[0-9a-f]{40}$')


def load(manifest_path):
    """Return {name: (path, revision)} for every project in the manifest."""
    root = ET.parse(manifest_path).getroot()
    default = root.find('default')
    default_revision = default.get('revision', '') if default is not None else ''

    projects = {}
    for project in root.iter('project'):
        name = project.get('name')
        if not name:
            continue
        projects[name] = (project.get('path') or name,
                          project.get('revision') or default_revision)
    return projects


def main(argv):
    if len(argv) != 3:
        sys.stderr.write('usage: %s <manifest_1.xml> <manifest_2.xml>\n' % argv[0])
        return 2

    manifest_1 = load(argv[1])
    manifest_2 = load(argv[2])

    for name in sorted(set(manifest_1) - set(manifest_2)):
        path, revision = manifest_1[name]
        print('REMOVED\t%s\t%s\t-\t%s\t-' % (name, path, revision))

    for name in sorted(set(manifest_2) - set(manifest_1)):
        path, revision = manifest_2[name]
        print('ADDED\t%s\t-\t%s\t-\t%s' % (name, path, revision))

    for name in sorted(set(manifest_1) & set(manifest_2)):
        path_1, revision_1 = manifest_1[name]
        path_2, revision_2 = manifest_2[name]

        immutable = SHA1_RE.match(revision_1) and SHA1_RE.match(revision_2)
        if revision_1 != revision_2 or not immutable:
            state = 'CHANGED'
        elif path_1 != path_2:
            state = 'MOVED'
        else:
            continue

        print('%s\t%s\t%s\t%s\t%s\t%s'
              % (state, name, path_1, path_2, revision_1, revision_2))

    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
