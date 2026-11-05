# Fast-OC 快速过流验证 PCB：真实订货型号与装配停止条件（2026-11-05）

**工程状态：可编辑 KiCad 原理图 + 已布线验证小板 + Gerber/钻孔/坐标齐全；没有实物测量、没有制造/装配批准。** `fab/manifest.json` 的 `fabrication_approved=false` 必须保持。仅有零 ERC/DRC 不代表“型号能贴上”或“保护有效”。

## OEM 核对后，已直接落进源生成器、原理图、PCB、BOM、网表和装配文件的四个实体位号

| 位号 | 原 BOM 表述（不能作为匹配采购） | 已选可核验订货号 | 必须匹配的实际封装 | 官方依据 |
| --- | --- | --- | --- | --- |
| D1、D2 | `BAT54`（**普通BAT54是SOT-23 3引脚**，与原PCB的SOD-123不匹配） | **ST BAT54ZFILM** | **SOD-123 两端子**，同一单二极管极性 | [ST BAT54系列官方datasheet，第11表](https://www.st.com/resource/en/datasheet/bat54.pdf) |
| U1 | `TLV3501AIDBV`（原理图符号/型号家族，缺正式包装后缀） | **TI TLV3501AIDBVR** | **DBV SOT-23-6** | [TI 可订货型号](https://www.ti.com/product/TLV3501/part-details/TLV3501AIDBVR) |
| U2 | `LM4040DBZ-2.5`（器件族描述，不是精确订货型号） | **TI LM4040D25IDBZR** | **DBZ SOT-23-3** | [TI 官方载带/封装记录](https://www.ti.com/packaging/docs/carriermaterial/carrierlookup?OPN=LM4040D25IDBZR&state=details) · [TI LM4040数据手册](https://www.ti.com/lit/ds/symlink/lm4040.pdf) |

**必须强调**：`Comparator:TLV3501AIDBV` 是 KiCad 元器件**符号库ID**，不能随采购型号替换成虚构的 `Comparator:TLV3501AIDBVR`。实例 `Value`、PCB `Value`、BOM `MPN` 才是本次已核实的采购对象。D1/D2的标称30 V在原 BOM 的 Rating 字段中是**设计筛选文字**；ST产品真实反向电压按40 V数据手册审核，具体降额、VF/IF/尖峰仍需设计复核。

**U2 的第三脚不是 NC。** TI DBZ 引脚 3 标识“\*”，厂家规定**浮置或连接到阳极 pin2**；在开关磁件高 EMI 环境建议接阳极。当前板采用两脚符号，pin3在PCB焊盘上未连接：这符合手册允许的浮置用法，但不能误称为内部无连接。若需要进一步抗干扰，下一ECO须明确画出pin3→PGND、重新布线并重出Gerber/DRC；不得仅更改 BOM 注释就宣称已改善EMC。

## 一句话说明为什么没有直接批准下单

当前 26 个实体位号中只有上述 **4 个位号**（其中两只同一BAT54Z型号）已在 BOM `MPN` 栏落实官方订货号；**其余 22 个仍无具体MPN/封装厂家SKU**。它们包括输入接口、钳位MOS、阻容和测试点等，不能让代工厂随意“同规格自动替代”后声称是受控的保护样板。特别需确认开关管 Q1 的真实G/S/D脚号与订单器件封装，以及D1/D2方向丝印是否与阴极带一致。

**真实投板/装配的最短交付出口**：

- 首先冻结其余22个器件的实际采购号/允许的经审查等效件，把制造厂、温度、电压/电流降额、0.2 mm线距/0.3 mm孔径与装配板材确认写入回件，不允许只写`BAT54`等大族名称。
- 在 KiCad GUI 重新打开原生PCB，人工核对U1 DBV6脚、U2 DBZ3脚、D1/D2 SOD123阴极方向与实物封装；导出真实ERC/DRC、Gerber与装配坐标后与`fab/manifest.json` 哈希再对一次。**本次代码已同步更改位号价值属性和受影响的文件哈希，但没有替代这个GUI步骤。**
- 将快速过流模块的`OCD/V5/PGND/FAST_TRIP`四线接到真正D0锁存，使用**低能量试验**测量比较器输出、欠压、输入过冲、最慢总关断延迟；FAST_TRIP开漏电平不能独自构成完整硬件保护。保护/制造标志在这些测量前保持false。

检验入口：`python -m pytest tools/test_fast_oc_vendor_ordering.py tools/test_make_fast_oc_eco.py tools/test_make_fast_oc_pcb.py -q`；`python tools/manufacturing_index.py --check`；`python tools/ci_check.py`。

本次修改 **F.Cu/B.Cu、阻焊、钻孔几何未改**，因为纠正的是有相同焊盘几何的实际采购料号，不是接线ECO。未来重跑 `python tools/make_fast_oc_pcb.py --fab` 要以正式现场Kicad版本重新生成并校验新哈希；不要混用不同批次的Gerber/装配BOM。
