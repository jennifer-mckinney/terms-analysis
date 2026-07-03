#!/usr/bin/env bash
# One-time installer: copy .githooks/pre-commit into .git/hooks/pre-commit.
#
# Contributors should run this once after cloning the repo. The hook enforces
# .gitignore governance invariants (see .githooks/pre-commit for the full
# policy). CI enforces the same invariants unconditionally via
# .github/workflows/gitignore-enforcement.yml, so the pre-commit hook is a
# fast-fail local convenience, not the only line of defense.

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
SRC="${REPO_ROOT}/.githooks/pre-commit"
DEST="${REPO_ROOT}/.git/hooks/pre-commit"

if [[ ! -f "${SRC}" ]]; then
    printf 'install-hooks: source hook not found: %s\n' "${SRC}" >&2
    exit 1
fi

if [[ -f "${DEST}" ]] && ! cmp -s "${SRC}" "${DEST}"; then
    printf 'install-hooks: existing %s differs from source; backing up to %s.bak\n' "${DEST}" "${DEST}" >&2
    cp "${DEST}" "${DEST}.bak"
fi

cp "${SRC}" "${DEST}"
chmod +x "${DEST}"
printf 'install-hooks: installed pre-commit hook at %s\n' "${DEST}"
