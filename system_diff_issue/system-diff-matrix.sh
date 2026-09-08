#!/bin/bash -ex
#
# Step 2 of the system_diff job, run once per component (matrix axis
# DIFF_INPUT): produce the source code diff of one component between two
# system labels.
#
# Input  (environment): DIFF_INPUT="<package>|<version_1>|<version_2>"
#                       EXCLUDE_PROJECTS  (optional, space separated names)
#                       REPO_MIRROR       (optional, local repo mirror)
#                       STRICT_DIFF_ERRORS=1|0             (default 1)
#                       INCLUDE_MANIFEST_GIT_DIFF=1|0      (default 1)
#                       INCLUDE_GIT_LOG=1|0                (default 1)
#                       SYNC_JOBS=<n>                      (default 8)
# Output (files):       result-dir/<component>_diff.txt
#                       result-dir/<component>_diff_excluded.txt
#                       result-dir/<component>_gitlog.txt
#                       result-dir/<component>_project_delta.tsv
#
set -o pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"
workspace="${WORKSPACE:-$PWD}"
result_dir="$workspace/result-dir"
strict_diff_errors="${STRICT_DIFF_ERRORS:-1}"
include_manifest_git_diff="${INCLUDE_MANIFEST_GIT_DIFF:-1}"
include_git_log="${INCLUDE_GIT_LOG:-1}"
sync_jobs="${SYNC_JOBS:-8}"

mkdir -p "$result_dir"

# ---------------------------------------------------------------------------
# 1. Resolve the two build-metadata packages of this component
# ---------------------------------------------------------------------------
if [ -z "$DIFF_INPUT" ]; then
    echo "ERROR: DIFF_INPUT is empty, aborting!" >&2
    exit 1
fi

IFS='|' read -r build_metadata_pkg_name build_metadata_pkg_ver_1 build_metadata_pkg_ver_2 <<<"$DIFF_INPUT"
if [ -z "$build_metadata_pkg_name" ] || [ -z "$build_metadata_pkg_ver_1" ] || [ -z "$build_metadata_pkg_ver_2" ]; then
    echo "ERROR: DIFF_INPUT '${DIFF_INPUT}' is not '<package>|<version_1>|<version_2>', aborting!" >&2
    exit 1
fi

deb_pkg_file_path_1=$(repository getpackage "$build_metadata_pkg_name" "$build_metadata_pkg_ver_1")
deb_pkg_file_path_2=$(repository getpackage "$build_metadata_pkg_name" "$build_metadata_pkg_ver_2")
dpkg-deb -I "$deb_pkg_file_path_1" > metadata_1.txt
dpkg-deb -I "$deb_pkg_file_path_2" > metadata_2.txt

metadata_field() {  # <metadata-file> <field-name>
    grep -m1 "^ *${2}:" "$1" | cut -d ':' -f2- | tr -d ' '
}

component_name=$(metadata_field metadata_1.txt XB-SONY-Component-Name)
component_name_2=$(metadata_field metadata_2.txt XB-SONY-Component-Name)
manifest_git=$(metadata_field metadata_1.txt XB-SONY-Component-Manifest-Git)
manifest_branch=$(metadata_field metadata_1.txt XB-SONY-Component-Manifest-Branch)
manifest_static_path_1=$(metadata_field metadata_1.txt XB-SONY-Component-Manifest-Static-Path)
manifest_static_path_2=$(metadata_field metadata_2.txt XB-SONY-Component-Manifest-Static-Path)
manifest_static_revision_1=$(metadata_field metadata_1.txt XB-SONY-Component-Manifest-Revision)
manifest_static_revision_2=$(metadata_field metadata_2.txt XB-SONY-Component-Manifest-Revision)

for field in component_name component_name_2 manifest_git manifest_branch \
             manifest_static_path_1 manifest_static_path_2 \
             manifest_static_revision_1 manifest_static_revision_2; do
    if [ -z "${!field}" ]; then
        echo "ERROR: '${field}' is missing from the package metadata of ${build_metadata_pkg_name}, aborting!" >&2
        exit 1
    fi
done

