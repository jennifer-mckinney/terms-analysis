#!/usr/bin/env bash
# Scan docs/evidence/ for local machine paths and private directory names.
#
# Server-side counterpart of .githooks/pre-commit check 4 (issue #91 P9
# security R2-F2 / grumpy round-2 #4): client hooks can be skipped or not
# installed, so CI runs this. Pattern SSoT:
# .claude/governance/evidence-leak-regex.txt. Matching is done by
# scripts/governance/leak_scan.py (the same implementation the hook uses):
# each line is URL-decoded, unescaped and case-folded before the canonical
# patterns run, so encoded spellings need no extra alternatives (#91 round 5).
#
# Two modes:
#   tree  (default) every file under docs/evidence/ in the checkout.
#   range (--range REV-RANGE) every line ADDED under docs/evidence/ by each
#         commit in REV-RANGE (git log -p -m --text). Issue #91 round 3 (security
#         CI note): a leak added and removed inside one PR passes a tip-only
#         scan but would still enter main history through a merge commit.
#         Merge commits are diffed against each parent (-m) so conflict
#         resolutions are scanned too. REV-RANGE is anything `git log`
#         accepts, e.g. BASE..HEAD, or a single commit to scan its whole
#         ancestry. Needs full history (fetch-depth 0).
#
# NUL bytes are stripped before matching so UTF-16 text and binary blobs with
# embedded paths are scanned too (grep -a / git log --text, never skipped).
# A compressed or archived file (zip/docx, gz, bz2, xz, zstd, 7z, PDF) cannot
# be read, so the matcher refuses it as "opaque-container" (#91 r8 F1).
#
# #91 r8 (security F4 / F5, grumpy 5): PATH NAMES are scanned too (a file or
# directory named after a home slug leaks with clean content), and a symlink
# is scanned as its target path (its blob in git), never followed.
#   tree:  every file, symlink and directory name under docs/evidence/;
#   range: every docs/evidence/ path added, changed or renamed in REV-RANGE.
#
# Usage: scripts/governance/scan-evidence-leaks.sh [repo-root]
#        scripts/governance/scan-evidence-leaks.sh --range REV-RANGE [repo-root]
# Exit: 0 = scanned, no leak; 1 = leak found; 2 = setup / scan error.
# Needs python3 (stdlib only); override with LEAK_SCAN_PYTHON.

set -euo pipefail
# Byte-wise matching: without C locale, macOS tr/grep reject non-UTF-8 bytes
# ("Illegal byte sequence") and a binary or UTF-16 file would go unscanned.
export LC_ALL=C

RANGE=""
if [[ "${1:-}" == "--range" ]]; then
    if [[ -z "${2:-}" ]]; then
        printf 'scan-evidence-leaks: --range needs a revision range\n' >&2
        exit 2
    fi
    RANGE="$2"
    shift 2
fi

ROOT="${1:-$(git rev-parse --show-toplevel)}"
REGEX_FILE="${ROOT}/.claude/governance/evidence-leak-regex.txt"
EVIDENCE_DIR="${ROOT}/docs/evidence"

if [[ ! -f "${REGEX_FILE}" ]]; then
    printf 'scan-evidence-leaks: pattern SSoT missing: %s\n' "${REGEX_FILE}" >&2
    exit 2
fi
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MATCHER="${SCRIPT_DIR}/leak_scan.py"
PYTHON="${LEAK_SCAN_PYTHON:-python3}"
if [[ ! -f "${MATCHER}" ]]; then
    printf 'scan-evidence-leaks: matcher missing: %s\n' "${MATCHER}" >&2
    exit 2
fi
if ! command -v "${PYTHON}" >/dev/null 2>&1; then
    printf 'scan-evidence-leaks: %s not found (needed by %s)\n' "${PYTHON}" "${MATCHER}" >&2
    exit 2
fi
# grep-compatible matcher: prints "<line>:<pattern>", exit 0 hit / 1 none /
# 2 error. -I: isolated mode, no cwd or PYTHON* env on the import path.
leak_match() {
    "${PYTHON}" -I "${MATCHER}" "${REGEX_FILE}" "$@"
}
# #91 security r6: fail closed. Exit 1 counts as "no leak" ONLY when the
# matcher also printed its "CLEAN <n>" sentinel; a Python crash before
# main() (or LEAK_SCAN_PYTHON=false) also exits 1 but prints no sentinel.
# Any exit other than 0 or 1 is an error.
is_clean() {
    [[ "$1" -eq 1 && "$2" =~ ^CLEAN\ [0-9]+$ ]]
}
# Validate the pattern SSoT up front so a malformed file is exit 2 even when
# there is nothing to scan.
set +e
selftest="$(printf '' | leak_match -)"
rc=$?
set -e
if ! is_clean "${rc}" "${selftest}"; then
    printf 'scan-evidence-leaks: invalid pattern SSoT %s (matcher exit %s)\n' "${REGEX_FILE}" "${rc}" >&2
    exit 2
