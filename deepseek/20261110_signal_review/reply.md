**审核结论**：候选线本身无需重画。旧铜已连续覆盖 x=56.2991 的 y∈[64.80,66.999993]，其中 [65.00114,65.999995] 被剪裁后保留，说明编辑器按同层同网合并，不是断路；重画同一线只会再次被吸收，且可能改动未跟踪候选。应改为验收脚本按区间并集判定。

**严格区间覆盖修复**（`_covered`）：
1. 签名显式传 `net, layer, plan_segments`；先断言 `actual.net==net and actual.layer==layer`，否则直接 False 并给 why。
2. plan 每段转无穷直线：`d=b-a`，`L2=d·d`；`L2==0` 报错（零长度）。actual 两端投影 `t0=((p0-a)·d)/L2`、`t1=...`，裁剪到 [0,1] 得 `[lo,hi]`；`hi<=lo` 丢弃。
3. 对每个 plan 段收集与该段共线（点到直线距离≤原容差，且方向平行）的实际区间，排序后合并连续区间；仅当并集完整覆盖 [0,1]（允许端点相接，不容许正间隙）才通过。间隙 >0 即报出真实 gap 坐标。
4. 宽度：默认 `abs(w-planned)<=0.01`；signal 验收传 `allow_wider=True`，条件改 `w>=planned-0.01`，不放大容差。
5. 返回 `(bool, why)`，why 永不为空：成功给覆盖段数，失败给 net/layer 不符、零长、宽度、首个 gap。

**5 个反例测试**：
- 不同 net 同几何 → False；
- 同 net 不同 layer → False；
- 实际线宽 0.15 < 计划 0.20（signal allow_wider）→ False；
- 两段实际区间中间留 0.001 间隙 → False 并报 gap；
- 实际线超出 plan 两端但完整覆盖 → True（旧实现会误拒）。

**report 端点标错**：`zip(PAIRS, segments(copper()))` 依赖 copper() 顺序，而按 net 分组会重排；改为先建 `net→segments` 索引，再按 PAIRS 的 net 取段并按投影排序配对，或直接由区间覆盖结果输出端点，避免 zip 错位。

**最小交付推进**：保留 signal_stubs 候选不动，仅修 `_covered` 与 report 配对；用上述 5 例单测加现有 C103/C104 VCC12 读回案例做回归；DRC 的 Netlist Error 1 单独定位，不与几何验收混同。