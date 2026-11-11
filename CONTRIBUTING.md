# 论文提交规范

本仓库用 **commit message 声明研究方向**，提交时由本地 git hook 自动完成三件事：补齐 BibTeX、写入方向标记、把论文按 GB/T 7714-2015 格式写进 `README.md` 的对应小节。
成员只需放好文件、写对 commit 注释，**不需要**（也不要）手动编辑 `README.md`，多人同时提交不会产生 Git 冲突。

**三条硬规则：**

1. **先装一次 hook**（每个 clone 一次）：`sh scripts/install_hooks.sh`
2. **commit 注释必须写全 4 段信息**：数字序号、论文文件名、`[AREA: ...]`、`[贡献人 ： ...]`。缺任何一段，**本地直接拒绝提交**并打印正确格式。
3. **不要用 `--no-verify`**：它会同时跳过注释校验与 BibTeX 生成，只能等 CI 兜底，补出来的文件会落在下一个 commit。

---

## 一、一次提交的完整流程

```text
git add papers/alice/attention.pdf          ← 只 add PDF 就够了
git commit -m "3： attention : [AREA: 大模型推理优化]  :  [贡献人 ： alice]"
        │
        ├─ pre-commit   ① 检查暂存区 PDF 有没有同名 .bib，有没有真正的 @ 条目
        │               ② 没有 → 调 scripts/pdf_to_bib.py 从 PDF 提取元数据生成 .bib
        │               ③ 把 .bib 加入暂存区（PDF 与 bib 同 commit）
        │
        ├─ commit-msg   ④ 校验注释 4 段信息，缺任何一段 → 中止提交并打印模板
        │
        ├─ commit       ⑤ 生成 commit（PDF + bib）
        │
        └─ post-commit  ⑥ 写 <stem>.research-area（方向 + 贡献人 + 序号）
                        ⑦ 重建 README.md（GB/T 7714-2015 著录 + 序号 + 贡献人）
                        ⑧ git add 两个文件 + git commit --amend
                           → PDF / bib / 标记 / README 全部落在**同一个 commit**
```

push 之后 README 就是最新的，**不需要等下一次提交**，也不用手动 pull 再改。

> 为什么第 ⑥ 步在 post-commit：git 在 pre-commit 之后就锁定了本次提交的索引快照，在 `commit-msg` 里 `git add` 的文件只会进入**下一次**提交——这正是「README 总比论文晚一个 commit」的老问题。放到 post-commit 再 `--amend`，才能保证同一个 commit。

---

## 二、目录结构：每人一个目录，文件平铺

每个成员只在 `papers/` 下建**一个以自己 GitHub 用户名命名的目录**，把论文 PDF 和对应的 `.bib` **直接放进去**，不为每篇论文单独建子目录：

```text
papers/
├── alice/
│   ├── attention.pdf                    ← 只 add 这个就够了
│   ├── attention.bib                    ← hook 生成或你自己写
│   ├── attention.research-area          ← hook 生成（JSON，记录方向/贡献人）
│   ├── smith2024attention.pdf
│   ├── smith2024attention.bib
│   └── smith2024attention.research-area
└── bob/
    ├── lee2025robust.pdf
    ├── lee2025robust.bib
    └── lee2025robust.research-area
```

规则：

- **PDF 与 `.bib` 同名**（只有扩展名不同），脚本按「文件名去掉扩展名」关联二者。
- 建议用简短的 cite key 作文件名（如 `smith2024attention`）。**允许文件名含空格**（如 `WeSCE A Benchmark for Measuring Security.pdf`），README 里的链接会自动做 URL 编码。
- 一个 `.bib` 文件只放一条文献，至少要有 `title`、`author`、`year`，期刊/会议论文再加 `journal` 或 `booktitle`、`pages`，否则 GB/T 7714 著录会缺项。
- 推荐自己提供准确的 `.bib`（Zotero / Google Scholar 导出单条并核对）。只提供 PDF 时 hook 会补一份**草稿**，准确性仍需你复核。
- `<stem>.research-area` 是**自动生成的标记，一篇一个**，不要手动创建或编辑。
- 每位成员只动自己的 `papers/<用户名>/` 目录，这是避免冲突的关键。

---

## 三、commit 注释：必须写全 4 段信息

**固定格式：**

```text
该小节下的数字序号： <论文文件名> : [AREA: <研究方向名称>]  :  [贡献人 ： 项目成员的GitHub账号]
```

典型示例：

```text
1： WeSCE A Benchmark for Measuring Security : [AREA: Intelligence Software Engineering]  :  [贡献人 ： lihongweimail]
```

| 字段 | 说明 |
| --- | --- |
| 数字序号 | 该论文在所属方向小节里的顺序号。README 的编号由生成器统一分配，这里填「当前条目数 + 1」即可，只作人工核对 |
| 论文文件名 | `papers/<你的用户名>/` 下的文件名，不含扩展名；写论文标题也可以，脚本会做模糊匹配 |
| `[AREA: ...]` | 研究方向名称，会成为 README 的小节标题。**一次 commit 只写一个方向** |
| `[贡献人 ： ...]` | 你的 GitHub 账号，会显示在 README 条目末尾 |

