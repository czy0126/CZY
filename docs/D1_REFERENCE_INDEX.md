# 参考资料与历史路线索引（非当前任务）

> **唯一每日入口：[D1_CURRENT](D1_CURRENT.md)**。这份索引只解决“已经有何资料、该去哪里找”。旧文档**不迁移或删除**，以免使 GitHub PR、Issue、文件哈希和历史交叉引用失效；旧文件内写的“最新”“首选”“必须马上”均是**当时快照**，不构成现在的任务命令。

## 当前按用途找原始资料

| 需要什么 | 使用哪个现有入口 | 用途与边界 |
| --- | --- | --- |
| 单一阶段合同 | [第49章（2026-11-09）](D1_EXECUTION_KIT/49_D1主功率板PCB唯一执行计划_2026-11-09.md) | G1/G2/G3 验收规则；其中旧 R8/未布线描述已被 G1 最新原生读回更新；只沿用阶段定义 |
| 唯一活板与最新 G1 回执 | [G1 文件夹](../hardware/dcx_main/g1/README.md) · [当前索引](D1_CURRENT.md) | 原生 `.eprj2` / readback / 原生 DRC；不把概念 board 当制造板 |
| 当前 G1 BOM 与禁装 | [实际 83 器件清册](../hardware/dcx_main/g1/g1_native_inventory_bom_gate.json) · [D1 旧版综合 Gate](../hardware/dcx_main/d1_fabrication_gate.json) | 两者绑定的**主板版次不同**；不得混用元件或关断结论 |
| 100 A 两极铜路 | [真实 G1 窄颈筛查](../hardware/dcx_main/g1/g1_100a_copper_neck_screen.json) · [两极接点候选](../hardware/dcx_main/output_joint_reduction_cases.json) | 前者用于否决当前旧线；后者是未落 CAD 的理论候选 |
| 五磁件与 Maxwell | [概念几何参数](../design/v3/maxwell/diy_magnetics_concept.json) · [真实求解入口](../tools/maxwell_diy_run.py) · [磁件实脚审核指南](D1_EXECUTION_KIT/30_磁件24端子回件自动审核.md) | STEP 仅概念；真实工艺/端子/DOT、BH 及原始 Maxwell 求解仍缺 |
| D0 保护与真实十路示波器 | [#36](https://github.com/czy0126/CZY/issues/36) · [第29章真实门极波形判定](D1_EXECUTION_KIT/29_D0十路门极同步波形证据验收.md) | 低能量台架原始证据未齐；工具不会自动证明是真实硬件 |
| 现场命令与工具陷阱 | [操作命令](agent/COMMANDS.md) · [EasyEDA / 电路 ECO 环境](agent/EDA.md) · [CLAUDE.md](../CLAUDE.md) | 工具参考，不是新的阶段里程碑 |
| 文献、原厂器件、RFQ | [第47章原厂资料](D1_EXECUTION_KIT/47_原厂电容磁件高流端子资料与采购决策_2026-11-09.md) · [第48章供应商沟通](D1_EXECUTION_KIT/48_磁件电容铜排可发送供应商邮件_2026-11-09.md) | 候选/询样与实装 MPN 审批分开 |
| 原始 LTspice 与历史损耗 | [`sim/v3`](../sim/v3) · [`design/v3`](../design/v3) | 仅用于追溯已经验证的模型、并重新证实时可以重跑；不再主动扫参抢占 A/B/C |

## 已停止以“最新”为名重复阅读的资料

- [`docs/` 根目录的 2026-10-31 至 2026-11-06 评审/路线](./) 与 [`D1_EXECUTION_KIT/` 的 01–48 历次技术章](D1_EXECUTION_KIT/README.md)：按**历史技术证据**查找，不按其中各自的日期标题确定主线优先级。
- [原活跃分支 README 归档](archive/README_D1_branch_before_single_entry_2026-11-10.md)：保留过去每轮审查说明及追溯链接，非执行入口；原根目录 README 已换为简短当前索引。
- 默认 `main` 中的旧 V1/V2/V3 与 10 mm 目标仅作历史；新 PR 目标分支为 `feat/d1-fab-package`，除非明确说明维护 `main` 的导航指针。

## 防止文档再次分叉

项目日常进度**只**更新 [Issue #4](https://github.com/czy0126/CZY/issues/4)；[D1_CURRENT](D1_CURRENT.md)只在**当前基线换代、下一次主交付改变或现状描述确实过期**时伴随真实工程 PR 更改；[D1_DECISIONS](D1_DECISIONS.md)只在有新实证推翻冻结结论时更改。旧报告保持原有字节，禁止为改标题成“2026-11-11 最新路线”而再次复制一份。
