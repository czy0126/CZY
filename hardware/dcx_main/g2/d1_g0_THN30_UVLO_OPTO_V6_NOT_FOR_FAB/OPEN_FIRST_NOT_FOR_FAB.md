# 双路12V隔离偏置 V6 UVLO/光耦健康信号子板 (NOT_FOR_FAB)

从 V5 双 THN 30-4812 偏置电源2层原生板扩展至115x115mm，放置两只TPS3710DDCR，分别测量 VCC12/PGND 和 VCC12_S/SR_SOURCE_RETURN，两个261k/10k分压在 Ti 400mV上升阈值对应10.84V、下降394.5mV对应10.69V，需要以器件准确度、R温漂和真实噪声进行最坏值复核。每颗有100nF旁路、OUT开漏上拉；副边OUT通过VO617A-3 LED及光晶体管回到原边，原边再经MMBT3904LT1G 反相输出UVLO_S_PRIMARY_OK，与本地UVLO_P_OK 一起提供在J_HEALTH的3针端口上（pin1 P_OK、pin2 S_OK、pin3 PGND）。

该板仅检测两个12V的电压，**没有连到主功率48V急停接触器、真正的UCC栅驱使能RUN或高侧HS监视**，所以不得误认作已实现安全许可。VO617A-3的光耦CTR依赖输入电流、温度/老化，当前约4mA并未签核充足裕量； 光耦只有器件额定耐压，不等于本PCB已通过爬电/灌封/耐压认证。 同时VDD低于POR时TPS3710输出不定；必须由物理 外部默认OFF联锁防止低压假高。

 PCB KiCad10 原生DRC0/unconnected0；由独立 pin/net合同生成的可编辑原生 SCH与PCB 80 pins对齐并执行ERC。输出BOM和 SHA/ZIP完整，不允许上电或送厂。