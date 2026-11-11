# GroupPaperCollecting 文献清单

> 本文件由 GitHub Actions 自动生成，请勿手动编辑。最后更新于 2026-11-11。
>
> A repository for students in our Group committing the reading Papers for Collecting.

## 提交前必读：commit 注释必须声明研究方向

成员提交论文时，**commit 注释中必须写上 `[AREA: ...]`**，格式为：

```text
<论文标题> : [AREA: <研究方向>]
```

典型示例（本条对应 `papers/lihongwei/` 下的 WeSCE）：

```text
WeSCE A Benchmark for Measuring Security : [AREA: Intelligence Software Engineering]
```

- `[AREA: ...]` 里的方向名会被写成该论文的 `<文件名>.research-area` 标记，并作为下面每个小节的标题，请保持简短、稳定。
- **一次 commit 只写一个方向**；不同方向的论文请分开提交，否则 CI 会判为冲突。
- 漏写 `[AREA: ...]` 时 CI 会**失败（红色 ✗）**，补正方式：`git add <论文> && git commit --amend --no-edit` 后重新 push。
- 论文与同名 `.bib` 必须在**同一个 commit** 中提交；首次 clone 后先执行 `sh scripts/install_hooks.sh` 安装 pre-commit hook，缺 `.bib` 时会在提交前自动生成。
- 完整目录结构与贡献流程见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## Intelligence Software Engineering

- [WeSCE: A Benchmark for Measuring Security Drift in LLM-Driven Code Editing](papers/lihongwei/WeSCE%20A%20Benchmark%20for%20Measuring%20Security.pdf) — Zhang et al. — 2026