if [ "$component_name" != "$component_name_2" ]; then
    echo "ERROR: The two packages describe different components (${component_name} vs ${component_name_2}), aborting!" >&2
    exit 1
fi

diff_file="$result_dir/${component_name}_diff.txt"
excluded_file="$result_dir/${component_name}_diff_excluded.txt"
error_file="$result_dir/${component_name}_diff_errors.txt"
gitlog_file="$result_dir/${component_name}_gitlog.txt"
delta_file="$result_dir/${component_name}_project_delta.tsv"

# "set -o pipefail" matters here: without it a failing dpkg or tar leaves an
# empty manifest behind and the whole component is silently reported as having
# no delta.
dpkg --fsys-tarfile "$deb_pkg_file_path_1" | tar xOf - "./${manifest_static_path_1}" > manifest_static_1.xml
dpkg --fsys-tarfile "$deb_pkg_file_path_2" | tar xOf - "./${manifest_static_path_2}" > manifest_static_2.xml
for manifest in manifest_static_1.xml manifest_static_2.xml; do
    if [ ! -s "$manifest" ]; then
        echo "ERROR: ${manifest} could not be extracted from the build-metadata package, aborting!" >&2
        exit 1
    fi
    xmllint --noout "$manifest"
done

# ---------------------------------------------------------------------------
# 2. Work out which projects can possibly differ
# ---------------------------------------------------------------------------
python3 "${script_dir}/manifest_project_delta.py" manifest_static_1.xml manifest_static_2.xml > "$delta_file"

awk -F'\t' '$1 == "CHANGED" { print $3 }' "$delta_file" | sort -u > sync_paths.txt
awk -F'\t' '$1 == "CHANGED" { print $4 }' "$delta_file" | sort -u > forall_paths.txt
changed_count=$(wc -l < sync_paths.txt)

echo "INFO: ${changed_count} project(s) of ${component_name} can differ between ${build_metadata_pkg_ver_1} and ${build_metadata_pkg_ver_2}."

# The report header. The format of the first line is parsed by
# system-diff-collect.sh and must not change.
{
    echo "Diff of ${component_name} ${build_metadata_pkg_ver_1} and ${build_metadata_pkg_ver_2}"
    awk -F'\t' '$1 != "CHANGED" { printf "PROJECT-SET-CHANGE %s %s %s %s %s %s\n", $1, $2, $3, $4, $5, $6 }' "$delta_file"
} > "$diff_file"

# ---------------------------------------------------------------------------
# 3. Set up the source tree and sync only what can differ
# ---------------------------------------------------------------------------
repo_init_args=(-u "git://review.ptc.sony.co.jp/${manifest_git}" -b "$manifest_branch")
if [ -n "${REPO_MIRROR:-}" ] && [ -d "${REPO_MIRROR}" ]; then
    repo_init_args+=("--reference=${REPO_MIRROR}")
else
    echo "WARNING: REPO_MIRROR is unset or missing; syncing without a local mirror reference." >&2
fi

repo init "${repo_init_args[@]}"
cp manifest_static_1.xml manifest_static_2.xml .repo/manifests/.
repo init -m manifest_static_1.xml

if [ "$changed_count" -gt 0 ]; then
    mapfile -t sync_paths < sync_paths.txt
    repo sync -j"$sync_jobs" --no-clone-bundle "${sync_paths[@]}"
else
    echo "INFO: every project is pinned to the same revision in both labels; skipping repo sync."
fi

repo init -m manifest_static_2.xml

# ---------------------------------------------------------------------------
# 4. Diff of the manifest git itself (metadata, not source code)
# ---------------------------------------------------------------------------
if [ "$include_manifest_git_diff" = "1" ]; then
    (
        cd .repo/manifests

        for revision in "$manifest_static_revision_1" "$manifest_static_revision_2"; do
            if ! git cat-file -e "${revision}^{commit}" 2>/dev/null; then
                git fetch -q origin "+refs/heads/*:refs/remotes/origin/*"
                break
            fi
        done

        for revision in "$manifest_static_revision_1" "$manifest_static_revision_2"; do
            if ! git cat-file -e "${revision}^{commit}" 2>/dev/null; then
                echo "ERROR: manifest revision ${revision} is not available in ${manifest_git}, aborting!" >&2
                exit 1
            fi
        done

        git diff "${manifest_static_revision_1}..${manifest_static_revision_2}" > "$workspace/manifest_git_diff.txt"
    )

    if [ -s "$workspace/manifest_git_diff.txt" ]; then
        {
            echo "project .repo/manifests/"
            cat "$workspace/manifest_git_diff.txt"
            echo ""
        } >> "$diff_file"
    fi
