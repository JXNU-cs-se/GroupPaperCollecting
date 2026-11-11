#!/usr/bin/env python3
"""Aggregate paper entries by research area and regenerate README.md.

Runs in the "Build README" workflow whenever a ``<stem>.research-area`` marker
is pushed, or when the workflow is dispatched by the "Resolve Research Area"
workflow (a GITHUB_TOKEN push cannot itself trigger another workflow).

Layout: ``papers/<user>/<stem>.pdf`` + ``<stem>.bib`` + ``<stem>.research-area``.
Files are matched by stem (the file name without its extension); file names may
contain spaces, so PDF links are percent-encoded.

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

ROOT = Path(__file__).resolve().parent.parent
PAPERS = ROOT / "papers"
README = ROOT / "README.md"
MARKER_SUFFIX = ".research-area"
PAPER_SUFFIXES = {".bib", ".pdf"}


def marker_for(base: Path) -> Path:
    return base.parent / (base.name + MARKER_SUFFIX)


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
    for match in re.finditer(r"@\w+\s*\{\s*([^,\s]+)\s*,", text):
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
        fields["citekey"] = match.group(1)
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
                }
                for entry in library.entries
            ]
        # bibtexparser 1.x
        database = bibtexparser.loads(text)
        return [
            {**{k.lower(): _clean(str(v)) for k, v in entry.items()}}
            for entry in database.entries
        ]
    except ImportError:
        print(
            "note: bibtexparser not installed, using the built-in BibTeX parser",
            file=sys.stderr,
        )
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

def format_authors(raw: str) -> str:
    # Stubs generated without metadata carry an obvious REVIEW placeholder;
    # render it as a clear to-do instead of pretending "authors" is a surname.
    if not raw or raw.strip().upper().startswith("REVIEW"):
        return "待补作者"
    parts = [part.strip() for part in re.split(r"\s+and\s+", raw, flags=re.I) if part.strip()]
    if not parts:
        return "未知作者"
    first = parts[0]
    surname = first.split(",")[0].strip() if "," in first else first.split()[-1]
    surname = surname.strip("{} ").strip()
    if not surname:
        return "未知作者"
    if surname.lower() == "others":
        return "et al."
    return surname + " et al." if len(parts) > 1 else surname


def parse_year(raw: str) -> int:
    match = re.search(r"\b(\d{4})\b", raw or "")
    return int(match.group(1)) if match else 0


def md_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")


@dataclass(frozen=True)
class Entry:
    area: str
    title: str
    authors: str
    year: int
    pdf: Path | None
    source: Path
    needs_review: bool = False

    def render(self) -> str:
        title = md_escape(self.title)
        if self.pdf is not None:
            rel = self.pdf.relative_to(ROOT).as_posix()
            title = f"[{title}]({quote(rel, safe='/-._~')})"
        else:
            print(
                f"warning: no PDF found for {self.source.relative_to(ROOT).as_posix()}, "
                "rendering title without a link",
                file=sys.stderr,
            )
        year = str(self.year) if self.year else "n.d."
        line = f"- {title} — {self.authors} — {year}"
        if self.needs_review:
            line += "（BibTeX 自动生成，待核对）"
        return line


# --------------------------------------------------------------------------
# Fixed header: the commit message contract
# --------------------------------------------------------------------------
# This block is part of the generator on purpose. README.md is rebuilt from
# scratch on every run, so a hand-written notice would be erased by the first
# CI rebuild. Keeping it here makes the rule permanent and impossible to drift
# away from what scripts/parse_area.py actually parses.

COMMIT_CONVENTION = [
    "## 提交前必读：commit 注释必须声明研究方向",
    "",
    "成员提交论文时，**commit 注释中必须写上 `[AREA: ...]`**，格式为：",
    "",
    "```text",
    "<论文标题> : [AREA: <研究方向>]",
    "```",
    "",
    "典型示例（本条对应 `papers/lihongwei/` 下的 WeSCE）：",
    "",
    "```text",
    "WeSCE A Benchmark for Measuring Security : [AREA: Intelligence Software Engineering]",
    "```",
    "",
    "- `[AREA: ...]` 里的方向名会被写成该论文的 `<文件名>.research-area` 标记，"
    "并作为下面每个小节的标题，请保持简短、稳定。",
    "- **一次 commit 只写一个方向**；不同方向的论文请分开提交，否则 CI 会判为冲突。",
    "- 漏写 `[AREA: ...]` 时 CI 会**失败（红色 ✗）**，补正方式："
    "`git add <论文> && git commit --amend --no-edit` 后重新 push。",
    "- 论文与同名 `.bib` 必须在**同一个 commit** 中提交；首次 clone 后先执行 "
    "`sh scripts/install_hooks.sh` 安装 pre-commit hook，缺 `.bib` 时会在提交前自动生成。",
    "- 若 commit 注释里写了**已有论文**的方向（复制模板、顺带提及、或修改旧论文时又写一遍），"
    "该声明会被**识别并忽略**：那篇论文保持原小节，不会被移动，也不会重复出现在新方向里。"
    "只有**尚未归类**的新论文才会使用 `[AREA: ...]`。",
    "- 完整目录结构与贡献流程见 [CONTRIBUTING.md](CONTRIBUTING.md)。",
]


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
            marker = marker_for(base)
            if not marker.is_file():
                continue
            area = " ".join(marker.read_text(encoding="utf-8").split())
            if not area:
                print(
                    f"warning: empty marker at {marker.relative_to(ROOT).as_posix()}, skipped",
                    file=sys.stderr,
                )
                continue

            bib_files = grouped[base]["bib"]
            if not bib_files:
                print(
                    f"warning: {base.relative_to(ROOT).as_posix()}.pdf has no matching "
                    ".bib; skipped (the Resolve Research Area workflow generates it, "
                    "or run scripts/pdf_to_bib.py locally)",
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
                        area=area,
                        title=record.get("title") or record.get("citekey") or base.name,
                        authors=format_authors(record.get("author", "")),
                        year=parse_year(record.get("year", "")),
                        pdf=pdf,
                        source=bib_path,
                        needs_review=needs_review,
                    )
                )
    return entries


def build_markdown(entries: list[Entry]) -> str:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines = [
        "# GroupPaperCollecting 文献清单",
        "",
        f"> 本文件由 GitHub Actions 自动生成，请勿手动编辑。最后更新于 {today}。",
        ">",
        "> A repository for students in our Group committing the reading Papers for Collecting.",
        "",
        *COMMIT_CONVENTION,
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
        for entry in sorted(
            groups[area],
            key=lambda item: (-item.year, item.title.lower(), item.source.as_posix()),
        ):
            lines.append(entry.render())
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    content = build_markdown(collect_entries())
    if README.is_file() and README.read_text(encoding="utf-8") == content:
        print("README.md is already up to date.")
        return 0
    README.write_text(content, encoding="utf-8")
    print(f"Wrote {README.relative_to(ROOT).as_posix()}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