分隔符半角/全角都行（`:` 或 `：`），`贡献人` 写成 `contributor` 也认；`[ AREA: x ]`、`【AREA：x】` 同样能识别。但这 4 段信息**必须齐全**，否则 `commit-msg` hook 会中止提交：

```text
✗ commit 注释不合规，已中止提交：
  - commit 注释缺少 `[贡献人 ： <GitHub账号>]`
```

只差文字时不必重新 `git add`，直接 `git commit --amend` 改注释即可。

### 合并提交

**一个 commit 对应一个研究方向。** 多篇不同方向的论文请拆成多个 commit（分别 `git add` + `git commit`，最后一次性 `git push`）。同一方向的多篇可以放在一个 commit 里，但注释里要**为每篇各写一行**声明。

### 旧论文：声明会被忽略

`[AREA: ...]` 只对**还没有方向的论文**生效。如果你在注释里写了某篇**已有论文**的方向（复制模板、顺带提一句、或修改旧论文时又写一遍），这条声明会被**识别并忽略**：

- 那篇论文保持原来的小节，**不会被移动**；
- 它的 bib 信息**不会**再次写进任何小节，README 里始终只出现一次；
- 这条声明也**不会**被同一次提交里的新论文「继承」。

**新论文不受影响**：尚未归类的论文仍按原有行为，直接写入 `[AREA: ...]` 对应的小节。日志里的 `· ...本次声明被忽略（保持原小节）` 属正常现象。

### 只有一处改动时

只修改已有论文的 `.bib`（补元数据、删掉 `AUTO-GENERATED` 头）时，注释可以照常写该论文的完整声明；因为它已有方向标记，声明会被忽略，README 只会按新元数据刷新著录，不会挪动位置。

---

## 四、README 里的条目长什么样

`README.md` 由脚本生成，每个研究方向一个小节，条目格式为：

```text
<数字序号>： <GB/T 7714-2015 著录> : [<贡献人 GitHub 账号>]
```

实际效果（`Intelligence Software Engineering` 小节）：

```text
1： ZHANG Z, WEN T, SUN S, et al. WeSCE: A Benchmark for Measuring Security Drift in LLM-Driven Code Editing[J]. arXiv preprint arXiv:2608.15092, 2026. : [lihongweimail]
```

著录细节：

- **著者**：姓全大写 + 名首字母（`ZHANG Z`），超过 3 人截断为前 3 人加 `et al.`；中文姓名按原样并用「等」。
- **文献类型标识**：`[J]` 期刊、`[C]` 会议、`[M]` 专著、`[D]` 学位论文、`[R]` 报告、`[S]` 标准、`[P]` 专利、`[EB/OL]` 在线资源；arXiv 预印本若无 `journal` 字段，按 `arXiv preprint arXiv:<id>` 归入 `[J]`。
- **期刊**：`刊名, 年, 卷(期): 起止页码.`；**会议**：`//论文集名. 出版地: 出版者, 年: 页码.`
- 题名同时是 PDF 链接，正文仍是标准著录文字。
- 序号在**小节内**从 1 开始，按提交先后（标记里的 `added` 日期）排列，新增论文不会打乱已有编号。
- `.bib` 由脚本生成且头部带 `%% AUTO-GENERATED` 时，条目末尾会多一个 **（BibTeX 自动生成，待核对）**。核对完元数据、删掉 `.bib` 头部的 `%%` 行，再提交一次即可去掉。

---

## 五、hook 说明

### 安装（每个 clone 一次）

```bash
sh scripts/install_hooks.sh
```

它做三件事：给 `.githooks/` 下三个 hook 加执行权限、设置 `git config core.hooksPath .githooks`、检查 Python 与可选依赖。hook 是本地配置，**不会随 clone 自动生效**，换机器或重新 clone 后要再跑一次。

如需更准的 PDF 元数据提取，再装一次可选依赖：

```bash
python3 -m pip install -r requirements-pdf.txt
```

### 三个 hook 的职责

| hook | 职责 | 不合规时 |
| --- | --- | --- |
| `.githooks/pre-commit` | 暂存区里每个 PDF 都要有同名 `.bib`，且 `.bib` 里至少有一条 `@type{`；缺失或为空 → 从 PDF 生成并 `git add` | `.bib` 生成失败 → **中止提交** |
| `.githooks/commit-msg` | 校验注释的 4 段信息 | 缺失 → **中止提交**并打印模板 |
| `.githooks/post-commit` | 写 `.research-area`、重建 `README.md`、`git commit --amend` 并入同一 commit | 失败 → 文件留在暂存区，给出补救命令 |

### BibTeX 生成时的行为

| 场景 | 行为 |
| --- | --- |
| 暂存了新 PDF，没有同名 `.bib` | 生成 `.bib` 并 `git add`，两者进入同一个 commit |
| `.bib` 存在但没有任何 `@` 条目（空文件、导出失败） | 视为缺失，重新生成并 `git add` |
| `.bib` 已有可用条目 | 不重新生成，绝不覆盖 |
| 只改了已有 PDF（`.bib` 完整） | 不动作 |
| `.bib` 已在仓库且内容有效 | 不动作 |

