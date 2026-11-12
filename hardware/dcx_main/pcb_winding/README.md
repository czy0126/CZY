# Lr 三匝穿板绕组：独立 KiCad 原生工程（非制造版）

本目录的 `ELP38_Lr_3turn_PCB_EMBEDDED_CONCEPT_NOT_FOR_FAB.kicad_pcb` 是**独立、可编辑的六铜层电路板**，不是现有 EasyEDA 主功率板的替代原稿。单匝分别并联两层铜箔，再经独立贯穿过孔串联成三匝；板内实际有 ELP38 中柱和两侧磁芯腿的三处贯通开槽。两端是板载通孔端子。板上的全部铜线都用一个逻辑网络描述，因此 **KiCad DRC 不知道什么是“一匝被自身短路”**：脚本另设同层非相邻线段、跨层孔壁与其他匝间距的专项检查。

唯一几何、层叠与损耗试验参数位于 `../../../design/v3/maxwell/pcb_embedded_lr_3turn_candidate.json`（仓库根目录相对入口为 `design/v3/maxwell/pcb_embedded_lr_3turn_candidate.json`）；计算结果、源 SHA、温度电阻与完整限制条件在同名 `.json`，原生 KiCad10 DRC 原文在 `.drc.txt`。

```powershell
D:\anaconda3\envs\dc-dc\python.exe tools/pcb_embedded_lr.py --write
D:\anaconda3\envs\dc-dc\python.exe tools/pcb_embedded_lr.py --check
D:\anaconda3\envs\dc-dc\python.exe tools/pcb_embedded_lr.py --drc
D:\anaconda3\envs\dc-dc\python.exe -m pytest tools/test_pcb_embedded_lr.py -q
```

当前只完成 **Lr 三匝 PCB 工艺候选**，尚未设计 T1–T4 的 P/S_A/S_B 独立绕组、绝缘层压和中心抽头/DOT，也没有 CT 的100匝绕组。正式主板、冷板接口、出线回路及热设计均未被此文件修改。特别需要验证厂商能否制作所提六层/每层厚铜/开槽/通孔工艺、过孔在故障峰值下的温升、气隙边缘邻近损耗、真实非线性N97 100°C增量 `L(I)` 以及包括夹具/TIM/冷板的16mm全装配高度。**0 DRC不是0故障，也不是制造许可。**

下一步在原有原生线圈板上运行 `python tools/pcb_embedded_lr_dfm.py --check` 和 `python -m pytest tools/test_pcb_embedded_lr_dfm.py -q`。该检查仅用同版本 CAD + 已记录的真实Lr电流合同，计算串联贯穿孔在多档假设孔铜厚度下的理想直流损耗，产出 [过孔瓶颈计算与来源哈希](ELP38_Lr_3turn_PCB_embedded_DFM_via_screen_NOT_FOR_FAB.json) 及 [厂家核对表](ELP38_Lr_3turn_PCB_embedded_factory_review_NOT_FOR_FAB.csv)。厂商实测孔铜、脉冲SOA、200 kHz场损耗、温升均未签核；不允许凭试算值直接放行当前单孔方案。

**已另建多过孔对照板**：`ELP38_Lr_3turn_PCB_EMBEDDED_4VIAS_PER_TRANSITION_TRIAL_NOT_FOR_FAB.kicad_pcb` 不覆盖原双单孔板，使用每串联换层节点4只PTH与前一匝双层焊盘支路。通过 `python tools/pcb_embedded_lr_4via_trial.py --check`、`--drc`、`python -m pytest tools/test_pcb_embedded_lr_4via_trial.py -q` 检查原生CAD、第三匝串扰/短匝、KiCad真实DRC。四孔均分是假设，不代表真实电流均分；支路对实际磁场和热设计的影响、过孔填孔/铜厚与绝缘均待物理验证，不要直接用该候选替换主板。

**圆角锣槽独立对照板**：原方角Edge.Cuts槽不满足大多数铣削刀具的实际内角；另建立 [`ELP38_Lr_3turn_PCB_EMBEDDED_ROUNDED_SLOTS_4VIAS_DFM_NOT_FOR_FAB.kicad_pcb`](ELP38_Lr_3turn_PCB_EMBEDDED_ROUNDED_SLOTS_4VIAS_DFM_NOT_FOR_FAB.kicad_pcb)，设计自选R0.8mm圆角、与原矩形磁芯让位相容的扩大开槽，并同步外移所有3匝线圈导体以保留铜-槽净距。运行 `python tools/pcb_embedded_lr_rounded_core_via_array.py --check`、`--drc`，且 `python -m pytest tools/test_pcb_embedded_lr_rounded_core_via_array.py -q`。本机KiCad10 DRC通过；工厂开槽R/铜厚、磁芯实物与绕组L(I)未验证，**只作为厂家制程询问与CAD筛选，不是投板批准**。
