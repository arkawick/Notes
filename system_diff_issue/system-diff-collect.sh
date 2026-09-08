#!/bin/bash -ex
#
# Step 3 of the system_diff job: collect the per component reports produced by
# the system_diff_matrix job, render them as HTML and decide whether the two
# system labels are equal.
#
# Input  (environment): EXCLUDE_PROJECTS, SYSTEM_LABEL_1, SYSTEM_LABEL_2
#                       FAIL_ON_DELTA=1|0   (default 0)
# Input  (files):       result-dir/<axis>/<component>_diff.txt
#                       result-dir/<axis>/<component>_diff_excluded.txt
# Output (files):       result-dir/all_diff.html
#                       result-dir/all_diff_excluded.html
#                       result-dir/diff/<md5>.txt
#                       result-dir/stats.tsv
#                       result-dir/summary.json
#                       verdict.properties
#
set -o pipefail

fail_on_delta="${FAIL_ON_DELTA:-0}"
workspace="${WORKSPACE:-$PWD}"
cd "$workspace"

shopt -s nullglob
diff_files=($(printf '%s\n' result-dir/*/*_diff.txt | sort))
excluded_files=($(printf '%s\n' result-dir/*/*_diff_excluded.txt | sort))
shopt -u nullglob

if [ ${#diff_files[@]} -eq 0 ]; then
    echo "ERROR: no per component diff reports were copied from system_diff_matrix, aborting!" >&2
    exit 1
fi

# Truncating instead of appending: a rebuild in a workspace that was not
# cleaned used to concatenate the previous run on top of the current one.
cat "${diff_files[@]}" > result-dir/all_diff.txt

if [ ${#excluded_files[@]} -eq 0 ]; then
    # EXCLUDE_PROJECTS is documented as optional, so an empty exclusion list
    # must not break the collection step.
    cp result-dir/all_diff.txt result-dir/all_diff_excluded.txt
else
    cat "${excluded_files[@]}" > result-dir/all_diff_excluded.txt
fi

(
cd result-dir

awk_program='
function html_escape(s) {
    gsub(/&/, "\\&amp;", s)
    gsub(/</, "\\&lt;", s)
    gsub(/>/, "\\&gt;", s)
    return s
}

function emit(line) {
    body = body line "\n"
}

function close_setchange() {
    if (in_setchange == 1) {
        emit("</ul>")
        in_setchange = 0
    }
}

BEGIN {
    comp_idx = 0
    in_component = 0
    in_project = 0
    in_diff = 0
    in_setchange = 0
    is_meta = 0
    body = ""
}

in_diff == 1 && (/^diff/ || /^$/ || /^Diff/ || /^PROJECT-SET-CHANGE/) {
    in_diff = 0
}

in_project == 1 && (/^project/ || /^$/ || /^Diff/ || /^PROJECT-SET-CHANGE/) {
    in_project = 0
    in_diff = 0

    emit("</ol>")
}

in_setchange == 1 && !/^PROJECT-SET-CHANGE/ {
    close_setchange()
}

in_component == 1 && /^Diff/ {
    in_component = 0
    in_project = 0
    in_diff = 0

    if (comp_projects[comp_idx] == 0 && comp_setchanges[comp_idx] == 0)
        emit("<p class=\"nodiff\">No diff</p>")
}

/^PROJECT-SET-CHANGE/ {
    if (in_setchange == 0) {
        emit("<h2>Project set changes</h2>")
        emit("<ul class=\"setchange\">")
        in_setchange = 1
    }
    comp_setchanges[comp_idx]++

    line = "<li><b>" $2 "</b> " html_escape($3)
    if ($2 == "MOVED")
        line = line " &mdash; path " html_escape($4) " &rarr; " html_escape($5)
    else if ($2 == "ADDED")
        line = line " &mdash; path " html_escape($5) ", revision " html_escape($7)
    else
        line = line " &mdash; path " html_escape($4) ", revision " html_escape($6)
    emit(line "</li>")
}

/^diff/ {
    in_diff = 1
    diff = $0

    if (is_meta == 0)
        comp_files[comp_idx]++

    key = component " " project " " diff
    gsub(/[^A-Za-z0-9 ._\/-]/, "_", key)
    cmd = "echo \"" key "\" | md5sum | cut -d\" \" -f1"
    (cmd | getline md5sum)
    close(cmd)
    diff_file = DIFF_FILES_DIR "/" md5sum ".txt"
    emit("<li><a href=\"" diff_file "\">" html_escape(diff) "</a></li>")
}

/^project/ {
    close_setchange()

    in_project = 1
    project = $2
    is_meta = (project == ".repo/manifests/")

    if (is_meta == 0) {
        comp_projects[comp_idx]++
        emit("<h2>" html_escape(project) "</h2>")
    } else {
        emit("<h2>" html_escape(project) " <span class=\"meta\">(manifest metadata, not a source delta)</span></h2>")
    }
    emit("<ol>")
}

/^Diff/ {
    close_setchange()

    comp_idx++
    in_component = 1
    is_meta = 0

    component = $3
    comp_name[comp_idx] = $3
    comp_label_1[comp_idx] = $4
    comp_label_2[comp_idx] = $6
    comp_projects[comp_idx] = 0
    comp_files[comp_idx] = 0
    comp_setchanges[comp_idx] = 0

    emit("<h1 id=\"c" comp_idx "\">" toupper($3) ": " $4 " vs " $6 "</h1>")
}

{
    if (in_diff == 1)
        print > diff_file
}

END {
    close_setchange()

    if (in_project == 1)
        emit("</ol>")

    if (in_component == 1 && comp_projects[comp_idx] == 0 && comp_setchanges[comp_idx] == 0)
        emit("<p class=\"nodiff\">No diff</p>")

    if (length(EXCLUDE_PROJECTS) > 0) {
        emit("<hr>")
        emit("<p>Projects excluded:</p>")
        emit("<ul>")
        n = split(EXCLUDE_PROJECTS, excluded, " ")
        for (i = 1; i <= n; i++)
            emit("<li>" html_escape(excluded[i]) "</li>")
        emit("</ul>")
    }

    total = 0
    for (i = 1; i <= comp_idx; i++)
        total += comp_projects[i] + comp_setchanges[i]

    print "<!DOCTYPE html>"
    print "<html>"
    print "<head>"
    print "<meta charset=\"utf-8\">"
    print "<title>" TITLE "</title>"
    print "<style>"
    print "body {font-family: tahoma; margin: 1.5em;}"
    print "h1 {font-size: 140%}"
    print "h2 {font-size: 110%}"
    print ".report-title {font-size: 150%; font-weight: bold;}"
    print ".verdict {display: inline-block; padding: 0.4em 0.8em; font-weight: bold;}"
    print ".ok {background: #e3f4e3; border: 1px solid #4a4;}"
    print ".delta {background: #fdf0e0; border: 1px solid #d80;}"
    print ".meta {font-weight: normal; color: #777; font-size: 85%;}"
    print ".nodiff {color: #4a4; font-weight: bold;}"
    print "table.summary {border-collapse: collapse; margin: 1em 0;}"
    print "table.summary th, table.summary td {border: 1px solid #bbb; padding: 0.3em 0.8em; text-align: left;}"
    print "table.summary th {background: #f0f0f0;}"
    print "p.direction {color: #555;}"
    print "</style>"
    print "</head>"
    print "<body>"

    print "<p class=\"report-title\">" TITLE "</p>"
    if (total == 0)
        print "<p class=\"verdict ok\">NO DELTA - every component is identical on source code level</p>"
    else
        print "<p class=\"verdict delta\">DELTA FOUND - " total " project(s) differ, see the table below</p>"

    print "<p class=\"direction\">Removed lines (-) are " LABEL_1 ", added lines (+) are " LABEL_2 ". The <i>.repo/manifests/</i> section describes the manifest git itself and always differs between two branches; it is not a source code delta.</p>"

    print "<table class=\"summary\">"
    print "<tr><th>Component</th><th>Label 1</th><th>Label 2</th><th>Projects with delta</th><th>Files changed</th><th>Project set changes</th><th>Verdict</th></tr>"
    for (i = 1; i <= comp_idx; i++) {
        if (comp_projects[i] + comp_setchanges[i] == 0)
            verdict = "<span class=\"nodiff\">no delta</span>"
        else
            verdict = "<b>delta</b>"
        print "<tr><td><a href=\"#c" i "\">" toupper(comp_name[i]) "</a></td><td>" html_escape(comp_label_1[i]) "</td><td>" html_escape(comp_label_2[i]) "</td><td>" comp_projects[i] "</td><td>" comp_files[i] "</td><td>" comp_setchanges[i] "</td><td>" verdict "</td></tr>"
    }
    print "</table>"

    printf "%s", body

    print "</body>"
    print "</html>"

    if (STATS_FILE != "") {
        for (i = 1; i <= comp_idx; i++)
            printf "%s\t%d\t%d\t%d\n", comp_name[i], comp_projects[i], comp_files[i], comp_setchanges[i] > STATS_FILE
        close(STATS_FILE)
    }
}'

DIFF_FILES_DIR=diff
mkdir -p "$DIFF_FILES_DIR"

awk -v DIFF_FILES_DIR="$DIFF_FILES_DIR" \
    -v LABEL_1="${SYSTEM_LABEL_1:-label 1}" \
    -v LABEL_2="${SYSTEM_LABEL_2:-label 2}" \
    -v TITLE="System diff ${SYSTEM_LABEL_1:-label 1} vs ${SYSTEM_LABEL_2:-label 2} - all projects" \
    "$awk_program" all_diff.txt > all_diff.html

awk -v DIFF_FILES_DIR="$DIFF_FILES_DIR" \
    -v EXCLUDE_PROJECTS="$EXCLUDE_PROJECTS" \
    -v LABEL_1="${SYSTEM_LABEL_1:-label 1}" \
    -v LABEL_2="${SYSTEM_LABEL_2:-label 2}" \
    -v TITLE="System diff ${SYSTEM_LABEL_1:-label 1} vs ${SYSTEM_LABEL_2:-label 2} - excluded projects removed" \
    -v STATS_FILE=stats.tsv \
    "$awk_program" all_diff_excluded.txt > all_diff_excluded.html
)

# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------
stats_file="result-dir/stats.tsv"
[ -f "$stats_file" ] || : > "$stats_file"

delta_count=$(awk -F'\t' '{ total += $2 + $4 } END { print total + 0 }' "$stats_file")

if [ "$delta_count" -eq 0 ]; then
    verdict="NO_DELTA"
else
    verdict="DELTA_FOUND"
fi

awk -F'\t' \
    -v label_1="${SYSTEM_LABEL_1:-}" \
    -v label_2="${SYSTEM_LABEL_2:-}" \
    -v verdict="$verdict" \
    -v delta_count="$delta_count" \
    -v excluded="${EXCLUDE_PROJECTS:-}" \
    -v build_url="${BUILD_URL:-}" '
BEGIN {
    printf "{\n"
    printf "  \"system_label_1\": \"%s\",\n", label_1
    printf "  \"system_label_2\": \"%s\",\n", label_2
    printf "  \"verdict\": \"%s\",\n", verdict
    printf "  \"delta_project_count\": %d,\n", delta_count
    printf "  \"excluded_projects\": \"%s\",\n", excluded
    printf "  \"build_url\": \"%s\",\n", build_url
    printf "  \"components\": ["
}
{
    if (NR > 1)
        printf ","
    printf "\n    {\"component\": \"%s\", \"delta_projects\": %d, \"delta_files\": %d, \"project_set_changes\": %d}", $1, $2, $3, $4
}
END {
    if (NR > 0)
        printf "\n  "
    printf "]\n}\n"
}' "$stats_file" > result-dir/summary.json

{
    echo "SYSTEM_DIFF_VERDICT=${verdict}"
    echo "SYSTEM_DIFF_DELTA_COUNT=${delta_count}"
} > verdict.properties

echo "============================================================"
echo "VERDICT: ${verdict} (${SYSTEM_LABEL_1:-label 1} vs ${SYSTEM_LABEL_2:-label 2})"
echo "------------------------------------------------------------"
awk -F'\t' '{
    if ($2 + $4 == 0)
        printf "  %-16s no source delta\n", $1
    else
        printf "  %-16s %d project(s), %d file(s), %d project set change(s)\n", $1, $2, $3, $4
}' "$stats_file"
echo "============================================================"

if [ "$verdict" = "DELTA_FOUND" ] && [ "$fail_on_delta" = "1" ]; then
    echo "ERROR: a delta was found and FAIL_ON_DELTA is enabled." >&2
    exit 2
fi
