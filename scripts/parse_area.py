#!/usr/bin/env python3
"""Resolve research areas for newly added papers.

Runs in the "Resolve Research Area" workflow on every push that touches papers/.

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
* The contributor declares the area in the commit message. The documented
  template is ``<paper title> : [AREA: <area>]``, e.g.
  ``WeSCE A Benchmark for Measuring Security : [AREA: Intelligence Software Engineering]``.
  Only the bracketed part is parsed, so a leading description is harmless.
* For every paper stem that has a ``.pdf`` and/or ``.bib`` but no marker yet,
  this script writes the area name into ``<stem>.research-area``.
* If any such stem cannot be assigned an unambiguous area, the script exits
  with status 1 so the workflow turns red and the contributor is told to fix
  the commit message. Silent skipping would quietly corrupt the index.

Attribution rules (in order)
----------------------------
1. For a paper introduced by one of the commits in this push, use the
   ``[AREA: ...]`` value from *that specific commit*. This allows one push to
   contain several commits covering several different areas, as long as each
   commit declares exactly one area.
2. Otherwise (e.g. a repair commit after a missing ``[AREA: ...]``), use the
   area declared anywhere in this push, provided all declarations agree.

Environment
-----------
``BASE_SHA``      Commit sha before this push (``github.event.before``). If it
                  is absent or all zeroes, ``HEAD^`` is used instead.
``PUSH_COMMITS``  Optional space separated sha list, for local testing.

``GITHUB_STEP_SUMMARY`` is written when present.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAPERS = ROOT / "papers"
MARKER_SUFFIX = ".research-area"
PAPER_SUFFIXES = {".bib", ".pdf"}

# Tolerant on purpose: contributors type "[AREA: x]", "[ AREA: x ]" and the
# full-width "【AREA：x】" their input method produces. All mean the same thing.
AREA_RE = re.compile(
    r"[\[【]\s*AREA\s*[:：]\s*([^\]】\r\n]+?)\s*[\]】]",
    re.IGNORECASE,
)
# papers/<user>/<file>
PAPER_PATH_RE = re.compile(r"^papers/([^/]+)/(.+)$")


def marker_for(base: Path) -> Path:
    """Marker path for a stem path (a Path with no extension)."""
    return base.parent / (base.name + MARKER_SUFFIX)


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

    Used for repair commits: a contributor who forgot ``[AREA: ...]`` can edit
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


def paper_bases() -> list[Path]:
    """All stems (paths without extension) that look like a paper entry."""
    if not PAPERS.is_dir():
        return []
    found: set[Path] = set()
    for user_dir in PAPERS.iterdir():
        if not user_dir.is_dir() or user_dir.name.startswith("."):
            continue
        for file_path in user_dir.iterdir():
            if file_path.is_file() and file_path.suffix.lower() in PAPER_SUFFIXES:
                found.add(file_path.with_suffix(""))
    return sorted(found)


def areas_in(message: str) -> list[str]:
    """Unique, non-empty area names declared in a commit message, in order."""
    seen: list[str] = []
    for raw in AREA_RE.findall(message):
        name = " ".join(raw.split())
        if name and name not in seen:
            seen.append(name)
    return seen


def emit_outputs(lines: list[str]) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write("### Resolve Research Area\n\n")
            handle.write("\n".join(f"- {line}" for line in lines) + "\n")


def main() -> int:
    commits = push_commits()
    messages = {sha: commit_message(sha) for sha in commits}
    all_areas: list[str] = []
    for message in messages.values():
        for area in areas_in(message):
            if area not in all_areas:
                all_areas.append(area)

    introduced = introduced_bases(commits)
    touched = touched_bases(commits)
    unmarked = [base for base in paper_bases() if not marker_for(base).is_file()]
    # Only papers this push actually touched are in scope. Older unmarked
    # papers must NOT inherit an area from somebody else's commit message.
    targets = [base for base in unmarked if base in introduced or base in touched]
    legacy = [base for base in unmarked if base not in introduced and base not in touched]

    if legacy:
        print(
            "warning: paper(s) from earlier commits still lack a marker; "
            "left untouched (re-commit one of their files with [AREA: ...] to fix):",
            file=sys.stderr,
        )
        for base in legacy:
            print(f"  - {base.relative_to(ROOT).as_posix()}", file=sys.stderr)

    if not targets:
        print("No paper from this push needs a .research-area marker. Nothing to do.")
        emit_outputs(["No new marker was required for this push."])
        return 0

    assignments: dict[Path, str] = {}
    problems: list[str] = []
    for base in targets:
        rel = base.relative_to(ROOT).as_posix()
        sha = introduced.get(base) or touched.get(base)
        candidates = areas_in(messages[sha])
        source = f"commit {sha[:8]}"
        if not candidates and len(all_areas) == 1:
            candidates = list(all_areas)
            source = "the only area declared in this push"

        if len(candidates) == 1:
            assignments[base] = candidates[0]
        elif not candidates:
            problems.append(f"`{rel}.pdf / .bib` — no `[AREA: ...]` found in {source}")
        else:
            problems.append(
                f"`{rel}.pdf / .bib` — conflicting areas in {source}: "
                + ", ".join(f"`{name}`" for name in candidates)
                + " (split into one commit per area)"
            )

    if problems:
        print("ERROR: cannot resolve research areas for all papers:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        print(
            "\nFix: amend / re-commit with a message like "
            "`[AREA: 大模型推理优化] 添加 Smith 2024 论文`, one area per commit.\n"
            "See CONTRIBUTING.md for details.",
            file=sys.stderr,
        )
        emit_outputs(problems)
        return 1

    written: list[str] = []
    for base, area in sorted(assignments.items()):
        marker = marker_for(base)
        marker.write_text(area + "\n", encoding="utf-8")
        written.append(f"`{marker.relative_to(ROOT).as_posix()}` → **{area}**")

    print(f"Wrote {len(written)} .research-area marker(s):")
    for line in written:
        print("  " + line)
    emit_outputs(written)
    return 0


if __name__ == "__main__":
    sys.exit(main())
