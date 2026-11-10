# CZY — 48 V → 约 2 V 薄型固定变比 DCX

**D1 当前设计目标：** 约 24:1 固定比、100 A 输出目标、整机高度 ≤16 mm；成本暂不限制。D2 的 120 A 与 D3 的 ≤10 mm 均后置，保护、绝缘、载流与制造签核不可省。

> **当前研发分支：[`feat/d1-fab-package`](https://github.com/czy0126/CZY/tree/feat/d1-fab-package)。默认 `main` 仍是历史快照。当前 D1 为 `NOT_FOR_FAB`；真实样机尚未获得投板或额定许可。**

## 从这里开始（不用翻旧审核报告）

1. **[D1 当前交接面板](docs/D1_CURRENT.md)**：唯一当前可编辑 G1 原生 PCB、已发生的 ECO、三条并行任务及下一次操作/验收。
2. **[D1 已决事项与重开条件](docs/D1_DECISIONS.md)**：R8/R6、Lr XY、九根布线预检、100 A 铜路等已经确认的边界；禁止重复审查同一证据。
3. **[第49章：D1 G1→G2→G3 交付合同](docs/D1_EXECUTION_KIT/49_D1主功率板PCB唯一执行计划_2026-11-09.md)**：阶段目标、冻结条件与实际制造要求；其 11/9 日期快照不覆盖当前 G1 读回。
4. **[历史技术资料索引](docs/D1_REFERENCE_INDEX.md)**：资料在哪里、哪些只作参考。原 README 的长篇历史更新已[归档](docs/archive/README_D1_branch_before_single_entry_2026-11-10.md)，保留所有技术原文和链接。

**唯一任务入口：** [Issue #4 总交付](https://github.com/czy0126/CZY/issues/4)，以及 [#9 原生 PCB/器件](https://github.com/czy0126/CZY/issues/9)、[#12 磁件与接口](https://github.com/czy0126/CZY/issues/12)、[#36 D0 保护](https://github.com/czy0126/CZY/issues/36)。**同时最多 A/B/C 三个工程工作包**；不为“再次审核/继续优化”新建总计划。

## 实际应该先做什么

**A 线优先：** 9条控制小信号增量已完成原生重开验收，未连接206→199，Physical 0、Netlist仍1；见[同CAD审核回执](hardware/dcx_main/g1/lr_signal_review_report.json)。下一步处理原生Import Changes逐位号差异、实体Cout和100 A两极铜路，不重复重画已有短线。

```powershell
python -m pytest tools/test_g1_copper_coverage.py tools/test_g1_driver_route_plan.py -q
```

上述测试是回归检查，不替代原生DRC；本轮信号候选及失败回执全部保留，尚待随本轮提交提升基线。B（真实 Maxwell/实体 PAD）与 C（D0 真实关断）并行，不得以模拟或脚本绿色替代实际硬件证据。

**工程和开发规则：** [`CLAUDE.md`](CLAUDE.md) · [`docs/agent/EDA.md`](docs/agent/EDA.md) · [PR 模板](.github/PULL_REQUEST_TEMPLATE.md)。任何 PR 应说明真实产物的**改动前后、原始证据和下一次实际交付**。仅更换“最新计划”标题或重复风险总结不算里程碑。

**制造许可唯一来源：** [`hardware/dcx_main/d1_fabrication_gate.json`](hardware/dcx_main/d1_fabrication_gate.json) 及其相同 CAD 修订版的独立审核证据；历史 JSON 不能混用为 G1 的签核。