fi

# ---------------------------------------------------------------------------
# 5. The actual source code diff
# ---------------------------------------------------------------------------
: > "$error_file"

if [ "$changed_count" -gt 0 ]; then
    mapfile -t forall_paths < forall_paths.txt

    # stdout and stderr are kept apart on purpose. They used to be merged into
    # the report, where a "fatal: bad revision" is dropped by the HTML
    # generator and the project silently looks unchanged.
    set +e
    repo forall "${forall_paths[@]}" -p -c \
        'git cat-file -e "${REPO_RREV}^{commit}" 2>/dev/null || git fetch -q origin; git diff "HEAD..${REPO_RREV}"' \
        >> "$diff_file" 2> "$error_file"
    forall_rc=$?
    set -e

    if [ "$forall_rc" -ne 0 ] || { [ "$strict_diff_errors" = "1" ] && [ -s "$error_file" ]; }; then
        echo "ERROR: 'repo forall' reported problems for ${component_name}; the diff cannot be trusted:" >&2
        cat "$error_file" >&2
        exit 1
    fi

    if [ "$include_git_log" = "1" ]; then
        {
            echo "Commits of ${component_name} ${build_metadata_pkg_ver_1} and ${build_metadata_pkg_ver_2}"
            echo "left side = only in ${build_metadata_pkg_ver_1}, right side = only in ${build_metadata_pkg_ver_2}"
            echo ""
        } > "$gitlog_file"
        repo forall "${forall_paths[@]}" -p -c \
            'git log --left-right --cherry-pick --oneline "HEAD...${REPO_RREV}"' >> "$gitlog_file" 2>/dev/null || true
    fi
fi

# ---------------------------------------------------------------------------
# 6. Second report with the uninteresting projects removed
# ---------------------------------------------------------------------------
# The excluded report is always produced, also when EXCLUDE_PROJECTS is empty,
# so that system-diff-collect.sh always has a complete set of inputs.
cp "$diff_file" "$excluded_file"

sed_escape() {  # <string>
    printf '%s' "$1" | sed 's/[][\\.*^$\/]/\\&/g'
}

for exclude_project in ${EXCLUDE_PROJECTS:-}; do
    if [ "$exclude_project" = ".repo/manifests" ] || \
       [ "$exclude_project" = "$manifest_git" ] || \
       [[ "$exclude_project" =~ ^platform/(qssi|target|system|amss)manifest$ ]]; then
        exclude_path=".repo/manifests"
    else
        exclude_path=$(xmllint --xpath "string(//manifest/project[@name=\"${exclude_project}\"]/@path)" manifest_static_1.xml 2>/dev/null || true)
        if [ -z "$exclude_path" ]; then
            exclude_path=$(xmllint --xpath "string(//manifest/project[@name=\"${exclude_project}\"]/@path)" manifest_static_2.xml 2>/dev/null || true)
        fi
    fi

    if [ -z "$exclude_path" ]; then
        # This used to produce the pattern "^project /$", which quietly matches
        # nothing, so a typo in EXCLUDE_PROJECTS went unnoticed.
        echo "WARNING: '${exclude_project}' is not part of ${component_name}; nothing excluded for it." >&2
        continue
    fi

    start_pattern="^project $(sed_escape "$exclude_path")\\/$"
    end_pattern='^$'
    sed -i "/${start_pattern}/,/${end_pattern}/d" "$excluded_file"
    sed -i "/^PROJECT-SET-CHANGE [A-Z]* $(sed_escape "$exclude_project") /d" "$excluded_file"
done
