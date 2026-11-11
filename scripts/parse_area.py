#!/usr/bin/env python3
"""Resolve research areas for newly added papers — the CI fallback.

The normal path is ``.githooks/commit-msg`` + ``.githooks/pre-commit``: the
contributor's own clone validates the message, generates the BibTeX, writes the
marker and rebuilds README.md **inside the commit being created**. This script
only runs for contributors who did not install the hooks (paper uploaded
through the web UI, or a ``--no-verify`` commit). It performs the same steps on
the GitHub runner:

1. reads the ``[AREA: ...]`` / ``[贡献人 ： ...]`` declaration from the commit
   message that introduced each paper;
2. writes ``papers/<user>/<stem>.research-area`` (JSON: area, seq,
   contributor, date);
3. rebuilds README.md and stages it together with the markers, so the workflow
   commits marker + README in **one** commit — the index is correct as soon as
   the push finishes, not one commit later.

Layout
------
    papers/<github-user>/<stem>.pdf                 the paper
    papers/<github-user>/<stem>.bib                 its BibTeX
    papers/<github-user>/<stem>.research-area      generated marker

Each member owns one flat directory. There are no per-paper subdirectories.
The marker sits next to the paper and is named after it, so two members can
never touch the same path. File names may contain spaces.

Contract
--------
* The contributor declares the area, number and GitHub account in the commit
  message: ``<n>： <paper file name> : [AREA: <area>]  :  [贡献人 ： <account>]``.
  :mod:`commit_contract` is the single parser/validator for that format, shared
  with the local hooks, so both sides always agree.
* For every paper stem that has a ``.pdf`` and/or ``.bib`` but no marker yet,
  this script writes ``<stem>.research-area``.
* If any such stem cannot be assigned an unambiguous area, the script exits
  with status 1 so the workflow turns red and the contributor is told to fix
  the commit message. Silent skipping would quietly corrupt the index.

Attribution rules (in order)
----------------------------
0. A declaration that names an ALREADY categorised paper is **ignored**: the
   paper keeps its existing marker, is never moved to another section, and the
   declaration is not inherited by a newly added paper. This is reported in the
   step summary. A NEW (not yet categorised) paper is unaffected: its
   declaration is applied and the paper is written into that area's section.
1. For a paper introduced by one of the commits in this push, use the
   declaration from *that specific commit*. This allows one push to contain
   several commits covering several different areas, as long as each commit
   declares exactly one area.
2. Otherwise (e.g. a repair commit after a missing ``[AREA: ...]``), use the
   area declared anywhere in this push, provided all declarations agree.

Environment
-----------
``BASE_SHA``        Commit sha before this push (``github.event.before``). If it
                    is absent or all zeroes, ``HEAD^`` is used instead.
``PUSH_COMMITS``    Optional space separated sha list, for local testing.
``GITHUB_ACTIONS``  When set, the rebuilt README.md is staged so the workflow's
                    commit picks it up.
``GITHUB_STEP_SUMMARY`` is written when present.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import build_readme
from commit_contract import Declaration, declarations_in, help_text
from paper_index import (
    PAPER_SUFFIXES,
    ROOT,
    marker_for,
    paper_bases,
    read_marker,
    title_matches_paper,
    write_marker,
)

# papers/<user>/<file> — the layout is flat, so a nested directory is not a
# paper entry (leftovers of the old per-paper-subdirectory layout are ignored).
PAPER_PATH_RE = re.compile(r"^papers/([^/]+)/([^/]+)$")


def git(*args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if check and result.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed ({result.returncode}):\n{result.stderr.strip()}"
        )
    return result.stdout


def push_commits() -> list[str]:
    """Return the commit shas of this push, oldest first."""
    override = os.environ.get("PUSH_COMMITS", "").strip()
    if override:
        return override.split()

    base = os.environ.get("BASE_SHA", "").strip()
    if base and set(base) != {"0"}:
        # The sha may not be present locally (e.g. a shallow checkout); verify it.
        if subprocess.run(
            ["git", "cat-file", "-e", f"{base}^{{commit}}"],
            cwd=ROOT,
            capture_output=True,
        ).returncode == 0:
            shas = git("rev-list", "--reverse", f"{base}..HEAD").split()
            if shas:
                return shas

    # Fallbacks: single parent commit, or the root commit.
    if subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD^"], cwd=ROOT, capture_output=True
    ).returncode == 0:
        shas = git("rev-list", "--reverse", "HEAD^..HEAD").split()
        if shas:
            return shas
    return git("rev-parse", "HEAD").split()


def commit_message(sha: str) -> str:
    return git("log", "-1", "--format=%B", sha)


def added_paths(sha: str) -> list[str]:
    """Files added by a single commit (works for the root commit too)."""
    out = git(
        "diff-tree", "--root", "--no-commit-id", "--name-only",
        "--diff-filter=A", "-r", sha,
    )
    return [line.strip() for line in out.splitlines() if line.strip()]


def introduced_bases(commits: list[str]) -> dict[Path, str]:
    """Map a newly added paper stem -> sha of the commit that introduced it."""
    result: dict[Path, str] = {}
    for sha in commits:
        for path in added_paths(sha):
            if not PAPER_PATH_RE.match(path):
                continue
            file_path = ROOT / path
            if file_path.suffix.lower() not in PAPER_SUFFIXES:
                continue
            result.setdefault(file_path.with_suffix(""), sha)
    return result


def touched_bases(commits: list[str]) -> dict[Path, str]:
    """Map a stem touched (added OR modified) in this push -> last commit sha.

    Used for repair commits: a contributor who forgot the declaration can edit
    the .bib and re-commit. Papers that were NOT touched by this push are never
    assigned an area from somebody else's commit message.
    """
    result: dict[Path, str] = {}
    for sha in commits:
        out = git(
            "diff-tree", "--root", "--no-commit-id", "--name-only", "-r", sha
        )
        for path in out.splitlines():
            path = path.strip()
            if not path or not PAPER_PATH_RE.match(path):
                continue
            file_path = ROOT / path
            if file_path.suffix.lower() not in PAPER_SUFFIXES:
                continue
            result[file_path.with_suffix("")] = sha
    return result


def emit_outputs(lines: list[str]) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write("### Resolve Research Area\n\n")
            handle.write("\n".join(f"- {line}" for line in lines) + "\n")


def stage(paths: list[str]) -> None:
    if not paths:
        return
    result = subprocess.run(
        ["git", "add", "--", *paths], cwd=ROOT, capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"git add failed: {result.stderr.strip()}")


def main() -> int:
    commits = push_commits()
    messages = {sha: commit_message(sha) for sha in commits}

    introduced = introduced_bases(commits)
    touched = touched_bases(commits)

    bases = paper_bases()
    existing = {base: marker for base in bases if (marker := read_marker(base)) is not None}
    unmarked = [base for base in bases if base not in existing]

    # A commit message may mention an ALREADY categorised paper together with
    # its area (template copy-paste, a "see also" note, or simply re-touching
    # that paper). Those declarations are ignored: they must never move the
    # paper into another section, and they must not be inherited by a new paper
    # committed at the same time.
    usable: dict[str, list[Declaration]] = {}
    ignored: list[str] = []
    for sha, message in messages.items():
        for declaration in declarations_in(message):
            if declaration.paper:
                owner = next(
                    (base for base in existing if title_matches_paper(declaration.paper, base)),
                    None,
                )
                if owner is not None:
                    kept = existing[owner].area
                    reason = (
                        "方向与现有标记一致" if kept == declaration.area
                        else f"现有方向为 **{kept}**"
                    )
                    ignored.append(
                        f"`{owner.name}` — 已有方向，忽略本次声明 `{declaration.area}`（{reason}）"
                    )
                    continue
            bucket = usable.setdefault(sha, [])
            if all(item.area != declaration.area for item in bucket):
                bucket.append(declaration)

    all_areas: list[str] = []
    all_declarations: list[Declaration] = []
    for sha in commits:
        for declaration in usable.get(sha, []):
            if declaration.area not in all_areas:
                all_areas.append(declaration.area)
            all_declarations.append(declaration)

    # Only papers this push actually touched are in scope. Older unmarked
    # papers must NOT inherit an area from somebody else's commit message.
    targets = [base for base in unmarked if base in introduced or base in touched]
    legacy = [base for base in unmarked if base not in introduced and base not in touched]
    reasserted = [base for base in existing if base in introduced or base in touched]

    for line in ignored:
        print(f"ignored: {line}")
    if reasserted:
        print("Already categorised, left untouched (not re-added to any section):")
        for base in sorted(reasserted):
            print(f"  - {base.relative_to(ROOT).as_posix()} → {existing[base].area}")

    if legacy:
        print(
            "warning: paper(s) from earlier commits still lack a marker; "
            "left untouched (re-commit one of their files with the full "
            "commit message to fix):",
            file=sys.stderr,
        )
        for base in legacy:
            print(f"  - {base.relative_to(ROOT).as_posix()}", file=sys.stderr)

    assignments: dict[Path, Declaration] = {}
    problems: list[str] = []
    for base in targets:
        rel = base.relative_to(ROOT).as_posix()
        sha = introduced.get(base) or touched.get(base)
        candidates = list(usable.get(sha, []))
        source = f"commit {sha[:8]}" if sha else "this push"
        if not candidates and len(all_areas) == 1:
            candidates = [
                declaration
                for declaration in all_declarations
                if declaration.area == all_areas[0]
            ][:1]
            source = "the only area declared in this push"

        if len(candidates) == 1:
            assignments[base] = candidates[0]
        elif not candidates:
            problems.append(f"`{rel}.pdf / .bib` — no `[AREA: ...]` found in {source}")
        else:
            problems.append(
                f"`{rel}.pdf / .bib` — conflicting areas in {source}: "
                + ", ".join(f"`{item.area}`" for item in candidates)
                + " (split into one commit per area)"
            )

    # Contract check: the four required fields must be present on the
    # declaration that actually gets applied. Local hooks already blocked such
    # a commit, so reaching this point means the hooks were skipped.
    for base, declaration in assignments.items():
        gaps = declaration.missing()
        if gaps:
            problems.append(
                f"`{base.relative_to(ROOT).as_posix()}` — commit 注释缺少 "
                + "、".join(gaps)
            )

    if problems:
        print("ERROR: cannot resolve research areas for all papers:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        print("\n" + help_text(), file=sys.stderr)
        emit_outputs(problems + ignored)
        return 1

    written: list[str] = []
    staged: list[str] = []
    for base, declaration in sorted(assignments.items()):
        marker = write_marker(
            base,
            area=declaration.area,
            contributor=declaration.contributor,
            seq=declaration.seq,
        )
        staged.append(marker.relative_to(ROOT).as_posix())
        written.append(
            f"`{marker.relative_to(ROOT).as_posix()}` → **{declaration.area}**"
            f"（贡献人 @{declaration.contributor or '未注明'}）"
        )

    if written:
        print(f"Wrote {len(written)} .research-area marker(s):")
        for line in written:
            print("  " + line)

    # README is rebuilt here as well, and staged right after the markers, so
    # the workflow's single `git commit` contains both. Without this the index
    # would only catch up on the commit *after* the paper.
    readme_changed = build_readme.write_readme()
    if readme_changed and os.environ.get("GITHUB_ACTIONS"):
        staged.append("README.md")
    # Markers are staged by the workflow itself as well; staging them here
    # keeps `git add` idempotent when README changed but no marker did.
    if os.environ.get("GITHUB_ACTIONS") and staged:
        stage(staged)

    if not written and not readme_changed:
        print("Nothing to do for this push.")

    emit_outputs(
        written
        + (["`README.md` 已重建"] if readme_changed else [])
        + ignored
        + [
            f"`{base.relative_to(ROOT).as_posix()}` 已有方向 **{existing[base].area}**，未改动"
            for base in sorted(reasserted)
        ]
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
