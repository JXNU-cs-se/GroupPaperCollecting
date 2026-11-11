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
  template is ``<n>： <paper file name> : [AREA: <area>]  :  [贡献人 ： <gh account>]``,
  e.g. ``1： WeSCE A Benchmark for Measuring Security : [AREA: Intelligence Software Engineering]``.
  Only the bracketed ``[AREA: ...]`` is parsed; the position number, the
  trailing contributor field and any other prose are ignored.
* For every paper stem that has a ``.pdf`` and/or ``.bib`` but no marker yet,
  this script writes the area name into ``<stem>.research-area``.
* If any such stem cannot be assigned an unambiguous area, the script exits
  with status 1 so the workflow turns red and the contributor is told to fix
  the commit message. Silent skipping would quietly corrupt the index.

Attribution rules (in order)
----------------------------
0. A declaration that names an ALREADY categorised paper (template
   ``<title> : [AREA: ...]``) is **ignored**: the paper keeps its existing
   marker, is never moved to another section, and the declaration is not
   inherited by a newly added paper. This is reported in the step summary.
   A NEW (not yet categorised) paper is unaffected: its declaration is applied
   and the paper is written into that area's section, as before.
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

import difflib
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
BIB_TITLE_RE = re.compile(r"\btitle\s*=\s*[{\"](.+?)[}\"]\s*,", re.IGNORECASE | re.DOTALL)


def marker_for(base: Path) -> Path:
    """Marker path for a stem path (a Path with no extension)."""
    return base.parent / (base.name + MARKER_SUFFIX)


# --------------------------------------------------------------------------
# Commit message declarations
# --------------------------------------------------------------------------

def declarations_in(message: str) -> list[tuple[str, str]]:
    """Return ``(area, paper_title)`` pairs declared in a commit message.

    The documented template is ``<paper title> : [AREA: <area>]``, so the text
    between the start of the bracket's line and the bracket itself is treated
    as a *reference to a paper* only when it ends with a colon. Anything else
    (``[AREA: x] add Smith 2024``, ``docs: 说明 [AREA: ...] 的用法``) is prose
    and yields an empty title.

    ``paper_title`` matters because a member may legitimately mention an
    already-categorised paper in the same commit message (copying the template,
    a "see also" note, or re-touching that paper). Such a declaration must not
    be applied to the new paper, and must not move the old one.
    """
    declarations: list[tuple[str, str]] = []
    for match in AREA_RE.finditer(message):
        area = " ".join(match.group(1).split())
        if not area:
            continue
        line_start = message.rfind("\n", 0, match.start()) + 1
        prefix = message[line_start:match.start()].strip()
        title = ""
        if prefix.endswith((":", "：")):
            candidate = prefix[:-1].strip(" \t-—–·*#>")
            # The documented template prefixes the file name with the paper's
            # position in its section ("1： WeSCE …"). That number is not part
            # of the title, so drop it (with its separator) before matching.
            # A leading digit without a separator ("3D Gaussian Splatting") is
            # part of the title and must survive.
            candidate = re.sub(r"^\d+\s*[:：.、]\s*", "", candidate).strip()
            # Guard against a long prose line that merely happens to end with
            # a colon, and against a previously parsed "[AREA: ...]" fragment.
            if candidate and len(candidate) <= 200 and "[" not in candidate:
                title = candidate
        declarations.append((area, title))
    return declarations


def norm_text(text: str) -> str:
    """Letters/digits/CJK only, lowercased: 'WeSCE: A Benchmark' -> 'wesceabenchmark'."""
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", text.lower())


def bib_title(bib_path: Path) -> str:
    try:
        head = bib_path.read_text(encoding="utf-8", errors="replace")[:4000]
    except OSError:
        return ""
    match = BIB_TITLE_RE.search(head)
    if not match:
        return ""
    raw = re.sub(r"\\(?:emph|textbf|textit)\{([^{}]*)\}", r"\1", match.group(1))
    return " ".join(raw.replace("{", "").replace("}", "").split())


