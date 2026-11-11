#!/usr/bin/env python3
"""Local half of the pipeline: validate the message, then finish the index.

Split across two hooks because of how git builds a commit:

* ``.githooks/commit-msg`` runs *before* the commit object exists. Git has
  already taken its snapshot of the index, so files staged here would only land
  in the **next** commit — exactly the "README is one commit behind" bug this
  redesign fixes. This stage therefore only *validates* (``--check-only``) and
  aborts the commit when the message is incomplete.
* ``.githooks/post-commit`` runs right after the commit is written. It writes
  the ``.research-area`` marker, rebuilds README.md, stages both and folds them
  into the commit that was just created with ``git commit --amend --no-edit``.
  The result is a single commit containing PDF + BibTeX + marker + README.

BibTeX itself is handled one step earlier by ``.githooks/pre-commit`` (index
changes made there *do* make it into the commit): a missing or empty ``.bib``
is generated from the staged PDF and staged.

Nothing here pushes; the amend is local and happens before any push.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import build_readme
from commit_contract import Declaration, declarations_in, help_text, validation_errors
from paper_index import (
    PAPER_SUFFIXES,
    ROOT,
    has_bibtex_entries,
    marker_for,
    read_marker,
    title_matches_paper,
    write_marker,
)

PAPER_DIR = "papers/"
# Messages that legitimately do not describe a paper.
BOT_PREFIXES = ("Merge ", "Revert ", "[skip ci]", "chore: resolve research areas")


def git(*args: str, check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=False
    )


def _stems_from(paths: list[str]) -> list[Path]:
    bases: dict[Path, None] = {}
    for raw in paths:
        raw = raw.strip()
        if not raw:
            continue
        # git prints paths relative to the repository root; make them absolute
        # so they can be compared with ROOT everywhere else in the pipeline.
        path = ROOT / raw
        if path.suffix.lower() not in PAPER_SUFFIXES:
            continue
        # Flat layout only: papers/<user>/<file>. A PDF in a nested directory
        # is a leftover from the old layout and is not part of the index.
        try:
            parts = path.relative_to(ROOT).parts
        except ValueError:
            continue
        if len(parts) != 3 or parts[0] != "papers":
            continue
        bases.setdefault(path.with_suffix(""), None)
    return sorted(bases)


def staged_stems() -> list[Path]:
    """Stems of the papers staged in the index (used before the commit exists)."""
    result = git(
        "-c", "core.quotePath=false",
        "diff", "--cached", "--name-only", "-z", "--diff-filter=AMR",
        "--", PAPER_DIR,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git diff --cached failed")
    return _stems_from(result.stdout.split("\0"))


def head_stems() -> list[Path]:
    """Stems of the papers in the commit at HEAD (used from post-commit)."""
    result = git(
        "-c", "core.quotePath=false",
        "diff-tree", "--root", "--no-commit-id", "--name-only", "-z",
        "--diff-filter=AMR", "-r", "HEAD", "--", PAPER_DIR,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git diff-tree failed")
    return _stems_from(result.stdout.split("\0"))


def read_message(args: argparse.Namespace) -> str:
    if args.message is not None:
        return args.message
    if args.message_file:
        return Path(args.message_file).read_text(encoding="utf-8", errors="replace")
    return sys.stdin.read()


def is_exempt(message: str) -> bool:
    """Merge / revert / bot commits do not describe a paper."""
    stripped = message.strip()
    if not stripped:
        return False
    if (ROOT / ".git" / "MERGE_HEAD").exists():
        return True
    return stripped.startswith(BOT_PREFIXES)


def plan(
    message: str, bases: list[Path]
) -> tuple[list[tuple[Path, Declaration]], list[str], list[str]]:
    """Split the staged papers into (to write, ignored, problems)."""
    declarations = declarations_in(message)
    to_write: list[tuple[Path, Declaration]] = []
    ignored: list[str] = []
    problems: list[str] = []

    for base in bases:
        rel = base.relative_to(ROOT).as_posix()
        existing = read_marker(base)
        if existing is not None and existing.area:
            # "旧论文及其方向" is recognised and ignored: the paper keeps its
            # section, it is never moved and never listed twice.
            ignored.append(
                f"`{rel}` 已有方向 **{existing.area}**，本次声明被忽略（保持原小节）"
            )
            continue

        # Without BibTeX there is nothing to cite: the paper would show up as
        # an empty reference. pre-commit normally guarantees the .bib, so this
        # only triggers when the hooks were bypassed (--no-verify, web upload).
        if not has_bibtex_entries(base.with_suffix(".bib")):
            ignored.append(
                f"`{rel}` 没有可用的 .bib，已跳过（装好 hook 后重新提交，"
                "或运行 `python3 scripts/pdf_to_bib.py <pdf>`）"
            )
            continue

        matches = [d for d in declarations if title_matches_paper(d.paper, base)]
        areas = {d.area for d in matches}
        if not matches:
            problems.append(
                f"`{rel}` 没有出现在 commit 注释里；请为它单独写一行 "
                "`<序号>： <论文文件名> : [AREA: <研究方向>] : [贡献人 ： <GitHub账号>]`"
            )
        elif len(areas) > 1:
            problems.append(
                f"`{rel}` 在 commit 注释里被声明了多个方向："
                + "、".join(f"`{area}`" for area in sorted(areas))
                + "（一次 commit 只能有一个方向，请分开提交）"
            )
        else:
            to_write.append((base, matches[0]))
    return to_write, ignored, problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate the commit message and keep the paper index in sync."
    )
    parser.add_argument("--message-file", help="path to .git/COMMIT_EDITMSG (commit-msg hook)")
    parser.add_argument("--message", help="commit message given inline (post-commit hook)")
    parser.add_argument(
        "--from-head", action="store_true",
        help="look at the commit at HEAD instead of the index (post-commit)",
    )
    parser.add_argument(
        "--check-only", action="store_true",
        help="validate the message and stop; writes nothing (commit-msg)",
    )
    parser.add_argument(
        "--amend", action="store_true",
        help="fold the generated files into HEAD with `git commit --amend --no-edit`",
    )
    parser.add_argument(
        "--quiet", action="store_true", help="only print problems and a one-line summary"
    )
    args = parser.parse_args(argv)

    message = read_message(args)
    if is_exempt(message):
        return 0

    bases = head_stems() if args.from_head else staged_stems()
    if not bases:
        # Nothing under papers/: this commit cannot affect the index.
        return 0

    # Already categorised papers never need a declaration: a commit that only
    # touches them (fixing a typo in a .bib, re-committing a PDF) must not be
    # blocked, and their section must not change.
    unmarked = [base for base in bases if read_marker(base) is None]
    if not unmarked:
        if not args.quiet and not args.check_only:
            print("· 本次提交涉及的论文都已有方向标记，README 与标记无需改动。")
        return 0

    errors = validation_errors(message)
    if errors:
        print("✗ commit 注释不合规：", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        print("", file=sys.stderr)
        print(help_text(), file=sys.stderr)
        if args.check_only:
            print("提交已中止。请修改注释后重新提交。", file=sys.stderr)
            return 1
        # post-commit cannot abort: the commit exists already. Say so loudly
        # and leave the index alone so the contributor can fix it by hand.
        print(
            "注意：提交已经生成（--no-verify 跳过了 commit-msg 校验），"
            "README 与方向标记都没有更新。修正注释后再提交一次即可：\n"
            "    git commit --amend",
            file=sys.stderr,
        )
        return 0

    to_write, ignored, problems = plan(message, bases)
    if problems:
        print("✗ 无法确定以下论文的研究方向：", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        print("", file=sys.stderr)
        print(help_text(), file=sys.stderr)
        if args.check_only:
            print("提交已中止。请修改注释后重新提交。", file=sys.stderr)
            return 1
        return 0

    if args.check_only:
        for base, declaration in to_write:
            print(
                f"· 校验通过：`{base.relative_to(ROOT).as_posix()}` → "
                f"**{declaration.area}**（贡献人 @{declaration.contributor}）"
            )
        return 0

    for line in ignored:
        print(f"· {line}")

    written: list[str] = []
    for base, declaration in to_write:
        marker = write_marker(
            base,
            area=declaration.area,
            contributor=declaration.contributor,
            seq=declaration.seq,
        )
        written.append(
            f"`{marker.relative_to(ROOT).as_posix()}` → **{declaration.area}**"
            f"（贡献人 @{declaration.contributor}）"
        )

    staged: list[str] = [marker_for(base).relative_to(ROOT).as_posix() for base, _ in to_write]
    readme_changed = build_readme.write_readme(quiet=args.quiet)
    if readme_changed:
        staged.append("README.md")

    if not staged:
        return 0

    result = git("add", "--", *staged)
    if result.returncode != 0:
        print(
            "✗ 无法把生成的文件加入本次提交：\n" + (result.stderr or "").strip(),
            file=sys.stderr,
        )
        return 1

    if not args.quiet:
        if written:
            print("已写入方向标记：")
            for line in written:
                print("  · " + line)
        if readme_changed:
            print("已重建 README.md。")

    if args.amend:
        amend = git("commit", "--amend", "--no-edit", "--no-verify", "--quiet")
        if amend.returncode != 0:
            print(
                "✗ 无法把 README/标记并入本次提交：\n" + (amend.stderr or "").strip(),
                file=sys.stderr,
            )
            print(
                "  生成的文件仍在暂存区，手动并入：git commit --amend --no-edit",
                file=sys.stderr,
            )
            return 1
        if not args.quiet:
            print("已把 README.md 与方向标记并入本次提交（同一个 commit）。")

    if not args.quiet:
        print(
            "提示：README 里的序号由生成器按小节内顺序自动编号，"
            "commit 注释里的序号仅作人工核对。"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
