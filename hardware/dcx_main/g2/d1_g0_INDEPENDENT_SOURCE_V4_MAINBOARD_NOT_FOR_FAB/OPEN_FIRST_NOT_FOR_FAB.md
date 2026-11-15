# D1 G0 V4 157器件：真实PCB + 独立黄金设计来源的KiCad原理图

首选打开本目录同名前缀 kicad_pro 工程。ZIP同时包含 KiCad PCB、独立电气设计来源 SCH、本地符号库、原生网表、ERC/DRC、BOM、129物理焊盘迁移表、三段工程证据及 SHA 验收报告。

PCB实际完成：129副边焊盘迁入 SR_SOURCE_RETURN，181条副边铜线/过孔重新分网，In1原副边地平面物理分割，T4初级回流经槽间走廊接原边；R8启动1k焊盘已接入但 DNP，不启动。新增独立原边 J_BIAS_P(VCC12,PGND) 与副边J_BIAS_S(VCC12_S,SR_SOURCE_RETURN) 实体2x5mm暂定PTH端子。PCB ERC/DRC及未连接均0（具体见报告）。

SCH不是PCB反向投影；它独立来自 SPICE黄金netlist、真实库pin扩展、控制外围寄存器、72颗电容设计及公开的129pin SRET工程变更。157个Ref/Pin/Net逐项与PCB核验，总433个独立pin，SCH ERC0。但仍是**工程化简符号与逻辑连接**，并非真实电路安全功能签核，控制器物理接线和器件参数须进一步审查。

严禁直接制板/通电：厂商磁件端子/DOT/匝比/耐压未验；没有板载双路隔离12V转换、UVLO、硬件独立48V急停、浮地VGS监测及十路门极实物故障验证；外部12V连接器MPN/熔断及12层Stackup/via/开槽、铜损、温升/EMC均未签核。五类KiCad ignored DRC仍存在。安全许可G0 BLOCKED/G1 PENDING。