元数据按顺序尝试：`pdf2bib`（若装）→ PDF 内 DOI 查 Crossref → arXiv ID 查 arXiv → 首页标题检索 Crossref → 带 `REVIEW` 标记的占位条目。网络不通不会卡住提交。

生成的 `.bib` 顶部有：

```text
%% AUTO-GENERATED by scripts/pdf_to_bib.py -- METADATA NEEDS HUMAN REVIEW
%% Metadata source: Crossref DOI 10.1038/nature14539
%% Source PDF: papers/alice/attention.pdf
```

**建议尽快**核对 `title` / `author` / `year` / `journal` / `pages`，删掉头部 `%%` 行，再提交一次修正；README 的「待核对」标记随之消失。

### 手动等价操作（不想装 hook 时）

```bash
python3 scripts/pdf_to_bib.py "papers/alice/attention.pdf"
# 核对、必要时修改生成的 .bib
git add "papers/alice/attention.pdf" "papers/alice/attention.bib"
git commit -m "3： attention : [AREA: 大模型推理优化]  :  [贡献人 ： alice]"
```

没有 hook 时，方向标记与 README 由 GitHub Actions 兜底生成，但会是一个额外的 bot commit，README 会比自己 commit 晚一步。

### 关闭 hook

```bash
git config --unset core.hooksPath
```

---

## 六、常见问题

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `✗ commit 注释不合规，已中止提交` | 注释缺 4 段信息之一 | `git commit --amend` 改注释后重试 |
| `✗ 无法确定以下论文的研究方向` | 注释里没提到这篇论文，或同一篇写了两个方向 | 为它单独写一行声明；一条 commit 只能一个方向 |
| `pre-commit: ... is missing or contains no BibTeX entry` | 生成失败（多半没装 `pypdf`/没网） | `pip install -r requirements-pdf.txt`，或手工补 `.bib` 后 `git add` |
| Actions 的 `Resolve Research Area` 失败 | 没装 hook（网页上传 / `--no-verify`），CI 只校验不生成 | 本地按流程重提一次 |
| README 条目带「（BibTeX 自动生成，待核对）」 | `.bib` 由脚本生成 | 核对元数据、删掉文件头 `%%` 行、重新提交 |
| 著录缺项（无刊名/无页码） | `.bib` 缺 `journal` / `booktitle` / `pages` | 补全 `.bib` 字段后重新提交 |
| README 出现两个意思相近的小节 | 方向名用词不一致 | 统一用词，改对应 `<stem>.research-area` 的 `area` 后提交 |
| 贡献人写错了 | 注释里的账号打错 | 改 `<stem>.research-area` 的 `contributor` 后提交，或整篇重来 |
| 序号和别人的重复了 | 手工填的序号只是参考 | 无需处理：README 的编号由生成器统一分配 |

### 补救：已经 push 了才发现缺 `.bib`

要保持「严格同 commit」只能改写历史：

```bash
git add "papers/alice/attention.pdf"
git commit --amend --no-edit              # hook 会把 .bib 并入原 commit
git push --force-with-lease origin main   # 操作前确认没有别人的新提交
```

`main` 没有分支保护，force push 会改写远端历史。执行前先 `git fetch` 看一眼。

### 补救：漏写了 `[AREA: ...]`

```bash
git commit --amend                        # 补全注释
git push --force-with-lease origin main
```

或者改动一下该论文的 `.bib` 再以正确格式提交一次，CI 会把方向补齐（但 README 会晚一个 bot commit）。注意：**空 commit（`--allow-empty`）不会触发工作流**，因为路径过滤要求确实有 `papers/` 下的文件变更。

---

## 七、本地预览 README

```bash
python3 -m pip install -r requirements.txt
python3 scripts/build_readme.py    # 直接按现有标记重建 README.md
```

`build_readme.py` 在未安装 `bibtexparser` 时会退回到内置轻量解析器（v1/v2 API 均兼容），本地预览不依赖网络。方向小节按名称排序（中文按拼音）。

单独校验某条注释是否合规：

```bash
python3 scripts/commit_contract.py "1： attention : [AREA: 大模型推理优化]  :  [贡献人 ： alice]"
# 输出：✓ 注释合规
```

---

## 八、范围说明

- **「PDF 与 `.bib` 同 commit」由本地 `pre-commit` 保证；「标记与 README 同 commit」由 `post-commit` 的 `--amend` 保证。**
- CI 只校验、不生成：`pdf_to_bib.py --check --fail` 会在任何 PDF 缺 `.bib`、或 `.bib` 里没有 `@` 条目时让工作流失败。
- 自动生成的 BibTeX 只是草稿，**准确性由提交者负责**；README 会标注「待核对」，删掉 `.bib` 头部注释后标记消失。
- 方向名称不做自动归一，避免误判。
- `README.md` 由脚本维护，请勿手动编辑。
- bot 提交带 `[skip ci]`，且由 `GITHUB_TOKEN` 推送（GitHub 不会因此触发 push 型工作流），不会循环构建。