fi

STRIPPED="$(mktemp)"
ADDED="$(mktemp)"
LISTING="$(mktemp)"
NAMES="$(mktemp)"
trap 'rm -f "${STRIPPED}" "${ADDED}" "${LISTING}" "${NAMES}"' EXIT

# scan_names LABEL: run the matcher over ${NAMES} (one path per line) and
# print "LEAK (LABEL): <path>" per hit. Returns the number of leaking names
# via ${name_leaks}; exits 2 when the matcher gives no clean attestation.
name_leaks=0
scan_names() {
    local label="$1" hits rc
    set +e
    hits="$(leak_match "${NAMES}")"
    rc=$?
    set -e
    if [[ "${rc}" -eq 0 ]]; then
        while IFS= read -r n; do
            name_leaks=$((name_leaks + 1))
            printf 'LEAK (%s): %s\n' "${label}" "$(sed -n "${n}p" "${NAMES}")" >&2
        done < <(printf '%s\n' "${hits}" | cut -d: -f1)
    elif ! is_clean "${rc}" "${hits}"; then
        printf 'scan-evidence-leaks: path name scan failed (matcher exit %s, no clean attestation)\n' "${rc}" >&2
        exit 2
    fi
}

if [[ -n "${RANGE}" ]]; then
    # One git call, written to a file so a git failure (bad range, shallow
    # clone) is exit 2, never mistaken for "no added lines".
    if ! git -C "${ROOT}" log -p -m --text --no-color --no-ext-diff --no-renames \
            --format='commit %H' "${RANGE}" -- docs/evidence/ > "${STRIPPED}"; then
        printf 'scan-evidence-leaks: git log failed for range %s\n' "${RANGE}" >&2
        exit 2
    fi
    # Keep only added hunk lines, prefixed with their commit and file:
    #   <sha7> <path>\t<content>
    # Diff headers (between "diff --git" and the first "@@") are skipped, so a
    # "+++ b/..." header is never treated as content. NULs stripped first.
    if ! tr -d '\000' < "${STRIPPED}" | awk '
        /^commit [0-9a-f]+$/ { sha = substr($2, 1, 7); hunk = 0; next }
        /^diff --git / { hunk = 0; file = $NF; sub(/^b\//, "", file); next }
        /^@@/ { hunk = 1; next }
        hunk && /^\+/ { printf "%s %s\t%s\n", sha, file, substr($0, 2) }
    ' > "${ADDED}"; then
        printf 'scan-evidence-leaks: could not parse git log for %s\n' "${RANGE}" >&2
        exit 2
    fi
    commits="$(grep -c '^commit ' "${STRIPPED}" || true)"
    added="$(wc -l < "${ADDED}" | tr -d ' ')"
    set +e
    # Match the content only (after the tab), never the sha/path prefix.
    hits="$(cut -f2- "${ADDED}" | leak_match -)"
    rc=$?
    set -e
    if [[ "${rc}" -eq 0 ]]; then
        printf '%s\n' "${hits}" | cut -d: -f1 | head -20 | while IFS= read -r n; do
            printf 'LEAK (history): %s\n' "$(sed -n "${n}p" "${ADDED}" | cut -f1)" >&2
        done
        printf 'scan-evidence-leaks: %d added line(s) in %s contain a local machine path. Scrub the commit(s) above.\n' \
            "$(printf '%s\n' "${hits}" | wc -l | tr -d ' ')" "${RANGE}" >&2
        exit 1
    elif ! is_clean "${rc}" "${hits}"; then
        printf 'scan-evidence-leaks: history scan failed (matcher exit %s, no clean attestation)\n' "${rc}" >&2
        exit 2
    fi
    # Path names added, changed or renamed in the range (deletions excluded:
    # the name entered history in the commit that added it). NUL-delimited so
    # a non-ASCII or newline-bearing name is not C-quoted and skipped.
    if ! git -C "${ROOT}" log -m --name-only -z --no-renames --diff-filter=d --format= \
            "${RANGE}" -- docs/evidence/ > "${LISTING}"; then
        printf 'scan-evidence-leaks: git log --name-only failed for range %s\n' "${RANGE}" >&2
        exit 2
    fi
    # Blank lines (separators) are harmless to the matcher; a tr failure is exit 2.
    tr '\000' '\n' < "${LISTING}" > "${NAMES}" \
        || { printf 'scan-evidence-leaks: could not read the name listing for %s\n' "${RANGE}" >&2; exit 2; }
    scan_names "history name"
    if [[ "${name_leaks}" -gt 0 ]]; then
        printf 'scan-evidence-leaks: %d path name(s) under docs/evidence/ in %s contain a local machine path. Rename them.\n' \
            "${name_leaks}" "${RANGE}" >&2
        exit 1
    fi
    printf 'scan-evidence-leaks: range %s: %s commit(s) touching docs/evidence/, %s added line(s), %s path name(s), no local machine paths\n' \
        "${RANGE}" "${commits}" "${added}" "$(grep -c . "${NAMES}" || true)"
    exit 0
fi

if [[ ! -d "${EVIDENCE_DIR}" ]]; then
    # Distinguishable from a clean scan: says explicitly nothing was scanned.
    printf 'scan-evidence-leaks: no docs/evidence/ directory; scanned 0 files\n'
    exit 0
fi

# One listing (written to a file so a find failure is exit 2, never a short
# loop): every entry below docs/evidence/, NUL-delimited.
if ! find "${EVIDENCE_DIR}" -mindepth 1 -print0 > "${LISTING}"; then
    printf 'scan-evidence-leaks: could not list %s\n' "${EVIDENCE_DIR}" >&2
    exit 2
fi
# Names are scanned relative to the repo root, so the checkout's own location
# (a CI runner or temp directory) is never part of what is matched.
: > "${NAMES}"
while IFS= read -r -d '' entry; do
    printf '%s\n' "${entry#"${ROOT}/"}" >> "${NAMES}"
done < "${LISTING}"
scan_names "name"

scanned=0
leaks=0
while IFS= read -r -d '' file; do
    if [[ -L "${file}" ]]; then
        # A symlink's content in git IS its target path: scan that string,
        # never follow the link (#91 r8, grumpy 5 / security F5).
        readlink "${file}" > "${STRIPPED}" \
            || { printf 'scan-evidence-leaks: could not read link %s\n' "${file}" >&2; exit 2; }
    elif [[ -f "${file}" ]]; then
        # Two steps, not a pipe, so a tr failure can't be mistaken for "no match".
        tr -d '\000' < "${file}" > "${STRIPPED}" \
            || { printf 'scan-evidence-leaks: could not read %s\n' "${file}" >&2; exit 2; }
    else
        continue  # a directory: its name was scanned above
    fi
    scanned=$((scanned + 1))
    set +e
    hits="$(leak_match "${STRIPPED}")"
    rc=$?
    set -e
    if [[ "${rc}" -eq 0 ]]; then
        leaks=$((leaks + 1))
        lines="$(printf '%s\n' "${hits}" | cut -d: -f1 | head -5 | paste -sd, -)"
        printf 'LEAK: %s line(s) %s\n' "${file#"${ROOT}/"}" "${lines}" >&2
    elif ! is_clean "${rc}" "${hits}"; then
        printf 'scan-evidence-leaks: scan failed for %s (matcher exit %s, no clean attestation)\n' "${file}" "${rc}" >&2
        exit 2
    fi
done < "${LISTING}"

if [[ "${leaks}" -gt 0 ]]; then
    printf 'scan-evidence-leaks: %d of %d evidence file(s) contain a local machine path. Scrub to <tmp>/, <repo>/ or <user>.\n' "${leaks}" "${scanned}" >&2
fi
if [[ "${name_leaks}" -gt 0 ]]; then
    printf 'scan-evidence-leaks: %d path name(s) under docs/evidence/ contain a local machine path. Rename them.\n' "${name_leaks}" >&2
fi
if [[ "${leaks}" -gt 0 || "${name_leaks}" -gt 0 ]]; then
    exit 1
fi
printf 'scan-evidence-leaks: scanned %d file(s) and %d path name(s), no local machine paths\n' \
    "${scanned}" "$(wc -l < "${NAMES}" | tr -d ' ')"
