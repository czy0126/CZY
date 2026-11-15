# D1 G0 V6 双路偏置 UVLO 实体 KiCad 与接触器候选交接

2026-11-15。**G0 BLOCKED / G1 PENDING / NOT_FOR_FAB；未做实体硬件验收，不允许送厂或直接给主功率48V上电。**

推荐 ZIP：hardware/dcx_main/g2/d1_g0_THN30_UVLO_OPTO_V6_NOT_FOR_FAB/G0_V6_TWO_THN30_UVLO_OPTO_KICAD_NOT_FOR_FAB.zip

V5主功率PCB继续保留：hardware/dcx_main/g2/d1_g0_UCC24624_KELVIN_V5_INTEGRATED_MAINBOARD_NOT_FOR_FAB/G0_V5_161_PART_KELVIN_SOURCE_AUTHORED_EDITABLE_KICAD_NOT_FOR_FAB.zip

## 本轮已执行的真实 CAD 变更

在既有2×Traco THN 30-4812双域12V偏置子板的原生 KiCad PCB 中，扩展母板边框至115×115mm、重做原副边地及输出12V铜区，新增共17个真实器件封装（总30）。保留两只隔离模块、两只输入熔断器位置、各路输出滤波与对应原边/副边两线端子。

新增2×TI TPS3710DDCR SOT-23-6 低压检测IC，两个独立261kΩ/10kΩ 1%分压网络、100nF旁路与开漏输出上拉。厂商原始DDC针脚：1 OUT、2/4/6 GND、3 SENSE、5 VDD。独立PGND与SR_SOURCE_RETURN回流不短接。上升门槛标称10.84V、下降10.69095V，**实际温度、电阻公差、传播延迟、瞬态噪声尚未验证**。

新增 Vishay VO617A-3 DIP4 optocoupler：副边1 LED阳极、2 LED阴极；原边3光晶体管发射极、4集电极；之后用 onsemi MMBT3904LT1G SOT-23（1 Base、2 Emitter、3 Collector）反相并上拉得到原边可读取的副边偏置健康电平。J_HEALTH 三针：1原边UVLO_P_OK，2经光耦传回的UVLO_S_PRIMARY_OK，3PGND。

**这三个针脚仅为状态观察接口，不是主功率使能，不是物理48V断能，也不是安全继电器输出。** 副边 LED 实际偏置约4mA时VO617A-3光耦 CTR 的温度/老化、传播时间与源极接地噪声尚未签核；实际 PCB 光耦器件额定隔离不等于铜板层间/爬电距离认证。供电低于TPS3710的POR时OUT不确定，必须由额外默认关闭的硬件联锁解决。

源：
- TI TPS3710 Rev A：https://www.ti.com/lit/ds/symlink/tps3710.pdf
- Vishay VO617A Rev 2.8：https://www.vishay.com/docs/83430/vo617a.pdf
- Onsemi MMBT3904LT1G：https://www.onsemi.com/download/data-sheet/pdf/mmbt3904lt1-d.pdf

原生 KiCad 10 检验：V6偏置PCB有30个元件、80个独立来源的Ref-Pin-Net，SCH导出网表与PCB的Pad-Net逐项一致；**ERC=0，PCB DRC=0，未连接=0**。保留四项KiCad原生忽略检查的明细在DRC报告中；正式发板之前逐项人工评估。

## G0-04 主功率48V物理断能接触器，已查证厂家候选，但尚未接线

外置机械接触器候选：**Sensata GIGAVAC GX14FAC**，48VDC线圈、350+A主触点SPST-NO、NC辅助触点，额定12–800VDC；48V线圈吸合最大0.97A(75ms)、维持约0.042A，厂家给出最大释放时间12ms。资料：
https://www.sensata.com/sites/default/files/a/sensata-gigavac-gx14-series-open-contactors-datasheet.pdf
https://www.sensata.com.cn/products/gigavac-power-contactors-fuses/gx-contactors-800v/gx-normally-open-contactors/gx14-series

相比GX14B型号的12V线圈最大3.9A启动电流，12V THN30 2.5A额定输出不足以直接保证吸合，故推荐使用48V线圈的GX14FAC候选、线圈由预功率急停电源分支及独立熔断器供电、**机械急停常闭触点需串入线圈电源以实现断电失励**。线圈电气控制仍需要48V额定裕量的低侧开关驱动、隔离信号和真实输出硬件门禁；此时V6 UVLO状态才能参与AND门判定。接触器不是熔断器，仍需预充、短路熔断保护和可靠母线断电。辅助NC反馈不足以单独排除主触头焊接，须以断能后负载端母线电压/电流原始测试佐证。

**尚未实装** GX14FAC、控制驱动器、外部高侧GH-SW差分VGS监测器、G0首次上电时所有波形。该部件候选不得标记G0-04 PASS。

## 当前 G0 实物验收还缺

- 九项物理G0验收全PENDING；十路VGS×六种故障共60组真实数据未采集。
- 外置机械48V断能、UVLO转实际安全RUN/GATE硬件联锁、完整HS VGS漂浮监测、UVLO最坏响应时间和真实门极残余电荷尚未接线/测试。
- 12V实际负载峰值、降额后的输出有效电容和保持时间尚未测定。两只22µF标称滤波电容不能代替经过实测的毫秒级保持电源。
- T1–T4/CT只有逻辑端子，缺实体绕组、DOT、漏感矩阵、磁芯饱和与隔离工艺；12层开槽/铜损/过孔DFM、温升和EMC仍待实测。
- 原V5主板R8启动使能依然DNP，不可自行装焊绕开硬件安全阻断。

复核：Windows KiCad 10 bundled python.exe 运行 tools/d1_g0_dual_bias_uvlo_v6.py --check 和 tools/d1_g0_package_dual_bias_uvlo_v6.py --check；普通Python运行 python -m pytest tools/d1_g0_test_dual_bias_uvlo_v6.py -q 和 python tools/d1_lane_c_g0_acceptance.py --check。ZIP/JSON附SHA哈希，不能取代实物G0验收。
