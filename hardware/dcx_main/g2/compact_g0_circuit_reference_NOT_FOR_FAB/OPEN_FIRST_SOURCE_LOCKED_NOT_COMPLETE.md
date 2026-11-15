# 紧凑模块 G0 既有电路图复用包（非最终 C0 成品）

**来源与性质：** 从 `feat/d1-g0-integrated-mainboard-20261115` / [PR #136](https://github.com/czy0126/CZY/pull/136) **选择性提取已有电路**，只放入紧凑型 48 V→约 2 V DCX 主线。没有迁入任何其他架构、机械代理或冷板项目。

## 用户可以直接打开的图纸

- [V5 主功率原生 KiCad 原理图](./d1_g0_161_PART_SR_KELVIN_SOURCE_AUTHORED_NOT_FOR_FAB.kicad_sch)，相同文件名的 `.kicad_pro`、自包含 `G0SRKelvinSource.kicad_sym` 和 `sym-lib-table` 配套在本目录；[V5 原生PDF](./compact_g0_power_schematic_V5_REVIEW_NOT_INTEGRATED.pdf)。
- [四张独立现有电路 PDF 汇编](./compact_g0_existing_circuit_4sheets_REVIEW_NOT_INTEGRATED.pdf)：按顺序 V5 主功率、V6 隔离偏置/UVLO、V7 常闭急停、V8 隔离高侧监测。
- 原始的 V6/V7/V8 **可编辑 KiCad 子板设计**仍保存在 [PR #136](https://github.com/czy0126/CZY/pull/136)，此处只复制只读PDF供用户快速看图，以避免重复维护四份驱动/保护源文件。

## 验证与事实边界

- V5 `.kicad_sch` 原始字节 SHA256 `1e82084b84b6a881d82691d9b8dea787ec1e9851cc38b218f611fdefb281b6c1`，本轮原生 `kicad-cli sch erc` 重新运行显示0项违规，但仍有4类忽略项：`single_global_label`、`four_way_junction`、`simulation_model_issue`、`footprint_filter`，具体见 [原生ERC结果](./compact_v5_native_erc_recheck_NOT_FOR_FAB.json)。
- 上述 PDF 的四页**分别来自四个独立 KiCad 原理图**，尚未连接成顶层一套可运行、可上电的实际电路。不能把“已能够看到4张图”误报为“C0完整成品”。
- G0 真实硬件验收仍0/9、60项源参考VGS故障波形仍0/60；此目录所有原理图和PDF都是 **NOT_FOR_FAB / NOT_FOR_POWER_ON**。

## 下一位Agent的首要任务

在 `hardware/dcx_main/g2/compact_dcx_C0_integrated/` 真正整合 **V5功率—V6隔离偏置—V7急停—V8高侧测量接口**，逐脚核对磁件与驱动、把D0/UVLO/过流/失偏置默认关断连接完整，形成一份用户可直接审核的**统一原生KiCad工程+正式多页PDF+完整netlist+BOM/ERC和失败状态**。本目录仅是源追溯和现有工程进展的可视化入口，不是下一版完整电路的替代品。
