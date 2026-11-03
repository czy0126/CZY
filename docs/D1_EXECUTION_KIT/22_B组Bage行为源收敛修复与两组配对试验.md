# 第22章：B组收敛机理排查——一次只修一个行为模型硬限幅

**2026-11-04 审核发现**：1fF B_CONTROL停254.980µs；2fF B_CONTROL运行至264.515µs出现`Convergence Failure`、LTspice指名`xsr3:x2:Bage`；5fF B_CONTROL停235.890µs。因此cshunt效果不单调，继续扫10fF不是有明确机理的首选。此前后两组候选都能完成320µs，但对照失败；真实硬件保护与负载SOC仍不可宣称通过。

## 原始模型缺陷与针对性修改

`models/sr_timing_v3_3.lib` 的 `SR_CH3` 子电路中 `Bage` 积分器是 `if(V(Q,S)>.5,if(V(age,S)<10,-1m,0),V(age,S))`，电压age到10V后电流从−1mA瞬跳到0。在正常SR时序中唯一使用age的地方是 `BON=475ns` 时的0.475V门槛，10V硬限幅远高于此。但长时间gate-high、postfault状态可能落到10V硬边界，导致求解器需要无限减小步长。

新增完全独立的 [v3_4 age-soft-rail模型](../../models/sr_timing_v3_4_age_rail.lib)，**仅改一行**：`if(V(Q,S)>.5,-1m*limit((10-V(age,S))/0.1,0,1),V(age,S))`，在9.9V前保持原斜率，在9.9–10V平滑减小电流；这与原v3_3早已采用的Boff数值软轨同构。`Bton`和`Btoff`的潜在硬轨仍保留不动。这样可以**检验**Bage是否真正造成停算，不能将这项模型修改宣称为已解决收敛或原厂半导体行为。

## 已生成4份控制严格配对deck（均未实跑）

`sim/v3/d1_prot03_agefix_{published,shunt_2f}_{B_CONTROL,B_CANDIDATE}.cir` 的每份原始电路，除两行注明实验的注释与`.include sr_timing_v3_4_age_rail.lib`外字节内容均与原deck相同。每对两侧都用同一cshunt和新模型，避免把电路变更错算为保护效果。生成器 `tools/generate_prot03_bage_diagnostic.py --check`和测试将所有修改约束到这两点，并保留v3_3及历史仿真记录不变。

实际执行（优先2fF；只有目标机器安装了ADI LTspice时才可运行）：

```powershell
python tools/run_prot03_bage_diagnostic.py --variant shunt_2f
python tools/run_prot03_bage_diagnostic.py --variant shunt_2f --execute --run-id bage_2f_001 --ltspice 'D:/ADI/LTspice/LTspice.exe'
```

脚本默认dry-run，执行时直接复用成熟的RAW/LOG归档及SHA计算逻辑，控制+候选一并运行，超时或求解失败均保存可读前缀，不覆盖旧运行。`run_manifest.json`明确硬件、SOA、完整成对工作点验证均是false。结果若仍卡在Bage或转移到Bton/Btoff，不应继续扩大变更；先从保存波形/age状态/门极持续时长/求解器内部状态定位。若运行完成，仍需要和v3_3在同一个0–220µs冻结窗口比对故障前Vout、Ipri、SR正反向峰、故障点与关断时序，再从两个新v3_4 RAW按320µs完整窗口和1mV准则成对分析。

**注意**：原本四片UCC24624的行为模型本身就不包含原厂芯片全部比例门极/UVLO/待机细节；对模型数值稳定性的修复，不会自动将旧理想0.05Ω钳位转成实物有额定时间/SOA的硬保护。整机仍`NOT_FOR_FAB`。
