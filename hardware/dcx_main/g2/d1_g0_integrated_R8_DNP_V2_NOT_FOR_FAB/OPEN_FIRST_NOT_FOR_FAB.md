# KiCad 10 G0 V2 155器件整合板 (NOT_FOR_FAB)

打开同名前缀 kicad_pro 工程。主板是真实 KiCad PCB 原生铜路，包含已经放置的 R8 1k 启动使能元件物理焊盘，但 R8 **DNP 未装配**，RUN 保持受 R7 下拉的关闭状态。

已验证源独立 SPICE 控制/功率引脚映射差异为0；KiCad PCB DRC=0，unconnected=0，schematic ERC=0，429个唯一 Ref/Pin/net 核对。

禁止制造和直接上电：PCB 的主副边 PGND 仍共用，四个 U3-U6 和八个SR和 72 个输出电容均在该公共网；In1.Cu 大平面跨两域。必须在 d1_g0_secondary_return_eco_pin_table_NOT_FOR_FAB.csv 约束下重分 129 个实体焊盘并完整修改zone/trace/via，重新检查隔离。真实隔离12V、UVLO、物理48V急停和高侧VGS监测均未装入主板。T1..T4/CT 仅逻辑端子，厂家PIN/DOT/绝缘及真实绕组未验。原理图是从PCB Pad/Net反向导出的校对图，不是独立正式功能原理图。当前 G0 BLOCKED, G1 PENDING, NOT_FOR_FAB。
