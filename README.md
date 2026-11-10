# CZY — 48 V → 约 2 V 固定变比薄型 DCX

> **你现在看到的是默认 `main`：历史/公共入口，不是正在交付的主板 CAD 版本。** 当前 D1 原生设计在 [`feat/d1-fab-package`](https://github.com/czy0126/CZY/tree/feat/d1-fab-package)。不要以 `main` 的历史网表、BOM 或 10 mm 旧目标来替换 D1 的实际工程数据。

## 当前唯一正确入口

请直接打开以下 GitHub 文件（全部位于真实研发分支）：

1. [D1 当前交接面板：实际活板、下一工程任务和执行命令](https://github.com/czy0126/CZY/blob/feat/d1-fab-package/docs/D1_CURRENT.md)
2. [D1 冻结决策与允许重开的证据](https://github.com/czy0126/CZY/blob/feat/d1-fab-package/docs/D1_DECISIONS.md)
3. [D1 G1 / G2 / G3 阶段验收合同](https://github.com/czy0126/CZY/blob/feat/d1-fab-package/docs/D1_EXECUTION_KIT/49_D1主功率板PCB唯一执行计划_2026-11-09.md)
4. [历史技术参考索引](https://github.com/czy0126/CZY/blob/feat/d1-fab-package/docs/D1_REFERENCE_INDEX.md)

**唯一进度跟踪：** [Issue #4](https://github.com/czy0126/CZY/issues/4)；实际 A/B/C 子任务为 [#9 CAD](https://github.com/czy0126/CZY/issues/9)、[#12 磁件](https://github.com/czy0126/CZY/issues/12)、[#36 保护](https://github.com/czy0126/CZY/issues/36)。后续 D1 PR 的目标分支原则上应选 `feat/d1-fab-package`，不对默认 `main` 重复追加“最新审核路线”。

**阶段与安全：** D1 目标 100 A / ≤16 mm，D2 120 A、D3 ≤10 mm 后置；真实 PCB 和磁件/保护尚未完成独立制造审核，始终 `NOT_FOR_FAB`。代码检查通过、PR 合并和 LTspice 仿真都不能授权投板或高能量上电。

旧默认分支的长篇更新说明已[完整归档](docs/archive/README_main_before_single_entry_2026-11-10.md)。历史源码、旧仿真与引用文件仍保留，供追溯，不再竞争当前执行优先级。
