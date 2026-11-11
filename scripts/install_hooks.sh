#!/bin/sh
# Enable this repository's git hooks. Hooks are local and are NOT cloned
# automatically, so every fresh clone needs this once.
#
#     sh scripts/install_hooks.sh
#
# The hooks work together, all at commit time:
#
#   .githooks/pre-commit   checks that every staged PDF has a .bib with real
#                         BibTeX in it, and generates the .bib from the PDF when
#                         it is missing or empty (same commit).
#   .githooks/commit-msg   checks that the message carries the number, the paper
#                         file name, [AREA: ...] and [贡献人 ： ...]; an
#                         incomplete message aborts the commit.
#   .githooks/post-commit  writes the .research-area marker, rebuilds README.md
#                         and folds both into the commit just created, so the
#                         index is correct in the commit you just made.
set -eu

root=$(git rev-parse --show-toplevel)
cd "$root"

missing=""
for hook in pre-commit commit-msg post-commit; do
  if [ ! -f ".githooks/$hook" ]; then
    echo "install_hooks: .githooks/$hook is missing; is this the right repo?" >&2
    missing="yes"
  fi
done
if [ -n "$missing" ]; then
  exit 1
fi

previous=$(git config --get core.hooksPath || true)
if [ -n "$previous" ] && [ "$previous" != ".githooks" ]; then
  echo "install_hooks: replacing core.hooksPath=$previous"
fi

# core.hooksPath must point at executable files; a fresh checkout on a
# filesystem without the exec bit (or a file created via the web UI) needs this.
for hook in pre-commit commit-msg post-commit; do
  chmod +x ".githooks/$hook" 2>/dev/null || true
done
git config core.hooksPath .githooks

echo "hooks enabled (core.hooksPath=.githooks):"
echo "  · pre-commit  — PDF without a usable .bib? the .bib is generated and staged"
echo "  · commit-msg  — message must carry 序号 / 文件名 / [AREA: ...] / [贡献人 ： ...]"
echo "  · post-commit — marker + README.md are folded into the same commit"

if command -v python3 >/dev/null 2>&1; then
  if ! python3 -c "import pypdf" 2>/dev/null; then
    echo ""
    echo "hint: PDF text extraction needs an optional dependency:"
    echo "      python3 -m pip install -r requirements-pdf.txt"
    echo "      (without it the hooks still run, but metadata is more likely to be a stub)"
  fi
else
  echo ""
  echo "warning: python3 not found; the hooks will refuse PDF-only commits." >&2
fi
