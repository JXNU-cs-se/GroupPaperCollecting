# 论文提交规范

本仓库用 **commit message 声明研究方向**，由 GitHub Actions 自动写入方向标记并生成 `README.md`。
成员只需放好文件、按格式提交，**不需要**（也不要）手动编辑 `README.md`，因此多人同时提交不会产生 Git 冲突。

---

## 三步完成一次贡献

### 第 1 步：克隆仓库

```bash
git clone https://github.com/JXNU-cs-se/GroupPaperCollecting.git
cd GroupPaperCollecting
```

无需提前创建个人目录，按下面的路径放文件时目录会自动建立。

### 第 2 步：放入 PDF 与 BibTeX

每篇论文一个**独立子目录**，路径为 `papers/<你的GitHub用户名>/<bibkey>/`：

```text
papers/alice/smith2024attention/
├── smith2024attention.pdf
└── smith2024attention.bib
```

要求：

- **目录名 = BibTeX 的 cite key**，三者（目录名、`.bib` 文件名、`.pdf` 文件名）保持一致。
- `.bib` 可以从 Zotero 导出单条，或用 `pdf2bib` 等工具生成后**人工核对**；必须包含 `title`、`author`、`year` 三个字段，否则 README 中的条目会信息不全。
- 一个 `.bib` 文件只放一条文献。
- PDF 文件名与目录名相同（`smith2024attention.pdf`）。
- 不同成员使用各自的 `<GitHub用户名>` 子目录、各自不同的 `bibkey`，这是**避免冲突的关键**。

### 第 3 步：以约定格式提交

**commit message 固定格式**：

```text
[AREA: <研究方向名称>] 简短描述
```

示例：

```text
[AREA: 大模型推理优化] 添加 Smith 2024 关于 KV Cache 压缩的工作
[AREA: 图神经网络] 添加 Lee 2025 鲁棒性分析
```

```bash
git add papers/alice/smith2024attention/
git commit -m "[AREA: 大模型推理优化] 添加 Smith 2024 关于 KV Cache 压缩的工作"
git push origin main
```

`<研究方向名称>` **由提交者自由填写，无需在任何配置文件里预先注册**。若这是 README 中尚不存在的新方向，聚合脚本会自动为它创建新小节。

---

## 必须遵守的四条规则

1. **一个 commit 只对应一个研究方向。**
   若一次要提交多篇分属不同方向的论文，请**拆成多个 commit**（可以先 `git add` 一个目录、提交，再 `git add` 下一个目录、提交，最后一次性 `git push`）。同一个方向的多篇论文可以放在同一个 commit 里。
2. **每个带 `[AREA: ...]` 的 commit 中，方向名必须唯一。** 同一 commit 里写了两个不同的 `[AREA: ...]` 会被判定为归属不明，CI 直接标红。
3. **方向名称尽量简短、稳定。** 本系统**不做近义词归一化**：`大模型推理` 与 `LLM 推理优化` 会生成两个独立小节。首次使用新方向前，建议先在团队群里确认一次用词。
4. **不要手动编辑 `README.md`，也不要手动创建 `.research-area`。** 两者都由自动化维护；手工改动会在下次构建时被覆盖。

---

## 提交后会自动发生什么

1. `Resolve Research Area` 工作流扫描本次 push 新增的论文目录，从**引入该目录的那条 commit message** 中读取 `[AREA: ...]`，把方向名写入该目录下的 `.research-area` 文件（例如内容为 `大模型推理优化`）。
2. 该工作流随后触发 `Build README` 工作流；后者遍历所有 `.research-area`，用 BibTeX 的 `title / author / year` 生成条目，按方向分节、节内按年份倒序，覆盖写入 `README.md`。
3. 两个自动化提交都带 `[skip ci]`，不会引发循环构建。

---

## CI 标红了怎么办

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `Resolve Research Area` 失败，日志出现 `no [AREA: ...] found` | commit message 漏写方向声明 | 按下方「补救方式」补一次提交 |
| 日志出现 `conflicting areas` | 一条 commit 里写了两个不同方向 | 拆成两个 commit，各自声明一个方向 |
| README 中出现两个意思相近的小节 | 方向名用词不一致 | 统一用词后，修改对应目录下的 `.research-area` 并提交（触发 README 重建） |
| README 条目显示 `n.d.` 或 `未知作者` | `.bib` 缺 `year` / `author` 字段 | 补全 `.bib` 后重新提交 |

**补救方式（漏写 `[AREA: ...]` 时）**：在该论文目录下任意改动一下 `.bib`（例如修正一个字段、或补上注释），然后以正确的格式重新提交：

```bash
git add papers/alice/smith2024attention/smith2024attention.bib
git commit -m "[AREA: 大模型推理优化] 补充研究方向声明"
git push origin main
```

也可以在仓库 **Actions** 页手动运行 `Resolve Research Area`。注意：**空 commit（`--allow-empty`）不会触发工作流**，因为 push 的路径过滤要求确实有 `papers/` 下的文件变更。

---

## 本地预览 README

```bash
python3 -m pip install -r requirements.txt
python3 scripts/parse_area.py      # 需要本地 git 历史
python3 scripts/build_readme.py    # 生成 README.md
```

`build_readme.py` 在未安装 `bibtexparser` 时会退回到内置的轻量解析器，本地预览不依赖网络。方向小节按名称排序（中文按拼音），节内按年份倒序。

---

## 范围说明

- 本仓库**不负责**从 PDF 自动生成正确的 BibTeX。`.bib` 的准确性由提交者负责，工具生成的结果必须人工核对后再提交。
- 方向名称不做自动归一，避免误判；如后续确有需要，可在 `build_readme.py` 中增加可选的别名映射表。
