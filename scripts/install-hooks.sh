#!/usr/bin/env bash
# Idempotent installer for the tracked git hooks (.githooks/pre-commit).
# Sets core.hooksPath (repository scope) to the ABSOLUTE path of the MAIN
# checkout's .githooks and marks the hook scripts executable. Safe to run from
# the main checkout, any linked worktree or any subdirectory; re-running is a
# no-op.
#
# Absolute, not relative (#384, owner ruling 2026-10-15): every worktree,
# including the #125 detached relocation worktree that has no .githooks of its
# own, runs the main checkout's hook, and the hook reads its governance files
# (e.g. monorepo-layout.conf) from that checkout.
#
# P9 review is no longer a local hook: it runs as the CI jobs in
# .github/workflows/p9-review.yml (terms-analysis#191).
set -euo pipefail
# An exported CDPATH makes `cd <relative>` search elsewhere and echo the
# result, which would corrupt the resolved paths below.
unset CDPATH

HOOKS_DIR_NAME=".githooks"

# The main checkout is the parent of the common git dir, the same from every
# linked worktree. `cd -P` + `pwd -P` give one canonical spelling, so a rerun
# compares equal and stays quiet.
COMMON_GIT_DIR="$(cd -P -- "$(git rev-parse --path-format=absolute --git-common-dir)" && pwd -P)"
MAIN_ROOT="$(cd -P -- "${COMMON_GIT_DIR}/.." && pwd -P)"
# Fail closed on any other layout (bare repository, --separate-git-dir): the
# parent must be a checkout whose common git dir is this one.
MAIN_COMMON="$(git -C "${MAIN_ROOT}" rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)"
if [ -z "${MAIN_COMMON}" ] || [ "$(cd -P -- "${MAIN_COMMON}" && pwd -P)" != "${COMMON_GIT_DIR}" ] \
    || [ "$(git -C "${MAIN_ROOT}" rev-parse --is-inside-work-tree 2>/dev/null || true)" != "true" ]; then
    echo "install-hooks: cannot locate the main checkout (bare repository or separate git dir); run from a standard clone" >&2
    exit 1
fi
EXPECTED_HOOKS_PATH="${MAIN_ROOT}/${HOOKS_DIR_NAME}"

if [ ! -d "${EXPECTED_HOOKS_PATH}" ]; then
    echo "install-hooks: ${EXPECTED_HOOKS_PATH} not found; the main checkout must track ${HOOKS_DIR_NAME}/" >&2
    exit 1
fi

# Replace any other hooksPath value (e.g. an absolute <repo>/.git/hooks that
# has none of the tracked hooks and silently disables them) and say so.
CURRENT_HOOKS_PATH="$(git config --get core.hooksPath || true)"
if [ -n "${CURRENT_HOOKS_PATH}" ] && [ "${CURRENT_HOOKS_PATH}" != "${EXPECTED_HOOKS_PATH}" ]; then
    echo "install-hooks: replacing core.hooksPath=${CURRENT_HOOKS_PATH} with ${EXPECTED_HOOKS_PATH} (the previous value bypasses the tracked hooks)" >&2
fi
# --local: the repository config, shared by every worktree (one value).
git config --local --replace-all core.hooksPath "${EXPECTED_HOOKS_PATH}"

# Verify the effective value: a higher-precedence scope (e.g. a per-worktree
# config.worktree) could still shadow the value just written.
EFFECTIVE_HOOKS_PATH="$(git config --get core.hooksPath || true)"
if [ "${EFFECTIVE_HOOKS_PATH}" != "${EXPECTED_HOOKS_PATH}" ]; then
    echo "install-hooks: core.hooksPath is still '${EFFECTIVE_HOOKS_PATH}' after install; find the shadowing scope with: git config --show-origin --show-scope --get-all core.hooksPath" >&2
    exit 1
fi

find "${EXPECTED_HOOKS_PATH}" -maxdepth 1 -type f -exec chmod +x {} \;

echo "Git hooks installed: core.hooksPath=${EXPECTED_HOOKS_PATH}"
