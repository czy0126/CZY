# G0 整合主板 KiCad 10 工程 — 先读

**打开同名前缀** `d1_g0_integrated_mainboard_ELECTRICAL_NOT_FOR_FAB.kicad_pro`，进入 PCB 与 schematic。

- `.kicad_pcb`：包含 154 个可编辑封装对象、24 个磁件**逻辑**焊盘和已经连接的 27 条路由网（实际有多段 track/via）。KiCad 原生 DRC 0 项规则违规，0 项未连接。
- `.kicad_sch`：154 个可编辑**网络映射用简化符号**、427 组 Ref/Pin/Net，原生 KiCad ERC 0 项违规；符号并非真实厂家符号，原理图由 PCB Pad/Net 反向生成，不是独立功能设计签核。
- `.net`：从这张 schematic 原生导出的网表，427 引脚已逐一核对。
- `G0LogicalMainboard.kicad_sym`、`sym-lib-table`：项目局部符号库，和上述 SCH 一起打开。
- `d1_g0_integrated_trial_bom_UNQUALIFIED.csv`：所有 154 器件当前的设计意图和 Pad-Net 清单，**不代表真实供应链 MPN 全部合格**。
- `*_native_drc.json`、`*_native_erc.json`、`d1_g0_integrated_trial_package_NOT_FOR_FAB.json`：原生规则检查与 SHA 证据。

**绝不可直接生产/上电：** 磁件的 24 个厂家实体端子、DOT、匝数、3:1:1 绝缘尚未确认；跨层过孔与电流截面/EMC/热仍不合格签核；原副边 12 V 实际隔离偏置、UVLO、独立断开 48 V 急停及十路门极故障关断尚未并到这块产品主板；实测冷启动、故障波形和首次限流轻载均缺失。原始项目有 5 类忽略的 DRC 检查。

**工程进度事实：** “PCB DRC=0、连接=0”仅指网络连通和现有检查规则下无几何违规。严禁将其当作制造放行或 G0/G1 通过。

完整技术交接：仓库内 `docs/agent/D1_G0_INTEGRATED_NATIVE_MAINBOARD_20261115_NOT_FOR_FAB.md`。
