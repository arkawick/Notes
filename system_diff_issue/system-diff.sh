#!/bin/bash -ex
#
# Step 1 of the system_diff job: work out which components the two system
# labels are built from and hand one axis value per component to the
# system_diff_matrix job.
#
# Input  (environment): SYSTEM_LABEL_1, SYSTEM_LABEL_2, PROPERTIES_FILE
# Output (file):        $PROPERTIES_FILE with SYSTEM_DIFF_MATRIX_INPUT=...
#
set -o pipefail

if [ -z "$SYSTEM_LABEL_1" ] || [ -z "$SYSTEM_LABEL_2" ]; then
    echo "ERROR: Two system labels must be provided, aborting!" >&2
    exit 1
fi

if [ "$SYSTEM_LABEL_1" = "$SYSTEM_LABEL_2" ]; then
    echo "ERROR: Provided labels are the same, aborting!" >&2
    exit 1
fi

if ! build_metadata_pkgs_1=$(repository list "$SYSTEM_LABEL_1" -g build-metadata -xml); then
    echo "ERROR: Provided label ${SYSTEM_LABEL_1} is not a system label, aborting!" >&2
    exit 1
fi

if ! build_metadata_pkgs_2=$(repository list "$SYSTEM_LABEL_2" -g build-metadata -xml); then
    echo "ERROR: Provided label ${SYSTEM_LABEL_2} is not a system label, aborting!" >&2
    exit 1
fi

pkgs_count_1=$(xmllint --xpath "count(//package)" - <<<"$build_metadata_pkgs_1")
pkgs_count_2=$(xmllint --xpath "count(//package)" - <<<"$build_metadata_pkgs_2")
if [ "$pkgs_count_1" -ne "$pkgs_count_2" ]; then
    echo "ERROR: Provided labels are incompatible (number of contained metadata packages differ), aborting!" >&2
    exit 1
fi

if [ "$pkgs_count_1" -eq 0 ]; then
    echo "ERROR: ${SYSTEM_LABEL_1} contains no build-metadata packages, aborting!" >&2
    exit 1
fi

# Print the name of every build-metadata package of a label listing.
package_names() {  # <package-listing-xml> <package-count>
    local listing="$1" count="$2" i
    for ((i = 1; i <= count; i++)); do
        xmllint --xpath "string(//packages/package[$i]/@name)" - <<<"$listing"
        echo
    done
}

# Comparing only the number of packages is not enough: two labels can contain
# the same number of differently named components, in which case the lookup of
# the second version silently returns an empty string and the matrix job dies
# on 'repository getpackage <name> ""'.
pkg_names_1=$(package_names "$build_metadata_pkgs_1" "$pkgs_count_1" | sort)
pkg_names_2=$(package_names "$build_metadata_pkgs_2" "$pkgs_count_2" | sort)
if [ "$pkg_names_1" != "$pkg_names_2" ]; then
    echo "ERROR: Provided labels are incompatible (different components), aborting!" >&2
    echo "Components of ${SYSTEM_LABEL_1} vs ${SYSTEM_LABEL_2}:" >&2
    diff <(echo "$pkg_names_1") <(echo "$pkg_names_2") >&2 || true
    exit 1
fi

# Update job description
system_manifest_branch_1=$(repository labelmetadata "$SYSTEM_LABEL_1" | grep XB-SEMC-Manifest-Branch: | cut -d ':' -f2 | tr -d ' ')
system_manifest_branch_2=$(repository labelmetadata "$SYSTEM_LABEL_2" | grep XB-SEMC-Manifest-Branch: | cut -d ':' -f2 | tr -d ' ')
job_description="Diff between ${SYSTEM_LABEL_1} (${system_manifest_branch_1}) and ${SYSTEM_LABEL_2} (${system_manifest_branch_2})"
curl -s "${BUILD_URL}submitDescription" --data-urlencode "description=${job_description}"

# Get input for matrix job
SYSTEM_DIFF_MATRIX_INPUT=""
for i in $(seq 1 "$pkgs_count_1"); do
    build_metadata_pkg_name=$(xmllint --xpath "string(//packages/package[$i]/@name)" - <<<"$build_metadata_pkgs_1")
    build_metadata_pkg_ver_1=$(xmllint --xpath "string(//packages/package[$i]/@version)" - <<<"$build_metadata_pkgs_1")
    build_metadata_pkg_ver_2=$(xmllint --xpath "string(//packages/package[@name=\"$build_metadata_pkg_name\"]/@version)" - <<<"$build_metadata_pkgs_2")

    if [ -z "$build_metadata_pkg_ver_1" ] || [ -z "$build_metadata_pkg_ver_2" ]; then
        echo "ERROR: Could not resolve both versions of ${build_metadata_pkg_name}, aborting!" >&2
        exit 1
    fi

    SYSTEM_DIFF_MATRIX_INPUT+="${build_metadata_pkg_name}|${build_metadata_pkg_ver_1}|${build_metadata_pkg_ver_2} "
done
echo "SYSTEM_DIFF_MATRIX_INPUT=${SYSTEM_DIFF_MATRIX_INPUT}" > "${PROPERTIES_FILE}"
