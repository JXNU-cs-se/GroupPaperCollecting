#!/usr/bin/env python3
"""The commit-message contract: parse it, validate it, explain it.

One single implementation, used by

* ``.githooks/commit-msg``  -> blocks the commit locally, before anything is
  pushed, when the message does not carry the required fields;
* ``scripts/apply_local.py`` -> the same check, then writes the marker/README;
* ``scripts/parse_area.py``  -> the CI fallback for contributors who did not
  install the hooks (web upload, ``--no-verify``);
* ``scripts/build_readme.py`` -> renders the reminder at the top of README.md
  from :func:`convention_lines`, so the documentation cannot drift away from
  what the parser actually accepts.

Required shape (one line per paper)::

    1： WeSCE A Benchmark for Measuring Security : [AREA: Intelligence Software Engineering]  :  [贡献人 ： lihongweimail]

Four pieces of information must be present: the position number, the paper
file name, the ``[AREA: ...]`` bracket and the contributor's GitHub account.
Separators are accepted in both half-width and full-width forms, and the
contributor field may be written as ``贡献人`` or ``contributor``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

TEMPLATE = "该小节下的数字序号： <论文文件名> : [AREA: <研究方向>]  :  [贡献人 ： 项目成员的GitHub账号]"
EXAMPLE = (
    "1： WeSCE A Benchmark for Measuring Security : "
    "[AREA: Intelligence Software Engineering]  :  [贡献人 ： lihongweimail]"
)

# Tolerant on purpose: contributors type "[AREA: x]", "[ AREA: x ]" and the
# full-width "【AREA：x】" their input method produces. All mean the same thing.
AREA_RE = re.compile(r"[\[【]\s*AREA\s*[:：]\s*([^\]】\r\n]+?)\s*[\]】]", re.IGNORECASE)
CONTRIBUTOR_RE = re.compile(
    r"[\[【]?\s*(?:贡献人|投稿人|提交人|contributor|contributed\s*by)\s*[:：]\s*"
    r"@?([A-Za-z0-9](?:[A-Za-z0-9_-]{0,38}))\s*[\]】]?",
    re.IGNORECASE,
)
# "1：" / "1:" / "1." / "1、" — the separator is mandatory, so a title that
# really starts with a digit ("3D Gaussian Splatting") keeps its digit.
SEQ_RE = re.compile(r"^\s*(\d+)\s*[:：.、]\s*")


@dataclass(frozen=True)
class Declaration:
    seq: int
    paper: str
    area: str
    contributor: str
    line: str

    @property
    def complete(self) -> bool:
        return bool(self.seq and self.paper and self.area and self.contributor)

    def missing(self) -> list[str]:
        gaps: list[str] = []
        if not self.seq:
            gaps.append("数字序号")
        if not self.paper:
            gaps.append("论文文件名")
        if not self.area:
            gaps.append("`[AREA: <研究方向>]`")
        if not self.contributor:
            gaps.append("`[贡献人 ： <GitHub账号>]`")
        return gaps


def declarations_in(message: str) -> list[Declaration]:
    """Parse every ``[AREA: ...]`` declaration in a commit message.

    The text in front of the bracket is only treated as a *paper reference*
    when it ends with a colon; otherwise the bracket is prose
    (``docs: 说明 [AREA: ...] 的用法``) and the declaration carries no paper.
    """
    found: list[Declaration] = []
    for match in AREA_RE.finditer(message):
        area = " ".join(match.group(1).split())
        if not area:
            continue
        line_start = message.rfind("\n", 0, match.start()) + 1
        line_end = message.find("\n", match.end())
        if line_end == -1:
            line_end = len(message)
        line = message[line_start:max(match.end(), min(line_end, len(message)))]

        prefix = message[line_start:match.start()].strip()
        seq, paper = 0, ""
        if prefix.endswith((":", "：")):
            candidate = prefix[:-1].strip(" \t-—–·*#>")
            seq_match = SEQ_RE.match(candidate)
            if seq_match:
                seq = int(seq_match.group(1))
                candidate = candidate[seq_match.end():]
            candidate = candidate.strip()
            # Guard against a long prose line that merely ends with a colon.
            if candidate and len(candidate) <= 200 and "[" not in candidate:
                paper = candidate

        # The contributor normally sits on the same line, after the bracket.
        contributor = ""
        after = message[match.end():line_end]
        contrib_match = CONTRIBUTOR_RE.search(after)
        if not contrib_match:
            contrib_match = CONTRIBUTOR_RE.search(line, 0, match.start())
        if contrib_match:
            contributor = contrib_match.group(1)

        found.append(
            Declaration(seq=seq, paper=paper, area=area, contributor=contributor, line=line)
        )

    # A single declaration may put the contributor on its own line, e.g.
    #   1： xxx : [AREA: y]
    #   贡献人：alice
    if len(found) == 1 and not found[0].contributor:
        loose = CONTRIBUTOR_RE.search(message)
        if loose:
            first = found[0]
            found[0] = Declaration(
                seq=first.seq, paper=first.paper, area=first.area,
                contributor=loose.group(1), line=first.line,
            )
    return found


def areas_in(message: str) -> list[str]:
    """Unique, non-empty area names declared in a commit message, in order."""
    seen: list[str] = []
    for declaration in declarations_in(message):
        if declaration.area not in seen:
            seen.append(declaration.area)
    return seen


def validation_errors(message: str) -> list[str]:
    """Return human readable problems; an empty list means the message is fine."""
    declarations = declarations_in(message)
    if not declarations:
        return ["commit 注释里没有 `[AREA: <研究方向>]`"]

    errors: list[str] = []
    for declaration in declarations:
        gaps = declaration.missing()
        if gaps:
            errors.append(
                "commit 注释缺少 " + "、".join(gaps)
                + ("（当前行：" + declaration.line.strip() + "）" if declaration.line.strip() else "")
            )
    return errors


def help_text() -> str:
    """The message printed by the hook / CI when a commit message is rejected."""
    return (
        "commit 注释不符合规范，提交已被中止。\n"
        "\n"
        "必须按下面的格式写清 4 段信息（缺一不可）：\n"
        "\n"
        f"    {TEMPLATE}\n"
        "\n"
        "示例：\n"
        f"    {EXAMPLE}\n"
        "\n"
        "  - 数字序号：该论文在所属研究方向小节里的顺序号（由生成器最终编号，填当前条目数 + 1 即可）\n"
        "  - 论文文件名：papers/<你的GitHub用户名>/ 下的文件名，不含扩展名\n"
        "  - [AREA: ...]：研究方向名称，将作为 README 里的小节标题\n"
        "  - [贡献人 ： ...]：你的 GitHub 账号\n"
        "\n"
        "只差格式时不必重新 add 文件，直接改注释即可：\n"
        "    git commit --amend\n"
        "\n"
        "详见 CONTRIBUTING.md。"
    )


def convention_lines() -> list[str]:
    """The fixed reminder block at the top of README.md."""
    return [
        "## 提交前必读：commit 注释必须写全 4 段信息",
        "",
        "每次 commit 都必须在注释里写清下面这一行**核心信息**，缺任何一段，"
        "本地 hook 会**直接拒绝提交**并提示你改注释：",
        "",
        "```text",
        TEMPLATE,
        "```",
        "",
        "典型示例（对应 `papers/lihongwei/` 下的 WeSCE，"
        "`Intelligence Software Engineering` 小节的第 1 条）：",
        "",
        "```text",
        EXAMPLE,
        "```",
        "",
        "- **数字序号**：该论文在所属小节里的顺序号；README 中的编号由生成器按小节内顺序"
        "（先提交的在前）自动生成，避免重复或断号。",
        "- **论文文件名**：与 `papers/<你的用户名>/` 下的文件名一致（不含扩展名）；"
        "写论文标题也可以，脚本会做模糊匹配。",
        "- **`[AREA: ...]`**：研究方向名称，会成为 README 里的小节标题，请保持简短、稳定。"
        "**一次 commit 只写一个方向**，不同方向请分开提交。",
        "- **`[贡献人 ： ...]`**：你的 GitHub 账号，会显示在 README 对应条目的末尾。",
        "",
        "### 一次 commit 里发生了什么",
        "",
        "1. **校验注释**：缺上面任何一段信息，hook 立即中止提交并打印正确格式。",
        "2. **校验 BibTeX**：检查提交内容里的 `.bib` 是否存在、是否真的含有 `@` 条目；"
        "缺失或为空时，从同次提交的 PDF 里提取元数据生成 `.bib`。",
        "3. **写入方向标记**：生成 `<论文文件名>.research-area`，记录方向、贡献人、序号。",
        "4. **重建 README**：按 **GB/T 7714-2015** 著录该论文，写入对应研究方向小节，"
        "格式为 `<数字序号>： <GB/T 7714-2015 著录> : [<你的GitHub账号>]`。",
        "",
        "以上文件（PDF、`.bib`、`.research-area`、`README.md`）**落在同一个 commit 里**，"
        "push 之后 README 立即是最新的，不需要等下一次提交，也不用手动改 README。",
        "",
        "- **旧论文跳过、新论文照常归类**：commit 注释里写的是**已有论文**及其方向时，"
        "这条声明会被**识别并忽略**——那篇论文保持原小节，不会被移动，也不会重复出现；"
        "**尚未归类的新论文**仍按原行为写入 `[AREA: ...]` 对应的小节。",
        "- 首次 clone 后先执行一次 `sh scripts/install_hooks.sh` 安装 hook；"
        "没装 hook 时（例如网页上传）由 GitHub Actions 兜底完成第 2~4 步，"
        "但补出来的文件只能落在下一个 commit。",
        "- 完整目录结构与提交流程见 [CONTRIBUTING.md](CONTRIBUTING.md)。",
    ]


def _cli(argv: list[str]) -> int:
    """``python3 scripts/commit_contract.py "<commit message>"`` for a dry run."""
    if not argv:
        print("commit 注释模板：")
        print("    " + TEMPLATE)
        print("\n示例：")
        print("    " + EXAMPLE)
        print("\n把一条注释作为参数传入即可检查它是否合规：")
        print('    python3 scripts/commit_contract.py "1： xxx : [AREA: y]  :  [贡献人 ： bob]"')
        return 0

    message = " ".join(argv)
    declarations = declarations_in(message)
    if not declarations:
        print("✗ 没有找到 `[AREA: ...]`")
        print(help_text())
        return 1
    for declaration in declarations:
        print(
            f"序号={declaration.seq or '（缺）'}  "
            f"文件名={declaration.paper or '（缺）'}  "
            f"方向={declaration.area or '（缺）'}  "
            f"贡献人={declaration.contributor or '（缺）'}"
        )
    errors = validation_errors(message)
    if errors:
        print()
        for error in errors:
            print(f"✗ {error}")
        return 1
    print("✓ 注释合规")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(_cli(sys.argv[1:]))
