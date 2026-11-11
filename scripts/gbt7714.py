#!/usr/bin/env python3
"""Render a BibTeX record as a GB/T 7714-2015 style reference.

The README lists each paper as::

    <序号>： <GB/T 7714-2015 著录> : [<贡献人 GitHub 账号>]

GB/T 7714-2015 essentials implemented here:

* 著者: surname in full capitals followed by initials without periods
  (``ZHANG Z``); more than three authors are truncated to the first three plus
  ``et al.`` (``等`` when the names are Chinese);
* 文献类型标识: ``[J]`` 期刊, ``[C]`` 会议论文, ``[M]`` 专著, ``[D]`` 学位论文,
  ``[R]`` 报告, ``[S]`` 标准, ``[P]`` 专利, ``[EB/OL]`` 电子/在线资源;
* 会议论文用 ``//`` 引出论文集, 出版项写作 ``出版地: 出版者, 年: 页码.``;
* 期刊写作 ``刊名, 年, 卷(期): 起止页码.``

Metadata is best-effort: a field that is missing is simply omitted, so a
generated stub still produces a readable (if incomplete) reference instead of
an exception. Anything the generator could not fill in is flagged in the README
with「BibTeX 自动生成，待核对」, and the fix is to complete the ``.bib``.
"""

from __future__ import annotations

import re

# BibTeX entry type -> GB/T 7714-2015 文献类型标识
TYPE_MAP = {
    "article": "J",
    "inproceedings": "C",
    "conference": "C",
    "proceedings": "C",
    "book": "M",
    "inbook": "M",
    "incollection": "M",
    "phdthesis": "D",
    "mastersthesis": "D",
    "thesis": "D",
    "techreport": "R",
    "report": "R",
    "standard": "S",
    "patent": "P",
    "online": "EB/OL",
    "electronic": "EB/OL",
    "www": "EB/OL",
    "misc": "EB/OL",
    "unpublished": "Z",
}

CJK_RE = re.compile(r"[\u3400-\u9fff]")
PERIOD_END = re.compile(r"[.。．]$")


def _tidy(value: str) -> str:
    value = " ".join((value or "").split())
    return value.strip(" .。")


def _authors(raw: str) -> tuple[str, bool]:
    """Return ``(formatted, is_chinese)`` for a BibTeX ``author`` field."""
    if not raw or raw.strip().upper().startswith("REVIEW"):
        return "", False
    parts = [p.strip() for p in re.split(r"\s+and\s+", raw, flags=re.I) if p.strip()]
    if not parts:
        return "", False

    chinese = bool(CJK_RE.search(parts[0]))
    names: list[str] = []
    truncated = False
    for part in parts[:3]:
        if part.lower().replace(".", "") == "others":
            truncated = True
            break
        names.append(part if CJK_RE.search(part) else _western_name(part))
    if len(parts) > 3:
        truncated = True
    if not names:
        return "", chinese
    joined = ", ".join(names)
    if truncated:
        joined += "，等" if chinese else ", et al"
    return joined, chinese


def _western_name(name: str) -> str:
    """``Zhiyu Zhang`` -> ``ZHANG Z``; ``Zhang, Zhiyu`` -> ``ZHANG Z``."""
    name = name.replace("~", " ").strip()
    if "," in name:
        surname, _, given = name.partition(",")
    else:
        bits = name.split()
        if len(bits) == 1:
            return bits[0].upper()
        surname, given = bits[-1], " ".join(bits[:-1])
    surname = surname.strip()
    initials = []
    for token in re.split(r"[\s.\-]+", given.strip()):
        if token:
            initials.append(token[0].upper())
    return surname.upper() + (" " + " ".join(initials) if initials else "")


def _pages(raw: str) -> str:
    return _tidy(raw).replace("--", "-").replace("–", "-")


def _serial(record: dict[str, str]) -> str:
    """``, 2026, 12(3): 45-56`` — the part after the document type marker."""
    year = _tidy(record.get("year", ""))
    volume = _tidy(record.get("volume", ""))
    number = _tidy(record.get("number", ""))
    pages = _pages(record.get("pages", ""))

    tail = ""
    if year:
        tail += f", {year}"
    if volume:
        tail += f", {volume}"
    if number:
        tail += f"({number})"
    if pages:
        tail += f": {pages}"
    return tail


def _publisher(record: dict[str, str]) -> str:
    address = _tidy(record.get("address", "") or record.get("location", ""))
    publisher = _tidy(
        record.get("publisher", "")
        or record.get("school", "")
        or record.get("institution", "")
        or record.get("organization", "")
    )
    if address and publisher:
        return f"{address}: {publisher}"
    return publisher or address


def format_reference(record: dict[str, str], pdf_url: str | None = None) -> str:
    """Return one GB/T 7714-2015 style reference, without the leading number.

    ``pdf_url`` turns the title into a Markdown link while leaving the visible
    text in standard form.
    """
    entry_type = (record.get("entry_type") or "misc").lower()
    kind = TYPE_MAP.get(entry_type, "Z")

    authors, _chinese = _authors(record.get("author", ""))
    title = _tidy(record.get("title", "")) or "（题名缺失）"
    if pdf_url:
        title = f"[{_md_escape(title)}]({pdf_url})"

    journal = _tidy(record.get("journal", "") or record.get("journaltitle", ""))
    booktitle = _tidy(record.get("booktitle", ""))
    eprint = _tidy(record.get("eprint", ""))
    year = _tidy(record.get("year", ""))
    publisher = _publisher(record)
    url = _tidy(record.get("url", ""))

    # arXiv preprints carry no journal: cite them through the identifier.
    if not journal and eprint:
        journal = f"arXiv preprint arXiv:{eprint}"
        if kind == "EB/OL":
            kind = "J"

    if kind == "J":
        source = journal or "（刊名待补）"
        rest = source + _serial(record)
    elif kind == "C":
        venue = booktitle or "（会议名称待补）"
        rest = f"//{venue}"
        if publisher:
            rest += f". {publisher}"
        if year:
            rest += f", {year}"
        pages = _pages(record.get("pages", ""))
        if pages:
            rest += f": {pages}"
    elif kind in {"M", "D", "R", "S", "P"}:
        rest = publisher or "（出版者待补）"
        if year:
            rest += f", {year}" if rest else year
    else:  # EB/OL and anything unknown
        rest = publisher
        if year:
            rest += f", {year}" if rest else year
        if url:
            rest += f". {url}" if rest else url

    head = f"{authors}. " if authors else ""
    body = f"{title}[{kind}]"
    if kind == "C":
        # GB/T 7714-2015: 会议论文用 "//" 直接引出论文集，中间不加句点。
        body += rest
    elif rest:
        body += f". {rest}"
    body = body.rstrip()
    if not PERIOD_END.search(body):
        body += "."
    return head + body


def _md_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")
