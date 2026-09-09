#!/bin/sh
# Every check this project has.
#
# ruff comes from `uv run`, so it is the version pinned as a dev dependency in
# pyproject.toml and the same one CI pins on the action. An unpinned `uvx ruff`
# would fetch whatever is current and disagree with CI the moment ruff widens
# its default rule set, which is what turned main red once already.
#
# There is also a deliberate asymmetry. The project depends on mlx-audio, which
# ships wheels for Apple Silicon and for nothing else, so a Linux runner cannot
# install it and can only prove that the sources parse and the top level package
# imports. On this machine the dependencies really resolve, so the same script
# does more.
set -eu
cd "$(dirname "$0")/.."

fail=0
step() { printf '\n== %s\n' "$1"; }

step "Lint (ruff, pinned in pyproject.toml)"
uv run ruff check . || fail=1

step "Byte-compile all sources"
python3 -m compileall -q podcast run.py && echo "ok" || fail=1

step "Import the top-level package"
python3 -c "import podcast; print('podcast', podcast.__version__)" || fail=1

step "Source pages stay on the data side of the prompt"
uv run python tests/test_fence.py || fail=1

if [ "$(uname -sm)" = "Darwin arm64" ]; then
  step "Apple Silicon: resolve the real dependency tree"
  uv sync --frozen --quiet && echo "ok, environment resolves" || fail=1

  step "Apple Silicon: import the modules that need mlx-audio"
  uv run python -c "import podcast; print('full import ok')" || fail=1

  # Needs the `publish` extra for googleapiclient, which the default sync does
  # not install, so it sits with the other checks that only run here. It was
  # written for the PyDrive2 migration and then run by nothing.
  step "The Drive publish path, mocked"
  uv run --extra publish python scripts/test_publish.py || fail=1
else
  printf '\n(not Apple Silicon: skipping the checks that need mlx-audio)\n'
fi

if [ "$fail" -ne 0 ]; then printf '\nvalidate: FAILED\n'; exit 1; fi
printf '\nvalidate: everything passes\n'
