# D1 / G0 九项实物验收 — 真实证据封口及现场测试交接

**审查日期：2026-11-15。状态：0/9 获得实物安全签核；0/60 原始 VGS 故障波形；G0 BLOCKED / NOT_FOR_FAB。**

本记录取代“原生 KiCad DRC=0 即允许上电”的错误做法。本机工程仅有真实**可编辑 EDA 设计**、仿真模型及测试模板，没有找到已提交的 g0_external_witnesses.json、真实示波器原始波形、实际生产磁件绝缘及点号测量、实物接触器急停及高侧 VGS 关断签核。Windows 枚举仅能识别 COM1，未识别可连接的示波器/可编程电源等仪器；这不证明实验室没有这些设备，只代表此主机目前无法远程取得实物数据。

## 已重新实际运行的离线检查

- **V5 主功率电路**：161 原生 PCB footprint / 441 个独立来源 Ref-Pin-Net，KiCad ERC0/DRC0/Open0；R8 RUN 依旧 DNP。保留 5 类需人工复审的 KiCad ignored DRC。
- **V6 双路偏置/UVLO子板**：30 原生 footprint / 80 个独立来源 pin-net，KiCad ERC0/DRC0/Open0。虽有双 THN30、两颗TPS3710 和隔离光耦，但其状态端 J_HEALTH **不接实际主电源48V物理断能、R8或高侧VGS联锁**。
- **Fail closed 复测**：运行 python tools/d1_lane_c_g0_acceptance.py --require-g0 返回非0并明确输出“do not energize 48V power stage”。
- **独立证据审计工具**：运行 python tools/d1_g0_physical_readiness.py --write 可生成 g0_physical_readiness_independent_audit_NOT_FOR_FAB.json；--check 对比受保护的源文件与波形清单，--require-g0 必须拒绝通过。
- 新增工具会扫描 6种故障×10 路 VGS 的 **60 个唯一组合**，每项要求正负测点和原始二进制/CSV波形；即使某个路径确实含文件及SHA，它也只记录 RAW_PRESENT_UNVERIFIED，**绝不将其升级为硬件通过**。

## 九项验收逐项执行与必须获得的原始证据

| ID | 已有成果 | 关闭前必须得到的实物与独立审查 | 当前 |
|---|---|---|---|
| **G0-01 功率回路** | V5 KiCad独立网络一致、DRC/ERC0 | 完整装配的G0选定线路、板卡序号、半桥/Lr/Cr/Cin/SW-Kelvin走线照片、断电导通检查、厂家额定值审查和原生网表校验；上电前独立电气工程师审查 | **PENDING** |
| **G0-02 磁件** | T1–T4/CT逻辑landing，部分候选模型 | 仅需首个G0实用实际磁件：最终真实厂家/试制绕组 3:1:1、DOT/端子引脚核对、CT极性、Lm/漏感/电感矩阵及绝缘试验的原始记录、磁件序号与签核；不能用理想变压器或只有Maxwell的模型代替实物 | **PENDING** |
| **G0-03 双域12V** | THN30双模块 + TPS3710双域UVLO V6 PCB CAD | 两个真实装配偏置电源、原副边无直接返回短路的隔离/漏电测量；V12P/V12S/UVLO信号的实际启动/下降/故障源文件；带驱动负载的保持时间、模块热、保险丝额定审查 | **PENDING** |
| **G0-04 外部断能** | GX14FAC 48V线圈外置接触器的厂家选型候选 | **不经软件的硬接线NC急停**，独立DC额定48V断能执行件和保险丝/预充配合；线圈断线、急停按钮、控制断电、主触点焊接模拟失效、开断时间与下游总线真实电压/电流原始记录 | **PENDING** |
| **G0-05 浮地监测** | 原边驱动芯片数据手册及候选原理图 | 对**GH1相对SW**及**HB相对SW**而不是PGND的真实隔离差分测量及比较器阈值；监测器失电/断线/错误输出必须硬件默认OFF；原始波形和实测失效动作 | **PENDING** |
| **G0-06 60组故障波形** | 已有6种故障×10门极CSV模板 | 覆盖冷启动硬故障、稳态运行故障、原边偏置失效、副边偏置失效、CT输入缺失、ACK常高错误恢复 × GA1–GA8/GH1/GL1；每项具时间轴/仪器序号/门极正负端真实probe接法/VGS关断时间/双管重叠及保护接口和开断事件。务必以MOSFET真实**源端焊盘**为参考，不能简单用远端地线替代 | **PENDING (0/60)** |
| **G0-07 保护时序与SOA** | 既有仿真与示例保持时间 | 按实际 Qg、门极电阻、驱动放电电流、UVLO最坏传播、光耦CTR老化、12V有效电容和器件SOA计算极限；示波器测量关断全过程并与最坏容差核对，评审不能仅引用typical值 | **PENDING** |
| **G0-08 断电预检** | G0测试计划 | **在完全无高能供电的状态**核验电源反接、跨隔离域短路、功率回路短路、耐压与绝缘/极性、保险丝、接触器机械反馈、仪器校准与序列号、独立限流、临时冷却与灭火准备；由合格工程师签字 | **PENDING** |
| **G0-09 最终完整原生板** | V5主板 CAD ERC0/DRC0/Open0 | 实体 G0 磁件+真实保护/偏置+功率板完整组装为同一上电目标；所有安全关键 DRC ignored 分类解除或经明文批准，正式装配版本KiCad数据/制造图纸/PCB序号一致，复检零未连接并签核；不能用自动生成的简化功能原理图代替整机审定 | **PENDING** |