def title_matches_paper(title: str, base: Path) -> bool:
    """Does ``title`` refer to the paper at ``base``?

    Compared against the file stem and the BibTeX title, both normalised, so
    "WeSCE A Benchmark for Measuring Security" matches a file of that name as
    well as the fuller title stored in its .bib.
    """
    needle = norm_text(title)
    if not needle:
        return False
    keys = [norm_text(base.name), norm_text(bib_title(base.with_suffix(".bib")))]
    for key in keys:
        if not key:
            continue
        if needle == key:
            return True
        # A contributor often types an abbreviated title ("WeSCE A Benchmark
        # for Measuring Security" vs. the full published title).
        if len(needle) >= 12 and (needle in key or key in needle):
            return True
        if difflib.SequenceMatcher(None, needle, key).ratio() >= 0.86:
            return True
    return False


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
    for area, _title in declarations_in(message):
        if area not in seen:
            seen.append(area)
    return seen


def read_marker(base: Path) -> str:
    try:
        return " ".join(marker_for(base).read_text(encoding="utf-8").split())
    except OSError:
        return ""


def emit_outputs(lines: list[str]) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write("### Resolve Research Area\n\n")
            handle.write("\n".join(f"- {line}" for line in lines) + "\n")


def main() -> int:
    commits = push_commits()
    messages = {sha: commit_message(sha) for sha in commits}

    introduced = introduced_bases(commits)
    touched = touched_bases(commits)

    bases = paper_bases()
    existing = {base: read_marker(base) for base in bases if marker_for(base).is_file()}
    unmarked = [base for base in bases if base not in existing]

    # A commit message may mention an ALREADY categorised paper together with
    # its area (template copy-paste, a "see also" note, or simply re-touching
    # that paper). Those declarations are ignored: they must never move the
    # paper into another section, and they must not be inherited by a new paper
    # committed at the same time.
    usable: dict[str, list[str]] = {}
    ignored: list[str] = []
    for sha, message in messages.items():
        for area, title in declarations_in(message):
            if title:
                owner = next(
                    (base for base in existing if title_matches_paper(title, base)),
                    None,
                )
                if owner is not None:
                    kept = existing[owner]
                    reason = (
                        "方向与现有标记一致" if kept == area else f"现有方向为 **{kept}**"
                    )
                    ignored.append(
                        f"`{owner.name}` — 已有方向，忽略本次声明 `{area}`（{reason}）"
                    )
                    continue
            bucket = usable.setdefault(sha, [])
            if area not in bucket:
                bucket.append(area)

    all_areas: list[str] = []
    for sha in commits:
        for area in usable.get(sha, []):
            if area not in all_areas:
                all_areas.append(area)

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
            print(f"  - {base.relative_to(ROOT).as_posix()} → {existing[base]}")

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
        emit_outputs(
            ignored
            + [
                f"`{base.relative_to(ROOT).as_posix()}` 已有方向 **{existing[base]}**，未改动"
                for base in sorted(reasserted)
            ]
            or ["No new marker was required for this push."]
        )
        return 0

    assignments: dict[Path, str] = {}
    problems: list[str] = []
    for base in targets:
        rel = base.relative_to(ROOT).as_posix()
        sha = introduced.get(base) or touched.get(base)
        candidates = list(usable.get(sha, []))
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
        emit_outputs(problems + ignored)
        return 1

    written: list[str] = []
    for base, area in sorted(assignments.items()):
        marker = marker_for(base)
        marker.write_text(area + "\n", encoding="utf-8")
        written.append(f"`{marker.relative_to(ROOT).as_posix()}` → **{area}**")

    print(f"Wrote {len(written)} .research-area marker(s):")
    for line in written:
        print("  " + line)
    emit_outputs(written + ignored)
    return 0


if __name__ == "__main__":
    sys.exit(main())
