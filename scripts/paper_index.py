#!/usr/bin/env python3
"""Shared helpers for the paper index: marker files, titles, BibTeX checks.

Used by every stage so that the local hooks and the CI fallback agree on:

* where a marker lives and what it contains (``<stem>.research-area``);
* how a paper mentioned in a commit message is matched to a file on disk;
* whether a ``.bib`` really contains BibTeX (not just an empty file).

Marker format
-------------
Current format is a single JSON object::

    {"area": "Intelligence Software Engineering",
     "seq": 1,
     "contributor": "lihongweimail",
     "added": "2026-11-11"}

``seq`` is what the contributor typed in the commit message. It is kept for
traceability only: the README numbers entries automatically, so a stale
hand-written number can never break the generated index.

Older markers are plain text, one line, just the area name. They are still
read (``contributor`` ends up empty, ``added`` empty, so they sort first); the
next write upgrades them to JSON.
"""

from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAPERS = ROOT / "papers"
MARKER_SUFFIX = ".research-area"
PAPER_SUFFIXES = {".bib", ".pdf"}

BIB_TITLE_RE = re.compile(r"\btitle\s*=\s*[{\"](.+?)[}\"]\s*,", re.IGNORECASE | re.DOTALL)
# A real BibTeX entry starts a line with @type{. Anything else (comments only,
# an empty file, a half-written export) means "no usable metadata".
BIB_ENTRY_RE = re.compile(r"^[ \t]*@[A-Za-z]+[ \t]*[{(]", re.MULTILINE)


def marker_for(base: Path) -> Path:
    """Marker path for a stem path (a Path with no extension)."""
    return base.parent / (base.name + MARKER_SUFFIX)


# --------------------------------------------------------------------------
# Marker files
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Marker:
    area: str
    seq: int = 0
    contributor: str = ""
    added: str = ""

    def to_json(self) -> str:
        payload = {"area": self.area}
        if self.seq:
            payload["seq"] = self.seq
        payload["contributor"] = self.contributor
        payload["added"] = self.added
        return json.dumps(payload, ensure_ascii=False) + "\n"


def parse_marker(text: str) -> Marker | None:
    text = text.strip()
    if not text:
        return None
    if text.startswith("{"):
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # A truncated/edited JSON marker still tells us the area if the
            # first key survived; fall back to the legacy plain-text reading.
            return Marker(area=" ".join(text.strip("{} \n").split()))
        area = " ".join(str(data.get("area", "")).split())
        if not area:
            return None
        seq = data.get("seq", 0)
        try:
            seq = int(seq)
        except (TypeError, ValueError):
            seq = 0
        return Marker(
            area=area,
            seq=seq,
            contributor=" ".join(str(data.get("contributor", "")).split()),
            added=" ".join(str(data.get("added", "")).split()),
        )
    # Legacy: plain area name, possibly spread over several lines.
    return Marker(area=" ".join(text.split()))


def read_marker(base: Path) -> Marker | None:
    try:
        return parse_marker(marker_for(base).read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return None


def write_marker(base: Path, area: str, contributor: str, seq: int = 0) -> Path:
    path = marker_for(base)
    marker = Marker(
        area=" ".join(area.split()),
        seq=seq,
        contributor=" ".join(contributor.split()),
        added=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    )
    path.write_text(marker.to_json(), encoding="utf-8")
    return path


# --------------------------------------------------------------------------
# Matching a paper named in a commit message to a file on disk
# --------------------------------------------------------------------------

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
    the file name as well as the published title are accepted.
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


def has_bibtex_entries(path: Path) -> bool:
    """True when the file holds at least one ``@type{`` entry."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return bool(BIB_ENTRY_RE.search(text))


# --------------------------------------------------------------------------
# Directory scan
# --------------------------------------------------------------------------

def paper_bases(root: Path | None = None) -> list[Path]:
    """All stems (paths without extension) that look like a paper entry.

    Only ``papers/<user>/<file>`` is scanned: the layout is one flat directory
    per member, so nested directories (left over from the old layout) are
    ignored on purpose.
    """
    papers = (root or ROOT) / "papers"
    if not papers.is_dir():
        return []
    found: set[Path] = set()
    for user_dir in papers.iterdir():
        if not user_dir.is_dir() or user_dir.name.startswith("."):
            continue
        for file_path in user_dir.iterdir():
            if file_path.is_file() and file_path.suffix.lower() in PAPER_SUFFIXES:
                found.add(file_path.with_suffix(""))
    return sorted(found)
