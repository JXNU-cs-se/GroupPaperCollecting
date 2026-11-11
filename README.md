# GroupPaperCollecting 文献清单

> 本文件由提交 hook / GitHub Actions 自动生成，请勿手动编辑。最后更新于 2026-11-11。
>
> A repository for students in our Group committing the reading Papers for Collecting.

## 提交前必读：commit 注释必须写全 4 段信息

每次 commit 都必须在注释里写清下面这一行**核心信息**，缺任何一段，本地 hook 会**直接拒绝提交**并提示你改注释：

```text
该小节下的数字序号： <论文文件名> : [AREA: <研究方向>]  :  [贡献人 ： 项目成员的GitHub账号]
```

典型示例（对应 `papers/lihongwei/` 下的 WeSCE，`Intelligence Software Engineering` 小节的第 1 条）：

```text
1： WeSCE A Benchmark for Measuring Security : [AREA: Intelligence Software Engineering]  :  [贡献人 ： lihongweimail]
```

- **数字序号**：该论文在所属小节里的顺序号；README 中的编号由生成器按小节内顺序（先提交的在前）自动生成，避免重复或断号。
- **论文文件名**：与 `papers/<你的用户名>/` 下的文件名一致（不含扩展名）；写论文标题也可以，脚本会做模糊匹配。
- **`[AREA: ...]`**：研究方向名称，会成为 README 里的小节标题，请保持简短、稳定。**一次 commit 只写一个方向**，不同方向请分开提交。
- **`[贡献人 ： ...]`**：你的 GitHub 账号，会显示在 README 对应条目的末尾。

### 一次 commit 里发生了什么

1. **校验注释**：缺上面任何一段信息，hook 立即中止提交并打印正确格式。
2. **校验 BibTeX**：检查提交内容里的 `.bib` 是否存在、是否真的含有 `@` 条目；缺失或为空时，从同次提交的 PDF 里提取元数据生成 `.bib`。
3. **写入方向标记**：生成 `<论文文件名>.research-area`，记录方向、贡献人、序号。
4. **重建 README**：按 **GB/T 7714-2015** 著录该论文，写入对应研究方向小节，格式为 `<数字序号>： <GB/T 7714-2015 著录> : [<你的GitHub账号>]`。

以上文件（PDF、`.bib`、`.research-area`、`README.md`）**落在同一个 commit 里**，push 之后 README 立即是最新的，不需要等下一次提交，也不用手动改 README。

- **旧论文跳过、新论文照常归类**：commit 注释里写的是**已有论文**及其方向时，这条声明会被**识别并忽略**——那篇论文保持原小节，不会被移动，也不会重复出现；**尚未归类的新论文**仍按原行为写入 `[AREA: ...]` 对应的小节。
- 首次 clone 后先执行一次 `sh scripts/install_hooks.sh` 安装 hook；没装 hook 时（例如网页上传）由 GitHub Actions 兜底完成第 2~4 步，但补出来的文件只能落在下一个 commit。
- 完整目录结构与提交流程见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## Intelligence Software Engineering

1： ZHANG Z, WEN T, SUN S, et al. [WeSCE: A Benchmark for Measuring Security Drift in LLM-Driven Code Editing](papers/lihongwei/WeSCE%20A%20Benchmark%20for%20Measuring%20Security.pdf)[J]. arXiv preprint arXiv:2608.15092, 2026. : [lihongweimail]  
2： CHEN X, HU X, HUANG Y, et al. [Deep learning-based software engineering: progress, challenges, and opportunities](papers/lihongwei/Deep%20Learning-based%20Software%20Engineering%20Progress%2C%20Challenges%2C%20and%20Opportunities.pdf)[J]. Science China Information Sciences, 2024, 68(1). : [lihongweimail]（BibTeX 自动生成，待核对）  
3： HU X, XIA X, LO D, et al. [Practitioners' expectations on automated code comment generation](papers/lihongwei/ICSE22%20Practitioners%20Expectations%20on%20Automated%20Code%20Comment%20Generation.pdf)[C]//Proceedings of the 44th international conference on software engineering, 2022: 1693-1705. : [lihongweimail]  

## Sentiment Analysis

1： ZHANG L, WANG S, LIU B. [Deep learning for sentiment analysis: A survey](papers/lihongwei/Deep%20learning%20for%20sentiment%20analysis%20A%20survey.pdf)[J]. Wiley interdisciplinary reviews: data mining and knowledge discovery, 2018, 8(4): e1253. : [lihongweimail]  
