# Rev B候选偏置切断

2026-11-08新增：`hold_validation/`已有偏置/REG耦合敏感性验证及驱动预算。必须先完成低Qg对照或真实SR电荷核算，见 [最新审核](../../docs/2026-11-08_REG驱动预算与耦合验证审核.md)。

可编辑原理图、BOM、ERC和10个简化功率路径仿真。无PCB，无硬件验证，未批准制造。

完整审核及下一轮任务见 [Rev B审核](../../docs/2026-11-07_RevB整改审核与后续路线.md)。
生成器：`python tools/bias_cut_revision_b.py`。
用LTspice运行所有cir后：`python tools/bias_cut_revision_b.py --record`。

本目录是旧 `bias_cut_eco` 功率段的替代候选；旧文件是历史失败证据，不要将两版BOM合并。
保留Q41/R44快速REG钳位。

## 后续三轮的交付（数字只在各自的JSON里）

| 任务 | 文件 | 结论 |
|---|---|---|
| T1 偏置接口冻结 | [`bias_budget.json`](bias_budget.json) | 每只UCC24624独立支路；四组不得共用一个22Ω。22Ω在最坏角是否满足原厂REG稳压，只差ES1D在约39mA下的实测Vf |
| T2 REG保持能量与回灌 | [`reg_hold_energy.json`](reg_hold_energy.json) | 有限电容有界；持续外部注入**未闭合**，且不能靠加大R57解决 |
| T3 器件与控制时序 | [`timing/timing_report.json`](timing/timing_report.json) | R59脉冲/稳态按原厂曲线PASS；控制链含数据手册最大传播延迟与真实Q50 `Ciss`；共8个deck |

T3 改变了两个先前的读数，引用时不能再抄旧值：

- Rev B 的偏置切断比 Rev A 实测的 13.36 µs **更慢**（更小的 R50 被大 17 倍的 `Ciss` 抵掉），
  T2 的输入延迟能量只是量级不变，具体数字以 `timing_report.json` 的 `cut_delay` 为准。
- 5 V 掉电后切断本身约 23 µs 落地，但本地 11.1 µF 使 VDD_SR 在毫秒级仍高于 REG 关断下限；
  **"5 V 掉电后 SR 门极已关断"必须由 5 V 域的钳位保证，不能由偏置切断保证。**

三份报告都是 `measured=false`、`hardware_qualified=false`；`deepseek/` 下的审阅意见不是测量。
