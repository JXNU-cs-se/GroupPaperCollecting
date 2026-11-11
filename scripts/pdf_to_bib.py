#!/usr/bin/env python3
"""PDF -> BibTeX generator: used by the pre-commit hook and for local previews.

Where generation happens
------------------------
In the contributor's local pre-commit hook (``.githooks/pre-commit``). The hook
calls this script with an explicit PDF path and ``--quiet``, then stages the
``.bib`` itself, so a PDF and its BibTeX always land in the SAME commit.

CI does **not** generate files any more. It only verifies the invariant:
``pdf_to_bib.py --check --fail`` exits 1 when some PDF has no same-named
``.bib``, which turns the "Resolve Research Area" workflow red and tells the
contributor to enable the hook and amend the commit.

This script NEVER runs git itself. Staging / committing / pushing is either the
hook's job or yours.

Quality contract
----------------
Metadata is best-effort. Every generated file starts with an
``%% AUTO-GENERATED`` header. ``build_readme.py`` detects that header and marks
the README entry as "待核对". A human should verify title / author / year /
cite key with a follow-up commit and delete the header; the badge then
disappears automatically. Generated stubs contain obvious ``REVIEW:`` values.

Metadata sources, tried in order
--------------------------------
1. ``pdf2bib`` (if installed)
2. DOI found in the PDF text -> Crossref (Accept: application/x-bibtex)
3. arXiv id found in the PDF text -> arXiv Atom API
4. title guessed from the first page -> Crossref bibliographic query
5. a minimal ``@misc`` stub with obvious REVIEW placeholders

Missing optional libraries or an unreachable network are never fatal: the
script degrades to the next source and finally to a reviewable stub, so the
PDF never gets stuck without a .bib.

Usage (from the repository root)
--------------------------------
    python3 scripts/pdf_to_bib.py --check          # report PDFs lacking .bib, write nothing
    python3 scripts/pdf_to_bib.py --check --fail   # CI gate: exit 1 when any .bib is missing
    python3 scripts/pdf_to_bib.py                 # local: generate drafts for all such PDFs
    python3 scripts/pdf_to_bib.py papers/alice/attention.pdf --quiet
    python3 scripts/pdf_to_bib.py --offline       # no network calls; stubs only
    python3 scripts/pdf_to_bib.py --ci --list-generated "$RUNNER_TEMP/bibs.txt"  # batch mode

Optional dependencies
---------------------
    python3 -m pip install -r requirements-pdf.txt
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAPERS = ROOT / "papers"

try:  # same directory when run as `python3 scripts/pdf_to_bib.py`
    from paper_index import has_bibtex_entries
except ImportError:  # pragma: no cover - keep the script standalone
    def has_bibtex_entries(path: Path) -> bool:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return False
        return bool(re.search(r"^[ \t]*@[A-Za-z]+[ \t]*[{(]", text, re.MULTILINE))

USER_AGENT = "GroupPaperCollecting-pdf-to-bib/2.0 (mailto: repo maintainers)"
TIMEOUT = 12

DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\"'<>\]\),;]+", re.IGNORECASE)
ARXIV_RE = re.compile(r"arXiv\s*[:：]?\s*(\d{4}\.\d{4,5})(?:v\d+)?", re.IGNORECASE)
SKIP_LINE_RE = re.compile(
    r"^(arxiv|doi|https?://|www\.|©|copyright|proceedings|accepted|abstract|"
    r"keywords|vol\.|ieee|acm|springer|downloaded|submitted|draft)",
    re.IGNORECASE,
)
STOP_WORDS = {
    "the", "and", "for", "with", "from", "that", "this", "are", "was", "using",
    "based", "towards", "toward", "into", "via", "study", "analysis", "novel",
}


def warn(message: str) -> None:
    print(f"note: {message}", file=sys.stderr)


# --------------------------------------------------------------------------
# PDF text
# --------------------------------------------------------------------------

def extract_text(pdf: Path, max_pages: int = 3) -> str:
    """Best-effort extraction of the first few pages."""
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError:
        pass
    else:
        try:
            reader = PdfReader(str(pdf))
            return "\n".join(
                (page.extract_text() or "") for page in reader.pages[:max_pages]
            )
        except Exception as exc:  # noqa: BLE001
            warn(f"pypdf could not read {pdf.name}: {exc}")

    try:
        from pdfminer.high_level import extract_text as pdfminer_text  # type: ignore
    except ImportError:
        pass
    else:
        try:
            return pdfminer_text(str(pdf), maxpages=max_pages)
        except Exception as exc:  # noqa: BLE001
            warn(f"pdfminer could not read {pdf.name}: {exc}")

    try:
        out = subprocess.run(
            ["pdftotext", "-f", "1", "-l", str(max_pages), str(pdf), "-"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return ""


def guess_title(text: str) -> str:
    for line in text.splitlines():
        line = " ".join(line.split())
        if len(line) < 12 or len(line) > 220:
            continue
        if SKIP_LINE_RE.match(line) or line.isdigit():
            continue
        return line
    return ""


# --------------------------------------------------------------------------
# Metadata backends
# --------------------------------------------------------------------------

def http_get(url: str, accept: str) -> str:
    request = urllib.request.Request(
        url, headers={"Accept": accept, "User-Agent": USER_AGENT}
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return response.read().decode("utf-8", "replace")


def via_pdf2bib(pdf: Path) -> tuple[str, str] | None:
    try:
        from pdf2bib import pdf2bib as run_pdf2bib  # type: ignore
    except ImportError:
        return None

    try:
        result = run_pdf2bib(str(pdf))
    except Exception as exc:  # noqa: BLE001 - pdf2bib has a volatile API
        warn(f"pdf2bib could not process {pdf.name}: {exc}")
        return None

    raw = ""
    if isinstance(result, str):
        raw = result
    elif isinstance(result, dict):
        for key in ("bibtex", "bib", "BibTeX", "entry"):
            value = result.get(key)
            if isinstance(value, str) and value.strip():
                raw = value
                break
    else:
        for attribute in ("bibtex", "bib"):
            value = getattr(result, attribute, None)
            if isinstance(value, str) and value.strip():
                raw = value
                break
    if "@" in raw:
        return raw, "pdf2bib"
    return None


def _safe(value: str) -> str:
    return " ".join(value.split()).replace("{", "(").replace("}", ")")


def crossref_json_to_bib(item: dict, doi: str) -> str:
    """Build a compact entry from a Crossref JSON work (negotiation fallback)."""
    title = _safe((item.get("title") or [""])[0])
    authors = " and ".join(
        " ".join(
            part for part in (
                (a.get("family", "") + ",") if a.get("family") else "",
                a.get("given", ""),
            ) if part
        ).strip()
        for a in item.get("author", [])
    )
    date_parts = (item.get("published", {}).get("date-parts") or [[None]])[0]
    year = str(date_parts[0]) if date_parts and date_parts[0] else ""
    container = _safe((item.get("container-title") or [""])[0])
    entry_type = "article" if container else "misc"
    fields = [
        ("title", title or "REVIEW: fill in the title"),
        ("author", authors or "REVIEW: fill in the authors"),
        ("year", year or "0000"),
    ]
    if container:
        key = "journal" if item.get("type") == "journal-article" else "booktitle"
        fields.append((key, container))
    for source_key, target_key in (("volume", "volume"), ("page", "pages")):
        if item.get(source_key):
            fields.append((target_key, str(item[source_key])))
    if doi:
        fields.append(("doi", doi))

    width = max(len(key) for key, _ in fields)
    lines = [f"@{entry_type}{{placeholder,"]
    for key, value in fields:
        lines.append(f"  {key.ljust(width)} = {{{value}}},")
    lines[-1] = lines[-1].rstrip(",")
    lines.append("}")
    return "\n".join(lines) + "\n"


def crossref_bibtex(doi: str) -> tuple[str, str]:
    encoded = urllib.parse.quote(doi, safe="")
    base = "https://api.crossref.org/works/" + encoded
    source = f"Crossref DOI {doi}"
    try:
        # Plain Accept negotiation returns 406 on some Crossref edges; the
        # explicit transform endpoint is reliable.
        raw = http_get(base + "/transform/application/x-bibtex", "application/x-bibtex")
        if "@" in raw:
            return raw, source
    except Exception as exc:  # noqa: BLE001
        warn(f"Crossref BibTeX transform for {doi} failed: {exc}")
    payload = json.loads(http_get(base, "application/json"))
    return crossref_json_to_bib(payload.get("message", {}), doi), source + " (JSON)"


def crossref_by_title(title: str) -> tuple[str, str] | None:
    url = (
        "https://api.crossref.org/works?rows=3&query.bibliographic="
        + urllib.parse.quote(title, safe="")
    )
    payload = json.loads(http_get(url, "application/json"))
    for item in payload.get("message", {}).get("items", []):
        doi = item.get("DOI")
        if not doi:
            continue
        candidate_title = " ".join((item.get("title") or [""])[0].split())
        if candidate_title and not title_similar(title, candidate_title):
            continue
        raw, _ = crossref_bibtex(doi)
        return raw, f"Crossref title search ({doi})"
    return None


def title_similar(guessed: str, candidate: str) -> bool:
    """Loose token overlap check, to avoid accepting a wrong Crossref hit."""
    def tokens(value: str) -> set[str]:
        return {
            word.lower()
            for word in re.findall(r"[A-Za-z0-9]{4,}", value)
            if word.lower() not in STOP_WORDS
        }

    left, right = tokens(guessed), tokens(candidate)
    # A loose match produces confidently-wrong BibTeX, which is worse than a
    # clearly marked stub. Require a strong overlap on the shorter side.
    if len(left) < 2 or len(right) < 2:
        return False
    return len(left & right) / min(len(left), len(right)) >= 0.6


def arxiv_bibtex(arxiv_id: str) -> tuple[str, str]:
    namespace = {"a": "http://www.w3.org/2005/Atom"}
    xml = http_get(
        "https://export.arxiv.org/api/query?id_list=" + urllib.parse.quote(arxiv_id),
        "application/atom+xml",
    )
    root = ET.fromstring(xml)
    entry = root.find("a:entry", namespace)
    if entry is None:
        raise ValueError("arXiv returned no entry")
    title = " ".join((entry.findtext("a:title", "", namespace) or "").split())
    authors = [
        " ".join((node.findtext("a:name", "", namespace) or "").split())
        for node in entry.findall("a:author", namespace)
    ]
    year = (entry.findtext("a:published", "", namespace) or "")[:4]
    key_hint = re.sub(r"[^A-Za-z0-9]", "", (authors[0].split()[-1] if authors else "arxiv") + year)
    body = (
        f"@misc{{{key_hint or 'arxiv' + arxiv_id.replace('.', '')},\n"
        f"  title        = {{{title}}},\n"
        f"  author       = {{{' and '.join(authors)}}},\n"
        f"  year         = {{{year}}},\n"
        f"  eprint       = {{{arxiv_id}}},\n"
        "  archivePrefix = {arXiv},\n"
        f"  url          = {{https://arxiv.org/abs/{arxiv_id}}}\n"
        "}\n"
    )
    return body, f"arXiv API {arxiv_id}"


# --------------------------------------------------------------------------
# BibTeX shaping
# --------------------------------------------------------------------------

def fields_from_bibtex(raw: str) -> dict[str, str]:
    def grab(name: str) -> str:
        match = re.search(
            rf"\b{name}\s*=\s*(?:\{{(.*?)\}}|\"(.*?)\"|([^,\n}}]+))",
            raw,
            re.IGNORECASE | re.DOTALL,
        )
        if not match:
            return ""
        value = next((group for group in match.groups() if group is not None), "")
        return " ".join(value.split())

    return {"title": grab("title"), "author": grab("author"), "year": grab("year")}


def make_citekey(stem: str, fields: dict[str, str]) -> str:
    author = fields.get("author", "")
    surname = ""
    if author:
        first = re.split(r"\s+and\s+", author, flags=re.IGNORECASE)[0].strip()
        if first:
            surname = first.split(",")[0].split()[-1] if "," in first else first.split()[-1]
    year_match = re.search(r"\b(1[5-9]\d{2}|20\d{2})\b", fields.get("year", ""))
    year = year_match.group(1) if year_match else ""
    words = [
        word for word in re.findall(r"[A-Za-z0-9]{3,}", fields.get("title", ""))
        if word.lower() not in STOP_WORDS
    ]
    key = re.sub(r"[^A-Za-z0-9]", "", surname.lower() + year + (words[0].lower() if words else ""))
    if len(key) >= 5:
        return key[:60]
    fallback = re.sub(r"[^A-Za-z0-9]+", "", stem)
    return (fallback or "paper").lower()[:60]


def set_citekey(raw: str, key: str) -> str:
    return re.sub(
        r"(@\w+\s*\{\s*)([^,\s]+)(\s*,)",
        lambda match: match.group(1) + key + match.group(3),
        raw,
        count=1,
    )


def stub_bibtex(key: str, title: str) -> str:
    safe_title = (title or "REVIEW: fill in the title").replace("{", "(").replace("}", ")")
    return (
        f"@misc{{{key},\n"
        f"  title  = {{{safe_title}}},\n"
        "  author = {REVIEW: fill in the authors},\n"
        "  year   = {0000},\n"
        "  note   = {Metadata unavailable -- please fill in title, author and year}\n"
        "}\n"
    )


def with_review_header(raw: str, source: str, pdf: Path) -> str:
    """Header doubles as the machine-readable 'needs review' flag.

    ``build_readme.py`` looks for ``AUTO-GENERATED`` in the first lines and
    renders a "待核对" badge. Removing this header after a human check clears
    the badge without touching any other script.
    """
    rel = pdf.relative_to(ROOT).as_posix()
    return (
        "%% AUTO-GENERATED by scripts/pdf_to_bib.py -- METADATA NEEDS HUMAN REVIEW\n"
        f"%% Metadata source: {source}\n"
        f"%% Source PDF: {rel}\n"
        "%% Generated by the 'Resolve Research Area' workflow and committed with the PDF.\n"
        "%% Verify title / author / year / cite key with a follow-up commit, then\n"
        "%% delete these %% lines to remove the '待核对' badge in README.md.\n"
        "\n" + raw.strip() + "\n"
    )


def build_bib(pdf: Path, offline: bool) -> tuple[str, str, bool]:
    """Return (bibtex text, metadata source, is_placeholder_stub)."""
    text = extract_text(pdf)
    doi_match = DOI_RE.search(text)
    doi = doi_match.group(0).rstrip(".,;:)]}>\"'") if doi_match else None
    arxiv_match = ARXIV_RE.search(text)
    arxiv_id = arxiv_match.group(1) if arxiv_match else None
    title = guess_title(text)

    raw: str | None = None
    source = ""

    if not offline:
        found = via_pdf2bib(pdf)
        if found:
            raw, source = found
        if raw is None and doi:
            try:
                raw, source = crossref_bibtex(doi)
            except Exception as exc:  # noqa: BLE001
                warn(f"Crossref lookup for {doi} failed: {exc}")
        if raw is None and arxiv_id:
            try:
                raw, source = arxiv_bibtex(arxiv_id)
            except Exception as exc:  # noqa: BLE001
                warn(f"arXiv lookup for {arxiv_id} failed: {exc}")
        if raw is None and title:
            try:
                found = crossref_by_title(title)
                if found:
                    raw, source = found
            except Exception as exc:  # noqa: BLE001
                warn(f"Crossref title search failed: {exc}")

    is_stub = raw is None
    if raw:
        fields = fields_from_bibtex(raw)
        key = make_citekey(pdf.stem, fields)
        body = set_citekey(raw, key)
    else:
        key = make_citekey(pdf.stem, {"title": title})
        body = stub_bibtex(key, title)
        source = "local stub (no reliable metadata found)"

    return with_review_header(body, source, pdf), source, is_stub


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def iter_pdfs(explicit: list[str]) -> list[Path]:
    if explicit:
        result: list[Path] = []
        for value in explicit:
            path = Path(value)
            if not path.is_absolute():
                path = ROOT / path
            if not path.is_file():
                warn(f"not a file, skipped: {value}")
                continue
            if path.suffix.lower() != ".pdf":
                warn(f"not a PDF, skipped: {value}")
                continue
            result.append(path)
        return result
    if not PAPERS.is_dir():
        return []
    found: list[Path] = []
    for user_dir in sorted(PAPERS.iterdir()):
        if user_dir.is_dir() and not user_dir.name.startswith("."):
            found.extend(sorted(user_dir.glob("*.pdf")))
    return found


def write_ci_outputs(
    generated: list[tuple[str, str, bool]], list_path: str | None
) -> None:
    """Emit the exact file list and machine-readable counts for the workflow."""
    if list_path:
        target = Path(list_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            "".join(path + "\n" for path, _, _ in generated), encoding="utf-8"
        )

    stubs = sum(1 for _, _, is_stub in generated if is_stub)
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write(f"count={len(generated)}\n")
            handle.write(f"stubs={stubs}\n")

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write("### PDF → BibTeX\n\n")
            if not generated:
                handle.write("- Every PDF already has a matching `.bib`.\n")
            else:
                for path, source, is_stub in generated:
                    flag = " **(占位条目，元数据未查到)**" if is_stub else ""
                    handle.write(f"- `{path}` — {source}{flag}\n")
                handle.write(
                    "\n> 这些 `.bib` 由脚本自动生成并与 PDF 一同提交。请尽快人工核对 "
                    "`title / author / year / cite key`，修正后删除文件头的 `%%` 注释行，"
                    "README 中的「待核对」标记即会消失。\n"
                )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate <stem>.bib for PDFs that have none (pre-commit hook + local tool)."
    )
    parser.add_argument("pdfs", nargs="*", help="PDF paths relative to the repository root")
    parser.add_argument("--check", action="store_true", help="only report PDFs missing a .bib")
    parser.add_argument(
        "--fail", action="store_true",
        help="with --check: exit 1 when a PDF has no matching .bib (CI gate)",
    )
    parser.add_argument("--offline", action="store_true", help="skip all network lookups")
    parser.add_argument(
        "--force", action="store_true",
        help="regenerate even when a .bib already exists (used by the pre-commit "
             "hook when the file exists but contains no BibTeX entry)",
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="suppress the trailing review checklist (used by the pre-commit hook)",
    )
    parser.add_argument(
        "--ci", action="store_true",
        help="batch mode: also emit GITHUB_OUTPUT / GITHUB_STEP_SUMMARY metadata",
    )
    parser.add_argument(
        "--list-generated", metavar="FILE",
        help="batch mode: write the generated .bib paths, one per line",
    )
    args = parser.parse_args()

    # A .bib only counts when it really holds BibTeX. An empty or half-written
    # file is the same problem as a missing one, and is regenerated too.
    candidates = iter_pdfs(args.pdfs)
    if args.force:
        missing = candidates
    else:
        missing = [
            pdf for pdf in candidates
            if not has_bibtex_entries(pdf.with_suffix(".bib"))
        ]

    if not missing:
        print("Every PDF already has a usable .bib. Nothing to do.")
        if args.ci:
            write_ci_outputs([], args.list_generated)
        return 0

    if args.check:
        print(f"{len(missing)} PDF(s) without a usable .bib (missing or no @entry):")
        for pdf in missing:
            print(f"  - {pdf.relative_to(ROOT).as_posix()}")
        if args.fail:
            print(
                "\nERROR: every PDF must be committed together with a same-named "
                ".bib that contains at least one BibTeX entry.\n"
                "Enable the pre-commit hook once per clone:\n"
                "    sh scripts/install_hooks.sh\n"
                "then stage the PDF again and amend the commit:\n"
                "    git add <the pdf> && git commit --amend --no-edit",
                file=sys.stderr,
            )
        else:
            print("\nRun without --check to generate the missing .bib files.")
        if args.ci:
            write_ci_outputs([], args.list_generated)
        return 1 if args.fail else 0

    generated: list[tuple[str, str, bool]] = []
    for pdf in missing:
        content, source, is_stub = build_bib(pdf, offline=args.offline)
        target = pdf.with_suffix(".bib")
        target.write_text(content, encoding="utf-8")
        generated.append((target.relative_to(ROOT).as_posix(), source, is_stub))

    for path, source, is_stub in generated:
        flag = "  [STUB]" if is_stub else ""
        print(f"[generated] {path}   (source: {source}){flag}")

    if args.ci:
        write_ci_outputs(generated, args.list_generated)
        if not args.quiet:
            print(
                f"\nGenerated {len(generated)} .bib file(s). Stage them with the PDF "
                "so both land in the same commit."
            )
    elif not args.quiet:
        print(
            "\n" + "=" * 72 + "\n"
            "These .bib files carry an AUTO-GENERATED header: metadata is best-effort.\n"
            "  1. Verify title / author / year / cite key.\n"
            "  2. Delete the %% header lines to clear the README '待核对' badge.\n"
            "  3. Stage the .bib together with the PDF so both share one commit:\n"
            '       git add "<pdf>" "<bib>" && git commit\n'
            "     (the commit message must carry the full declaration, see CONTRIBUTING.md)\n"
            "The pre-commit hook does step 3 for you when you stage only the PDF.\n"
            "CI never generates or commits a .bib; it only verifies that one exists.\n"
            + "=" * 72
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
