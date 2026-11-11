#!/usr/bin/env python3
"""Resolve research areas for newly added paper directories.

Runs in the "Resolve Research Area" workflow on every push that touches papers/.

Contract
--------
* A paper lives in ``papers/<github-user>/<bibkey>/`` and contains at least a
  ``.bib`` or a ``.pdf`` file.
* The contributor declares the research area in the commit message:
  ``[AREA: <name>] <short description>``.
* For every paper directory that has no ``.research-area`` marker yet, this
  script writes the area name into that file.
* If any such directory cannot be assigned an unambiguous area, the script
  exits with status 1 so the workflow turns red and the contributor is told
  to fix the commit message. Silent skipping would quietly corrupt the index.

Attribution rules (in order)
----------------------------
1. For a directory introduced by one of the commits in this push, use the
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

``GITHUB_STEP_SUMMARY`` / ``GITHUB_OUTPUT`` are written when present.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAPERS = ROOT / "papers"
MARKER = ".research-area"
PAPER_SUFFIXES = {".bib", ".pdf"}

AREA_RE = re.compile(r"\[AREA\s*:\s*([^\]\r\n]+?)\s*\]", re.IGNORECASE)
# papers/<user>/<bibkey>/<file...>
PAPER_PATH_RE = re.compile(r"^papers/([^/]+)/([^/]+)/(.+)$")


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


def introduced_directories(commits: list[str]) -> dict[Path, str]:
    """Map a newly created paper directory -> the sha of the commit that added it."""
    result: dict[Path, str] = {}
    for sha in commits:
        for path in added_paths(sha):
            match = PAPER_PATH_RE.match(path)
            if not match:
                continue
            directory = PAPERS / match.group(1) / match.group(2)
            result.setdefault(directory, sha)
    return result


def paper_directories() -> list[Path]:
    """All directories that actually look like a paper entry."""
    if not PAPERS.is_dir():
        return []
    found: list[Path] = []
    for user_dir in sorted(PAPERS.iterdir()):
        if not user_dir.is_dir() or user_dir.name.startswith("."):
            continue
        for bib_dir in sorted(user_dir.iterdir()):
            if not bib_dir.is_dir() or bib_dir.name.startswith("."):
                continue
            if any(
                child.is_file() and child.suffix.lower() in PAPER_SUFFIXES
                for child in bib_dir.iterdir()
            ):
                found.append(bib_dir)
    return found


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

    introduced = introduced_directories(commits)
    targets = [
        directory
        for directory in paper_directories()
        if not (directory / MARKER).is_file()
    ]

    if not targets:
        print("No paper directory is missing a .research-area marker. Nothing to do.")
        emit_outputs(["All paper directories already have a marker."])
        return 0

    assignments: dict[Path, str] = {}
    problems: list[str] = []
    for directory in targets:
        rel = directory.relative_to(ROOT).as_posix()
        sha = introduced.get(directory)
        if sha is not None:
            candidates = areas_in(messages[sha])
            source = f"commit {sha[:8]}"
        else:
            candidates = list(all_areas)
            source = "this push"

        if len(candidates) == 1:
            assignments[directory] = candidates[0]
        elif not candidates:
            problems.append(
                f"`{rel}` — no `[AREA: ...]` found in {source}"
            )
        else:
            problems.append(
                f"`{rel}` — conflicting areas in {source}: "
                + ", ".join(f"`{name}`" for name in candidates)
                + " (split into one commit per area)"
            )

    if problems:
        print("ERROR: cannot resolve research areas for all paper directories:", file=sys.stderr)
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
    for directory, area in sorted(assignments.items()):
        rel = directory.relative_to(ROOT).as_posix()
        (directory / MARKER).write_text(area + "\n", encoding="utf-8")
        written.append(f"`{rel}/{MARKER}` → **{area}**")

    print(f"Wrote {len(written)} .research-area marker(s):")
    for line in written:
        print("  " + line)
    emit_outputs(written)
    return 0


if __name__ == "__main__":
    sys.exit(main())
