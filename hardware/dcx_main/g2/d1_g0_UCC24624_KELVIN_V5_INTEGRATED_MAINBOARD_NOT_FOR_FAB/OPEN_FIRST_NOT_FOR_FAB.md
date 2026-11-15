# D1 G0 V5 161器件原生KiCad整合主板（禁止制板/上电）

打开同名前缀的 .kicad_pro。该工程可编辑 PCB/SCH、项目内符号库、真实 KiCad ERC/DRC、netlist、逐脚BOM、V4→V5工程收据及 SHA ZIP。原副边回流仍维持 PGND 和 SR_SOURCE_RETURN 分离，偏置 J_BIAS_P/S 分开。实测的 T1-T4/CT 等实体磁件/安全电源系统并未完成。

新增4个UCC24624同步整流控制器 U3-U6 pin5 VSS 独立 SR_KELVIN_1..4检测线，使用四个 RK1-4 0603 0R 连接至对应SR MOS区域的本地 SR_SOURCE_RETURN；U3-U6 pin2 PGND维持独立门驱电流回流网。感测回路走 In9.Cu，部分过孔是普通12层贯通via，并非工艺验证的专用埋孔或低噪声Kelvin终极布线。真实SR负压关断偏移和噪声实测缺失。

实际C7-C10的REG去耦仍保留原0603焊盘，设计标记 Murata GRM188C71E225KE11, 2.2uF 25V X7S。**11V DC bias时有效电容量可能小于标称2.2uF，尚未完成厂家C(V)曲线与关断验证，不能以标称容值代替实际有效容值**；可以按测量适当并联/改大封装。

原生KiCad PCB DRC=0, unconnected=0; SCH ERC=0, 441个独立 SPICE +外设+可追踪Kelvin ECO Ref-Pin-Net一一匹配。 **仍无 板载48→12V隔离模块/熔断/完整UVLO/独立48V急停/HS差分VGS监控/可认证磁件封装。**不可制造不可直接上48V。 需先把G0的9项实体见证与60组故障波形补齐，并对所有忽略的 KiCad DRC 重新审查。R8启动路径始终DNP，不得自行上件。
