# D1 G0 V4 主板：独立设计源、分离回流、双偏置接口交付（2026-11-15）

首选工程：hardware/dcx_main/g2/d1_g0_INDEPENDENT_SOURCE_V4_MAINBOARD_NOT_FOR_FAB

下载 GitHub 中的 G0_V4_157_PART_INDEPENDENT_SCHEMATIC_EDITABLE_KICAD_NOT_FOR_FAB.zip，解压后在 KiCad 10 打开 d1_g0_157_PART_INDEPENDENT_SOURCE_MAINBOARD_NOT_FOR_FAB.kicad_pro。包含原生 PCB、独立来源 SCH、项目符号、ERC/DRC 报告、原生 netlist、BOM、修改说明、SHA证据及129个副边端子改线表。

## 工程内容

- V1 原生母板：149 个旧封装+五磁件逻辑占位=154个封装，27组未连接实际布线闭合，PCB规则DRC=0、未连=0、SCH ERC=0。但是 SCH 来源是 PCB自身，四个SR控制器和八个SR MOS Source以及输出回流都共用PGND。
- V2 实际新增 R8 1k RUN使能焊盘和铜路，155个封装。保持原生DNP，即不实际装焊，避免未经保护审核时自动启动。对独立SPICE黄金引脚表的缺件从R8一项降为零。
- V3 真实改动129个物理焊盘、181条副边PGND走线/过孔，拆开In1.Cu原先贯穿全板的PGND地平面，副边独立为SR_SOURCE_RETURN，T4 PRI_B保持原边PGND并通过槽间通路连接；原生PCB规则DRC=0、未连=0。这是电气CAD分域而不是绝缘认证。
- V4 再增加J_BIAS_P（VCC12/PGND）与J_BIAS_S（VCC12_S/SR_SOURCE_RETURN）两个实体PTH 12V外部偏置端子，157个可编辑封装。真实原生KiCad ERC=0、DRC=0、未连接=0。原理图不再从PCB反向投影，而是由独立保留的SPICE黄金网表、实测器件引脚扩展、外围使能规格、72个输出电容设计约定、129端子分域ECO和两输入端口设计约定直接构建。导出网表后433个独立 Ref/Pin/Net 与实际PCB逐脚吻合。

## 为什么仍不能送厂或上电

这是一块源电气网络已复核、CAD连通的工程试验板，**不是G0已经完成的真实48V→2V硬件**。

1. T1-T4和CT仍是逻辑端子焊盘，厂家真实24实体端子、DOT、绕组、磁芯、变压器匝比3:1:1和绝缘均未取得已批准证据。原理图采用中性简化符号，并非经过独立专业工程师的整套模拟/功能/时序签核。
2. 两个偏置端子只是外部输入接口，不是已装板的两只隔离48→12V模块；实际UVLO、供电失效强制关断、独立48V物理急停、浮地HS VGS检测、十路门极故障抑制尚未加入产品PCB。R8必须一直DNP，直到这些安全保护实体闭合且签核。
3. 新的铜网隔离不代表已通过爬电/电气间隙、层间耐压和EMC测试。12层stackup、磁件开槽、铜厚、过孔塞孔、涌浪/损耗和输出温升需厂商DFM。原项目仍存在5类被忽略的KiCad DRC检查，不得通过调整规则获得虚假合格。
4. 真实60组关断波形、限流冷启动、SOA和故障注入尚未采集，G0九项物理验收仍全部PENDING。

## 分工与可执行阻塞

| 工程环节 | 下一项实际工作 | 原始证据 |
|---|---|---|
| Lane A 电气功率 | UCC25600/UCC27282/UCC24624真实元件图、取样/控制、使能保护与原生产品PCB合并 | 正式电路图、带引脚的元器件库、真实器件值与仿真/初步波形 |
| Lane B 磁件 | T1-T4/CT厂家外形、24实体端子、DOT、绕组和3:1:1的核对 | 实体CAD、BOM、绝缘及Lm/Llk/铜损/饱和验证 |
| Lane C 电气安全 | 安装隔离12V偏置/UVLO、硬件48V断能急停、HS监测、SR失偏置关断 | 分域供电SCH/PCB、故障原始波形、独立人工作业签核 |
| DFM/测试 | 12层、via、接线端子与铜路电流/EMC/温升、G0安全限流台架 | 制造商DFM、实测和真实示波器数据 |

G0目标是首次低功率安全运行，G2 100A最大功率与G3 3LPM冷板可后置；但是G0的安全断能、偏置失效及真实磁件不允许后置。

## 复验

Windows本机KiCad 10的python.exe位于 C:/Users/27792/AppData/Local/Programs/KiCad/10.0/bin/python.exe。

依次运行新脚本的 --check：
tools/d1_g0_r8_safe_enable_eco.py
tools/d1_g0_split_return_eco_trial.py
tools/d1_g0_bias_ports_v4.py
tools/d1_g0_independent_design_source_schematic.py
tools/d1_g0_package_independent_v4.py

标准环境运行：
python tools/d1_lane_c_g0_acceptance.py --check
python -m pytest tools/d1_g0_test_v4_cad_handoff.py tools/d1_g0_test_cross_domain_audit.py tools/d1_lane_c_test_g0_acceptance.py -q

任何 --require-g0 验收仍必须返回BLOCKED。这些是可再现EDA/CAD证据，绝不能代替实际实验和制造批准。
