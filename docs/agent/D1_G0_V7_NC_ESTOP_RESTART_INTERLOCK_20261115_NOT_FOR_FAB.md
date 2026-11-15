# D1 G0 V7：常闭物理急停 + 故障后人工重新启动锁存（原生 KiCad）

2026-11-15，PR #136，工程位于 hardware/dcx_main/g2/d1_g0_ESTOP_INTERLOCK_V7_NOT_FOR_FAB/。

**严禁制板、上电：NOT_FOR_FAB / G0 BLOCKED。** 该版本是可编辑 KiCad 原理图与PCB实体布局候选，尚未连接真正GX14FAC高流主触点或独立高侧监测器，不能充当安全认证的急停装置。

## 已建立的物理断电铜路

48V预功率辅助电源 J_AUX48 → F_COIL保险丝位置 → J_ESTOP_PWR.1；外置机械常闭急停触点A接在 J_ESTOP_PWR.1和.2之间，**PCB不短接这两个不同网络**；J_ESTOP_PWR.2 → GX14FAC外置线圈正极 J_GX14COIL.1；线圈负极J_GX14COIL.2 → Infineon IRL540NPbF Q_COIL的Drain2；Source3 → PGND。Q_COIL的Gate1设100Ω驱动电阻、100kΩ下拉与13V栅源候选钳位（后两项仍待厂家型号/焊盘/实际门压核验）。48V辅助电源连接与主功率母线连接必须各自有独立额定熔断保护、预充和机械开断。

Sensata GX14FAC 48V线圈已经内置Transorb，厂家**禁止再并联外部续流二极管**。正式设计还要审查线圈极性/内部抑制器、48VDC接触器吸合浪涌、无控制器时的默认失励、实际开断延迟、接触器触头焊住后如何检测下游母线。 **GX14主触点没有实际装板或线束接入。**

## 已建立的逻辑电气原理图

TI CD4081BE 4个二输入AND实现：
- 门1：原边12V健康 UVLO_P_OK 与副边光耦健康 UVLO_S_PRIMARY_OK
- 门2：外置独立浮地HS监测器 HS_OK_IN 与机械联动的第二常闭急停触点B ESTOP_MON_OK
- 门3：两组AND得出 ALL_HEALTHY
- 门4：ALL_HEALTHY 与 TI CD4013BE 的 LATCH_Q，共同驱动COIL_ENABLE

CD4013BE使用实际芯片pinout：Q1 pin1，CLOCK1 pin3，RESET1 pin4，D1 pin5，VDD pin14，VSS pin7。外置J_ARM需接**瞬时常开人工启动按钮**，只有健康状态下新的ARM上升沿才能使Q=1。任一健康条件丢失时，Q_RESET NPN释放RESET_ACTIVE的10k上拉，触发异步Reset=HIGH，Q立即归零；仅恢复健康状态、持续按住ARM而没有新上升沿**不会自动重启**。外部逻辑输入均有100k硬件下拉，失联默认为0。数字故障注入模型覆盖16种健康组合、故障时清除锁存、接触器NC直接断能、人工重启要求。

**特别强调：目前控制信号的PCB并非全部布完。** 即使原生SCH ERC0，物理PCB DRC0也不等于unconnected0。必须以最终出厂PCB的原生DRC/所有未连记录、真实信号时序及安全评审为准。绝不在未验收的情况下把J_HS_OK跳为高以绕过高侧监测。

## 厂商数据与未闭环项目

- Sensata GX14： https://www.sensata.com/sites/default/files/a/sensata-gigavac-gx14-series-open-contactors-datasheet.pdf
- TI CD4081B： https://www.ti.com/lit/ds/symlink/cd4081b-mil.pdf
- TI CD4013B： https://www.ti.com/lit/ds/symlink/cd4013b.pdf
- Infineon IRL540N： https://www.infineon.com/assets/row/public/documents/24/49/infineon-irl540n-datasheet-en.pdf

实际主功率48V NC接触器/双触点急停开断失效验证未完成；第二路常闭触点不等于双通道功能安全控制器；独立高侧GH−SW、HB−SW监测器尚未实装；真实Fuse DC分断能力、MNP/线束防反插、线圈吸合/开断、电源保持时间、功率G0实物板和磁件端子/DOT/绝缘、60路示波器原始故障波形均无实测证据。所有G0九项物理验收依然PENDING。

**不能采用本轮CAD或软件模型放行48V，上电权仍由具备实验室资质的现场工程师按批准SOP独立判断。**
