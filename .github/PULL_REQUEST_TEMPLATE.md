> **GitHub 默认分支模板（`main`）**：D1 的交付文件、决策与 Issue 应引用 [活跃研发分支](https://github.com/czy0126/CZY/tree/feat/d1-fab-package)；本模板不能把旧 `main` 的源文件当作最新。

## 1. 必须交付什么（无实际产物的 PR 原则上停止）

- **归属**：`A #9 原生 CAD / B #12 磁件与器件 / C #36 D0 实测 / P0 安全修复 / 一次性仓库导航维护`（选一）
- **阶段**：`G1 布局 / G2 实装封装与100A铜路 / G3 真实制造审核 / 非阶段证据`
- **对应当前阻塞**：链接已有 Issue，不新建同义“再审核/总计划”。
- **唯一实际变化（改前 → 改后）**：填写原生 `.eprj2` / 工程磁件模型 / BOM 真实 EDA 字段 / 示波器 RAW / 板厂回件的**路径与版本 SHA**。若仅改文档，请说明替换了哪个重复入口；不得声明 CAD 里程碑进展。
- **实际执行地点与命令**：Windows EasyEDA / AEDT Maxwell / 台架 / 离线预检；**注明哪些命令只在 CI 跑，哪些在真实工作站执行了**。

## 2. 必须提供的验收证据

| 类别 | 真实结果、文件路径或无法执行的唯一条件 |
| --- | --- |
| 同版输入与 SHA / 原始数据 |  |
| 保存、关闭、重开 / 仿真收敛 / 原生 DRC / 波形证据 |  |
| 与上一版相比改变了什么计数或技术判据 |  |
| 未完成/不能批准制造的具体条件 |  |
| **下一个唯一交付**及执行环境 |  |

**严禁：** 把 offline 0 冲突、测试绿灯、旧网表 pin/net 一致、概念 STEP/临时 PAD、理想 SR 控制波形当作原生 PCB 已修改、实体 Maxwell 已完成、100 A 额定或安全关断已通过。

## 3. 反重复检查（修改前必须阅读）

- [ ] 已阅读 [当前活板/下一交付](https://github.com/czy0126/CZY/blob/feat/d1-fab-package/docs/D1_CURRENT.md) 和 [已决事项](https://github.com/czy0126/CZY/blob/feat/d1-fab-package/docs/D1_DECISIONS.md)，本 PR **没有再次做**已冻结事项；若重开，附真实新证据。
- [ ] 同一 A/B/C 主线不新增仅报告/预检的第二个未结核心 PR；当前原生 CAD 无法执行时不反复扩展小信号布线方案。
- [ ] 概念、仿真、实测、原生 CAD 的来源和对象版本清楚区分。
- [ ] `NOT_FOR_FAB` 与真实门禁不因本 PR 自行变更；真实设计安全 P0 纠错允许例外，但仍需证据。
- [ ] 文档只更新**一个权威入口**，旧路线归档或链接，不新建“最新总体路线”。

**当前主工作流：** [Issue #4](https://github.com/czy0126/CZY/issues/4) · [D1_CURRENT](https://github.com/czy0126/CZY/blob/feat/d1-fab-package/docs/D1_CURRENT.md) · [第49章设计合同](https://github.com/czy0126/CZY/blob/feat/d1-fab-package/docs/D1_EXECUTION_KIT/49_D1主功率板PCB唯一执行计划_2026-11-09.md)。PR 合并 ≠ 制造批准。
