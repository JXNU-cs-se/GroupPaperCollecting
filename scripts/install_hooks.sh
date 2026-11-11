#!/bin/sh
# Enable this repository's git hooks. Hooks are local and are NOT cloned
# automatically, so every fresh clone needs this once.
#
#     sh scripts/install_hooks.sh
#
# After that, staging a PDF without a matching .bib makes the pre-commit hook
# generate the .bib and add it to the very same commit.
set -eu

root=$(git rev-parse --show-toplevel)
cd "$root"

if [ ! -f .githooks/pre-commit ]; then
  echo "install_hooks: .githooks/pre-commit is missing; is this the right repo?" >&2
  exit 1
fi

previous=$(git config --get core.hooksPath || true)
if [ -n "$previous" ] && [ "$previous" != ".githooks" ]; then
  echo "install_hooks: replacing core.hooksPath=$previous"
fi

# core.hooksPath must point at an executable file; a fresh checkout on a
# filesystem without the exec bit (or a file created via the web UI) needs this.
chmod +x .githooks/pre-commit 2>/dev/null || true
git config core.hooksPath .githooks

echo "pre-commit hook enabled (core.hooksPath=.githooks)."
echo "A staged PDF with no .bib will get one generated into the same commit."

if command -v python3 >/dev/null 2>&1; then
  if ! python3 -c "import pypdf" 2>/dev/null; then
    echo ""
    echo "hint: PDF text extraction needs an optional dependency:"
    echo "      python3 -m pip install -r requirements-pdf.txt"
    echo "      (without it the hook still runs, but metadata is more likely to be a stub)"
  fi
else
  echo ""
  echo "warning: python3 not found; the hook will refuse PDF-only commits." >&2
fi
