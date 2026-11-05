# 35 · 研发停滞根因与 Maxwell 磁件验证最短路径（2026-11-05）

> 当前 D1 唯一首样目标：48 V / 24:1 / 100 A级 / ≤16 mm（目标）。D2 120 A 和 D3 10 mm 不在首样关键路径。本文不是新的投板授权。

## 一、停滞机制：已验证的计算没有转变成可执行工件

| 反复循环 | 已有证据 | 改进动作 |
|---|---|---|
| 模型结果多，硬件证据少 | LTspice 和状态机验证很多，D0 十路 VGS 关断示波器记录仍缺 | 先完成一组低能量实物关断对照，禁止以仿真替代实测 |
| 有效设计基线模糊 | 旧 ELP32/10 mm 工艺卡、检查表与现行 ELP38/16 mm RFQ 并存 | 唯一 D1 活动基线；所有历史文件标记 LEGACY/CONCEPT，不得直接下单 |
| 把供应商回复当成所有工作的前提 | 24 端子、成品公差尚未返回 | 先用已验证目录尺寸和几何草模进行 Maxwell 概念筛选，询样与PCB布线并行 |
| 计算方法不对准关键问题 | 简单 L I/(N Amin) 只能筛选磁密，不能保证偏置 L(I) 或局部饱和 | Maxwell 3D 非线性静磁场 + 交流涡流 + 实物验证逐层推进 |
| 串行验收导致停摆 | 100 A 最终放行限制不合理地阻止磁件询样、D0台架、PCB布局 | 放行门只限制对应高能量步骤，不限制低风险准备工作 |

## 二、当前磁件矛盾（本轮可复算）

现行 Lr 优先 ELP38 + I38 N97，Amin=192 mm²，Ae=194 mm²，AL0=8400 nH/turn²；外置目标0.92 µH，总谐振电感1.0 µH。以121.515 A的RFQ筛选电流而非实际额定电流计算：

| 备选结构 | 简化总气隙 | L I/(N Amin) | 0.248 T筛选 |
|---|---:|---:|---|
| 2匝 0.92µH | 1.031mm | 0.291T | 超出 |
| 2匝 1.0µH | 0.946mm | 0.316T | 超出 |
| 3匝 0.92µH | 2.356mm | 0.194T | 通过磁密筛查；气隙超出厂家示例公式2mm范围 |
| 3匝 1.0µH | 2.165mm | 0.211T | 通过磁密筛查；气隙超出厂家示例公式2mm范围 |

121.515 A 是带余量的询样应力点；模型故障峰的104.17 A不是相同工况。静态线性电感假设不能证明饱和或100°C增量电感；2mm是厂家气隙示例公式适用范围，不代表定制加工绝对不可能。

复算：python tools/maxwell_magnetics_prescreen.py；回归：python -m pytest tools/test_maxwell_magnetics_prescreen.py -q。

## 三、Maxwell 3D 两阶段、两条线

第一阶段 Lr（立即筛选2匝/3匝）：可先由工程师按原厂目录自行建立可追溯的ELP38与I38概念 STEP（含气隙、绕组形状和端面），**无需等供应商STEP**；但必须记录CAD与真实几何的差异，不可用于最终制造签核。100°C非线性N97 B-H 曲线优先采用原厂或实测，初期亦可采用带明确误差与出处的插值概念曲线，只用于方案排除而不对高电流性能签核。Maxwell Magnetostatic求不同 I 下磁链/增量 L(I)、局部 B、气隙边缘磁通与边柱饱和。检查0.5 /13.881/22.53/84.02/104.17/121.515 A六点，至少三个网格等级，电感差异拟控制在2%以内（计划阈值，尚无结果）。需要区分L_secant与L_incremental。

第二阶段交流损耗：使用 Eddy Current / AC Magnetic，依据真实0.1mm铜箔、引出端形状及约200.622kHz与其关键谐波，分析J分布、邻近效应、气隙边缘铜损。第一阶段stranded近似不能计算该铜损。磁芯损耗还需要实际N97的B-f-T损耗数据，不能从磁静态B-H直接推出。

