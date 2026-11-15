# D1 Lane A：V17 KiCad 真正布线闭合，7→0 unconnected（2026-11-15，NOT_FOR_FAB）

> 本页记录本工作包**实际修改的原生PCB与实际KiCad 10原生DRC**，不得用于证明原生嘉立创 G1/V18 的全部连接已修复，也不能直接作为上电/发板许可。

## 原始对象与实存回执

| 对象 | 内容 |
|---|---|
| 未覆盖的冻结父版 | `hardware/dcx_main/g2/dcx_main_board_g2_V17_OEM_T530_72_VIN_SW_CANDIDATE_NOT_FOR_FAB.kicad_pcb` |
| 父版 SHA256 | `4bdb3492959aa08e70716a0f6ca020fe8cf98da66f08c795b72f8172b5ab50f9` |
| 新实体可编辑KiCad PCB | `hardware/dcx_main/g2/d1_lane_a_connectivity/six_net_trial_04_NOT_FOR_FAB.kicad_pcb` |
| 新板 SHA256 | `85fff295c2c8bd594266881b711584be02b40b2158e266e8df4a2ba77d6bb76c` |
| 独立CLI DRC | `hardware/dcx_main/g2/d1_lane_a_connectivity/six_net_trial_04_DRC_NOT_FOR_FAB.json`（SHA256 `53a8655f17712561035c024274944debf4ce7888c41123fda98f87d269a08d2b`） |
| 验收报告 | `hardware/dcx_main/g2/d1_lane_a_connectivity/d1_lane_a_0_0_source_locked_gate_NOT_FOR_FAB.json` |
| 物理回读脚本 | `tools/d1_lane_a_verify_native.py` |
| 生成路线脚本 | `tools/d1_lane_a_connectivity_closure.py` |

**真实KiCad 10.0.6 DRC**：原父版为0条rule violations、**7**条unconnected；新板为0条rule violations、**0**条unconnected。没有关闭任何DRC检查来求取0/0，新板仍继承父版已有的5项忽略检查（包括courtyard/footprint过滤器和via接合中心）。KiCad独立回读确认149 footprints、425 native pads、12层铜、11铺铜区保持，原先529个铜对象→580个（净增51个真实trace/via对象），72颗原厂T530实体保持。全部原器件的ref/pad/net逐个一致。

## 本次实际闭合的网络

- **VIN_P**：从Cin.1绕开原边GH/PGND回流连接至QH原边VIN实体热焊盘，4个铜线段。输入热环没有进行电感与脉冲电流验收。
- **SW**：在QH与QL之间构建两组原生F.Cu—B.Cu穿孔回路（每组一对通孔），同时将C5开关检测点与U2.5接通；增20个线/过孔图元。穿孔电流能力、开关尖峰、EMC及100A等效工作点尚未验证，不能标为已合格的完整开关功率回路。
- **GH / GH_DRV / HB**：通过局部F.Cu/BCu独立返回路径完成门极和自举连线（净增GH 8、GH_DRV 5、HB 9个图元），排除草稿中的跨网铜线交叉。真实VGS/自举与开关过冲波形待测。
- **OC**：U1.3经原生过孔与B.Cu长线连至远端OC器件，净增4个图元。U1.3采用**试验性的过孔入焊盘**，其填孔/盖帽工艺未获厂家验收；OC约几十毫米的高阻/保护传输链需要抗干扰和真实故障关断验证，不得把DRC 0当作保护验证通过。
- **RT**：为避免OC与RT跨网净空不足，将原RT底层线分为有明确转角的两段，源、目的pad/net不变，净增1条图元。

**全部有效DRC错误已清零**是针对**已经存在KiCad板里的部分元件和网表**，不是对缺失的5套磁件/24个物理端子进行补零；也不是对原生EasyEDA G1 2026-11-15原始回执的146 Connection/1 Netlist错误补零。两类证据不能混用。

## 首次上电前的真实阻断

1. **CT、T1—T4五套实物绕组/引脚没有加入此KiCad PCB**，完整SCH-PCB ERC/网表逐脚匹配尚未通过；本PCB不是可运行LLC完整电路。
2. SW 连接用了通孔转层，热态铜阻/孔铜电流/回路杂散电感/开关应力没有验收；Cin充放电与突入限流未验证。
3. OC 保护路径的新U1过孔入焊盘未厂家签核，真实输入欠压/OC/D0失偏置强制OFF及十路SR VGS尚未做台架验证；不可高能量上电。
4. 12层叠构、铜厚、原厂主驱动不规则焊盘、绝缘、5个已有忽略DRC与EMI均未签核；持续`NOT_FOR_FAB`。
5. 3 LPM冷板属于后续G3，**不阻塞G0基本电路验证**；但轻载首试仍必须有适当临时散热/限流/隔离和安全关断能力。

## 复测方法

```powershell
& 'C:\Users\27792\AppData\Local\Programs\KiCad\10.0\bin\kicad-cli.exe' pcb drc --severity-all --format json --output hardware/dcx_main/g2/d1_lane_a_connectivity/fresh_DRC_check.json hardware/dcx_main/g2/d1_lane_a_connectivity/six_net_trial_04_NOT_FOR_FAB.kicad_pcb
& 'C:\Users\27792\AppData\Local\Programs\KiCad\10.0\bin\python.exe' tools/d1_lane_a_verify_native.py
D:\anaconda3\python.exe tools/d1_lane_a_gate.py --check
D:\anaconda3\python.exe -m pytest tools/test_d1_lane_a_gate.py -q
D:\anaconda3\python.exe tools/d1_lane_a_gate.py --require-release
```

上述`--require-release`故意返回2，表示**不能制造/上电**。若在板上补磁件、修正任何焊盘、改变铜线或生成制造文件，必须按新SHA重跑KiCad DRC和网表检查，**不复用旧0/0**。
