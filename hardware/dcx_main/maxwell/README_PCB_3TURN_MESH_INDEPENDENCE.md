# 三匝六铜层 PCB Lr：Maxwell 真正网格无关性实验（非制造资格）

2026-11-12 在真实 Ansys Electronics Desktop 2025 R2 上，从相同的三匝六层 KiCad 转换的可编辑 Maxwell 原生工程出发，以同一 1 A 直流激励，运行两套独立自适应加密策略并保存场结果与网格原始文件。

| 方案 | 早期7%初算 | A（1%/25%加密） | B（0.5%/30%加密） |
|---|---:|---:|---:|
| 实际完成轮次 | 2 | 6 | 7 |
| 最后四面体数 | 58,262 | 148,280 | 234,536 |
| 原生最终能量误差 | 5.7135% | 0.46082% | 0.23956% |
| 最后能量变化 | 5.3555% | 0.17451% | 0.095291% |
| Maxwell FieldsReporter 能量(J) | 8.9265540e-7 | 8.7051999e-7 | 8.6906713e-7 |
| 1 A 能量等效L(µH) | 1.7853108 | 1.7410400 | **1.7381343** |

两套不同加密策略最终场积分相差 **0.1671747%**；各自最后两个加密步能量变化都小于 0.5%。本固定模型在预先定义的跨网格相对差 <= 1% 标准下已通过数值稳定性检查。早期7%初算相对B偏高 2.7142%，不能当作稳定数值。

目录保存两套独立原生 .aedt 工程、原生 .conv、实际求解 .receipt.json、独立场积分 .field_energy.json、真实网格/场文件 .results.zip，以及包含原始每轮网格结果及SHA的 ELP38_Lr_PCB_3TURN_TWO_INDEPENDENT_MESH_STUDIES_1A_NOT_FOR_FAB.json。离线复核：python tools/aedt_pcb_embedded_3turn_mesh_independence.py --check；回归：python -m pytest tools/test_aedt_pcb_embedded_3turn_mesh_independence.py -q。重新求解时必须使用全新独立路径，不允许覆盖当前求解结果。

**物理模型仍未确认**：磁芯材料为库存通用 ferrite、不是实测100°C N97非线性B-H；气隙、25µm孔铜、FR4/开槽为概念简化，两根人工延长的外部引线改变总场能。1 A DC能量等效L不等于实物0.92µH额定值、高电流增量L(I)、200kHz交流损耗、温升或16mm机械合格。数值网格无关性不批准改变气隙或投板，始终 NOT_FOR_FAB。
