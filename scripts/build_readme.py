#!/usr/bin/env python3
"""Aggregate paper entries by research area and regenerate README.md.

Runs in two places, with the same output for the same inputs:

* ``.githooks/commit-msg`` (via ``scripts/apply_local.py``) — the normal path.
  README.md is rewritten *inside the commit that adds the paper*, so the index
  is already correct when it is pushed.
* the "Resolve Research Area" / "Build README" workflows — the fallback for
  contributors who did not install the hooks (web upload, ``--no-verify``).

Layout: ``papers/<user>/<stem>.pdf`` + ``<stem>.bib`` + ``<stem>.research-area``.
Files are matched by stem (the file name without its extension); file names may
contain spaces, so PDF links are percent-encoded.

Every entry is rendered as a numbered GB/T 7714-2015 reference plus its
contributor::

    1： ZHANG Z, WEN T, SUN S, et al. WeSCE: a benchmark for measuring security drift in LLM-driven code editing[J]. arXiv preprint arXiv:2608.15092, 2026. : [lihongweimail]

The visible text follows GB/T 7714-2015 (see ``scripts/gbt7714.py``); the title
is additionally a Markdown link to the PDF, so the reference stays standard
while remaining clickable.

Numbers are generated, never copied from the commit message: they are assigned
per section, oldest entry first (``added`` date in the marker), so adding a new
paper never renumbers the ones above it and two contributors can never claim
the same number.

The output is deterministic for a given set of inputs, so a no-op rebuild does
not create a commit.

BibTeX files written by ``scripts/pdf_to_bib.py`` start with an
``%% AUTO-GENERATED`` header. Such entries get a visible「待核对」badge in the
README; once a human fixes the metadata and removes the header the badge
disappears on the next rebuild.

``bibtexparser`` is used when available; both the v1 (``loads``/``load``) and
v2 (``parse_string``) APIs are supported. A small built-in parser is used as a
fallback so the aggregator still works in a bare environment (local preview,
or a runner where the dependency install failed).
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from commit_contract import convention_lines
from gbt7714 import format_reference
from paper_index import (
    MARKER_SUFFIX,
    PAPER_SUFFIXES,
    PAPERS,
    ROOT,
    read_marker,
)

README = ROOT / "README.md"
_FALLBACK_WARNED = False


try:
    # Chinese area names are sorted by pinyin, which is what "alphabetical"
    # means for a mostly-Chinese index. Falls back to code point order when the
    # optional dependency is absent (e.g. a bare local preview).
    from pypinyin import lazy_pinyin

    def area_sort_key(area: str) -> tuple[str, str]:
        return (" ".join(lazy_pinyin(area)).lower(), area.lower())

except ImportError:  # pragma: no cover

    def area_sort_key(area: str) -> tuple[str, str]:
        return (area, area.lower())


# --------------------------------------------------------------------------
# BibTeX parsing
# --------------------------------------------------------------------------

def _clean(value: str) -> str:
    value = " ".join(value.split())
    # Unwrap common text-formatting commands: \emph{KV} -> KV
    value = re.sub(
        r"\\(?:emph|textbf|textit|texttt|textsc|mathrm|operatorname)"
        r"\{([^{}]*)\}",
        r"\1",
        value,
    )
    # BibTeX protects capitalisation with braces: {KV} Cache -> KV Cache
    for _ in range(4):
        unwrapped = re.sub(r"\{([^{}]*)\}", r"\1", value)
        if unwrapped == value:
            break
        value = unwrapped
    value = re.sub(r"\\([{}&_%])", r"\1", value)
    value = value.replace(r"\"", '"')
    return value.strip()


def _read_value(text: str, i: int) -> tuple[str, int]:
    n = len(text)
    while i < n and text[i] in " \t\r\n":
        i += 1
    if i >= n:
        return "", i
    if text[i] == "{":
        depth, i, start = 1, i + 1, i + 1
        while i < n and depth:
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
            i += 1
        return text[start:max(start, i - 1)], i
    if text[i] == '"':
        i, start = i + 1, i + 1
        while i < n and text[i] != '"':
            i += 1
        return text[start:i], i + 1
    start = i
    while i < n and text[i] != ",":
        i += 1
    return text[start:i], i


def _parse_fields(body: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    i, n = 0, len(body)
    while i < n:
        while i < n and body[i] in " \t\r\n,":
            i += 1
        match = re.match(r"(\w+)\s*=\s*", body[i:])
        if not match:
            i += 1
            continue
        key = match.group(1).lower()
        i += match.end()
        raw, i = _read_value(body, i)
        fields[key] = _clean(raw)
    return fields


def _parse_bib_fallback(text: str) -> list[dict[str, str]]:
    """Dependency-free parser for ordinary BibTeX entries."""
    entries: list[dict[str, str]] = []
    for match in re.finditer(r"@(\w+)\s*\{\s*([^,\s]+)\s*,", text):
        i, depth, in_quotes = match.end(), 1, False
        while i < len(text) and depth:
            char = text[i]
            if char == '"' and (i == 0 or text[i - 1] != "\\"):
                in_quotes = not in_quotes
            elif not in_quotes:
                if char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
            i += 1
        body = text[match.end():max(match.end(), i - 1)]
        fields = _parse_fields(body)
        fields["citekey"] = match.group(2)
        fields["entry_type"] = match.group(1).lower()
        entries.append(fields)
    return entries


def parse_bib(path: Path) -> list[dict[str, str]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    try:
        import bibtexparser  # type: ignore

        if hasattr(bibtexparser, "parse_string"):
            # bibtexparser >= 2
            library = bibtexparser.parse_string(text)
            return [
                {
                    **{field.key.lower(): _clean(field.value) for field in entry.fields},
                    "citekey": entry.key,
                    "entry_type": entry.entry_type.lower(),
                }
                for entry in library.entries
            ]
        # bibtexparser 1.x
        database = bibtexparser.loads(text)
        return [
            {
                **{k.lower(): _clean(str(v)) for k, v in entry.items()},
                "entry_type": str(entry.get("ENTRYTYPE", "misc")).lower(),
            }
            for entry in database.entries
        ]
    except ImportError:
        global _FALLBACK_WARNED
        if not _FALLBACK_WARNED:
            print(
                "note: bibtexparser not installed, using the built-in BibTeX parser",
                file=sys.stderr,
            )
            _FALLBACK_WARNED = True
        return _parse_bib_fallback(text)
    except Exception as exc:  # noqa: BLE001 - degrade instead of failing the CI job
        print(
            f"note: bibtexparser could not parse {path.name} ({exc}); "
            "using the built-in BibTeX parser",
            file=sys.stderr,
        )
        return _parse_bib_fallback(text)


# --------------------------------------------------------------------------
# Formatting helpers
# --------------------------------------------------------------------------

def parse_year(raw: str) -> int:
    match = re.search(r"\b(\d{4})\b", raw or "")
    return int(match.group(1)) if match else 0


def render_contributor(account: str) -> str:
    account = account.strip().lstrip("@")
    return account or "未注明"


@dataclass(frozen=True)
class Entry:
    area: str
    number: int
    title: str
    year: int
    pdf: Path | None
    source: Path
    record: dict[str, str]
    contributor: str = ""
    needs_review: bool = False
    # Marker creation date (ISO). Keeps the numbering append-only: a paper
    # added later always gets a higher number than the existing ones.
    added: str = ""

    def numbered(self, number: int) -> "Entry":
        return Entry(
            area=self.area,
            number=number,
            title=self.title,
            year=self.year,
            pdf=self.pdf,
            source=self.source,
            record=self.record,
            contributor=self.contributor,
            needs_review=self.needs_review,
            added=self.added,
        )

    def render(self) -> str:
        """One line of the index: ``<n>： <GB/T 7714-2015 著录> : [<账号>]``."""
        pdf_url = None
        if self.pdf is not None:
            rel = self.pdf.relative_to(ROOT).as_posix()
            pdf_url = quote(rel, safe='/-._~')
        else:
            print(
                f"warning: no PDF found for {self.source.relative_to(ROOT).as_posix()}, "
                "rendering the reference without a link",
                file=sys.stderr,
            )
        reference = format_reference(self.record, pdf_url=pdf_url)
        line = f"{self.number}： {reference} : [{render_contributor(self.contributor)}]"
        if self.needs_review:
            line += "（BibTeX 自动生成，待核对）"
        # Two trailing spaces: a hard line break, so consecutive references do
        # not collapse into one paragraph on GitHub.
        return line + "  "


# --------------------------------------------------------------------------
# Aggregation
# --------------------------------------------------------------------------

def collect_entries() -> list[Entry]:
    if not PAPERS.is_dir():
        return []
    entries: list[Entry] = []
    for user_dir in sorted(PAPERS.iterdir()):
        if not user_dir.is_dir() or user_dir.name.startswith("."):
            continue

        # Group files by stem: <stem>.pdf / <stem>.bib / <stem>.research-area
        grouped: dict[Path, dict[str, list[Path]]] = {}
        for file_path in sorted(user_dir.iterdir()):
            if not file_path.is_file():
                continue
            suffix = file_path.suffix.lower()
            if suffix not in PAPER_SUFFIXES:
                continue
            base = file_path.with_suffix("")
            bucket = grouped.setdefault(base, {"bib": [], "pdf": []})
            bucket["bib" if suffix == ".bib" else "pdf"].append(file_path)

        for base in sorted(grouped):
            marker = read_marker(base)
            if marker is None or not marker.area:
                continue

            bib_files = grouped[base]["bib"]
            if not bib_files:
                print(
                    f"warning: {base.relative_to(ROOT).as_posix()}.pdf has no matching "
                    ".bib; skipped (run scripts/pdf_to_bib.py locally, or "
                    "'sh scripts/install_hooks.sh' and re-commit)",
                    file=sys.stderr,
                )
                continue
            bib_path = bib_files[0]
            pdf_files = grouped[base]["pdf"]
            pdf = pdf_files[0] if pdf_files else None
            # The CI-generated header is the single source of truth for the
            # "needs review" badge: fix the .bib, delete the header, rebuild.
            bib_head = bib_path.read_text(encoding="utf-8", errors="replace")[:400]
            # Only the header comment counts. A stub body may legitimately
            # contain words like "metadata unavailable"; matching those would
            # keep the badge alive after a human removed the header.
            needs_review = "%% AUTO-GENERATED" in bib_head

            for record in parse_bib(bib_path):
                entries.append(
                    Entry(
                        area=marker.area,
                        number=0,  # assigned per section in build_markdown()
                        title=record.get("title") or record.get("citekey") or base.name,
                        year=parse_year(record.get("year", "")),
                        pdf=pdf,
                        source=bib_path,
                        record=record,
                        contributor=marker.contributor,
                        needs_review=needs_review,
                        added=marker.added,
                    )
                )
    return entries


def build_markdown(entries: list[Entry]) -> str:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines = [
        "# GroupPaperCollecting 文献清单",
        "",
        f"> 本文件由提交 hook / GitHub Actions 自动生成，请勿手动编辑。最后更新于 {today}。",
        ">",
        "> A repository for students in our Group committing the reading Papers for Collecting.",
        "",
        *convention_lines(),
        "",
    ]

    if not entries:
        lines += ["目前尚无收录文献。", ""]
        return "\n".join(lines)

    groups: dict[str, list[Entry]] = {}
    for entry in entries:
        groups.setdefault(entry.area, []).append(entry)

    for area in sorted(groups, key=area_sort_key):
        lines += [f"## {area}", ""]
        ordered = sorted(
            groups[area],
            key=lambda item: (
                item.added,
                -item.year,
                item.title.lower(),
                item.source.as_posix(),
            ),
        )
        for number, entry in enumerate(ordered, start=1):
            lines.append(entry.numbered(number).render())
        lines.append("")
    return "\n".join(lines)


def write_readme(quiet: bool = False) -> bool:
    """Rebuild README.md. Returns True when the file changed."""
    content = build_markdown(collect_entries())
    if README.is_file() and README.read_text(encoding="utf-8") == content:
        if not quiet:
            print("README.md is already up to date.")
        return False
    README.write_text(content, encoding="utf-8")
    if not quiet:
        print(f"Wrote {README.relative_to(ROOT).as_posix()}.")
    return True


def main() -> int:
    write_readme()
    return 0


if __name__ == "__main__":
    sys.exit(main())
