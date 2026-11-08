# 偏置与REG耦合敏感性验证

`bias_budget.json`包含REG驱动预算缺口和低Qg对照候选；`report.json`包含6组实际仿真、源文件哈希及条件能量界。

生成：`python tools/bias_hold_validation.py`。LTspice `-b`逐一运行cir后记录：`python tools/bias_hold_validation.py --record`。
回归：`python -m pytest tools/test_bias_hold_validation.py -q`。

无SR门极开关波形，无原厂控制器/非线性MOS模型。完整审核在项目根目录 `docs/2026-11-08_REG驱动预算与耦合验证审核.md`。