> 以上所有必须**外部**真实测量、合格人员独立审查，不允许脚本代替签署“G0成功”。G0侧先做断电预检与诊断；不具备物理断能、高侧监测、磁件和独立限流时**不得安排48V主功率首次上电**。

## 对现场操作者的最小证据交接

在实验台上、按获批的风险评估和安全SOP操作，使用具备相应隔离/差分额定值的探头、合规直流电源和独立断电硬件。至少保留：

- **板卡与磁件唯一身份**：主PCB版本/序列号、贴装/返工清单、磁件实体DOT和引脚照片、实验批准人员身份。
- **仪器的原始数据及校准信息**：示波器、DMM、隔离/耐压测试仪、电源或电子负载型号与序列号；未修改的波形二进制文件或含完整采样时间轴的CSV，以及测点/通道/接地拓扑。对每个原始文件计算SHA256。
- **故障测试完整性**：使用已存的 g0_gate_fault_capture_matrix_NOT_FOR_FAB.csv，不漏掉 60 对组合；记录断能前后48V母线、门驱电源及VGS。不要使用屏幕截图代替可追踪的原始数据。
- **验收双人复核**：操作者与独立审核人不得为同一人；分别在具体试验结果的日志中签署。将真实测得的文件置于仓库受控的专用物理证据目录或用户指定的合规位置，按SHA登记在 g0_external_witnesses.json；原模板 g0_witness_template_NOT_FOR_FAB.json 为填写示例，**不要伪造已完成字段**。

审计脚本支持后续检查路径、重复组合、原始波形存在性、文件哈希及声明数据的可信边界，不会自动激励电源、操作仪器或产生假测量。

### 本机复验命令

在仓库根目录执行（read-only checks）：

```powershell
& "C:\Users\27792\AppData\Local\Programs\KiCad\10.0\bin\python.exe" tools/d1_g0_package_sr_kelvin_v5.py --check
& "C:\Users\27792\AppData\Local\Programs\KiCad\10.0\bin\python.exe" tools/d1_g0_package_dual_bias_uvlo_v6.py --check
python tools/d1_lane_c_g0_acceptance.py --check
python tools/d1_g0_physical_readiness.py --check
python -m pytest tools/d1_g0_test_physical_readiness.py -q
```

不允许软件/GitHub CI 运行任何控制真实继电器、门极驱动、可编程电源的 G0 上电命令。要执行正式 G0，请由具备实验室安全授权和可接触实物的操作员、审核员在现场签核后遵循经批准的实验程序。