变压器T1-T4应另建P1/S_A/P2/S_B/P3及端子、DOT的3D模型，求漏感矩阵、Lm、热点与AC铜损；正常工作磁芯ΔB来自绕组电压伏秒积分，绝不能把谐振电感Lr的电流磁通公式直接用于变压器。实物T1-T4漏感测出后，再冻结外置Lr=1.0uH-总等效漏感。

## 四、本次已经放入代码的执行入口

- tools/maxwell_magnetics_prescreen.py：读取真实lr_design.json源参数，计算四个备选，不伪称已执行Maxwell。
- design/v3/maxwell/elp38_lr_maxwell_contract.json：四套独立CAD案例，明确STEP、B-H、部件名称和必须完成的审核；概念 CAD 允许设计组自行重建，供应商几何最终确认与概念建模分离。
- tools/maxwell_lr_from_step.py：--check 仅列阻塞；在经过审阅的概念STEP、带来源的非线性材料与审核输入齐备后，--build通过PyAEDT导入Maxwell 3D，设置非线性静磁场模型、线圈、矩阵并保存工程；--solve逐电流点调用求解器，但不伪造L/B结果。
- tools/test_maxwell_magnetics_prescreen.py：自动回归两匝/三匝真实冲突及预防假签核。

可执行命令：

~~~bash
python tools/maxwell_magnetics_prescreen.py --out design/v3/maxwell/prescreen.json
python tools/maxwell_lr_from_step.py --check --case ELP38_Lr_2turn_0920uH
# 在有Maxwell授权且准确导入STEP、100C B-H后：
python tools/maxwell_lr_from_step.py --build --case ELP38_Lr_2turn_0920uH --aedt-version 2026.1
python tools/maxwell_lr_from_step.py --solve --case ELP38_Lr_2turn_0920uH --aedt-version 2026.1
~~~

所需几何必须含不同的ELP38_FERRITE、I38_FERRITE、LR_FOIL_COPPER、LR_COIL_TERMINAL模型/端面对象。另须在AEDT导入并验证可溯源非线性N97材料、线圈匝向/安匝约定和网格；全部输出逐个记录版本与模型SHA。不能由--solve返回true自动宣称任何L(I)、温升、零件制造合格。

官方操作参考：[PyAEDT Maxwell 3D Magnetostatic例子](https://examples.aedt.docs.pyansys.com/version/dev/examples/low_frequency/magnetic/3d_magsta_rotational_actuator.html)；[Ansys Magnetostatic winding指引](https://ansyshelp.ansys.com/public/Views/Secured/Electronics/v261/en/Subsystems/Maxwell/Content/Maxwell/AssigningaWindingSetupforaMagnetostaticSolver.htm)。

## 五、不再串行等待的退出规则

| 并行任务 | 立即可以执行 | 仍不可替代的最终实物证据 |
|---|---|---|
| D0a低能量关断 | 与磁件、账本无关，继续一对驱动技术A/B实测 | 原始门极VGS/故障波形；供电失效/断线/复位验证 |
| 主板有网PCB | 允许有明确冻结区和替代占位的前期关键铜路设计 | 真正核对网络、厂家端子、ERC/DRC、实际保护 |
| Maxwell几何/扫参 | 用实际数据手册和设计图进行初选，不等样件 | FEM真实材料/网格收敛结果与后续实物L(I)/DCR/漏感 |
| 磁件询样 | 先给两家供应商询ELP38/43或定制结构 | 真实端子/DOT与制造公差、报价、首件测量 |
| 主功率100A上电 | 不等D3 10mm和末尾0.09W账本 | 完整保护、SOA、铜路及磁件验证后逐级安全上电 |

**限制**：当前可访问的执行环境没有Ansys Maxwell授权程序、可执行的模型STEP或有来源的100°C非线性B-H数据，所以本次完成的是参数复核和可执行入口，而不是声称已求解出磁场云图。厂商回件仍须继续，但不得因此停止PCB和D0a进度。

最终原则：每次迭代必须回答一个可以结束的技术分歧，并产出CAD/求解结果/样品或原始波形；不继续用新的规划文档替代这些工件。
