# ARM 对抗扫描与双路互锁复核

日期 2026-10-31。对应审核步骤 2 的第三项：“验证 ARM、BON/BOFF、双路互锁”。
状态：**SIMULATION EVIDENCE**。行为时序模型，不是硬件验证，也不支持任何硅片级结论。

BON/BOFF 的对抗角已在 `verify_param_bounds.cir` 中闭合（见 `design/baseline/BASELINE.md` §4.2）。
本文补齐剩下的两项：ARM 阈值角，以及双路互锁/仲裁的逐台架构结果。

---

## 1 为什么要单独扫 ARM

ARM 是 VD 比较阈值（datasheet typ 1.5 V），模型里有**两处**独立使用它：

| 位置 | 代码 | 作用 |
|---|---|---|
| 通道内重装锁存 | `models/sr_timing_v3.lib:84` `Barm arm S I=if(V(Q,S)>.5,V(arm,S)*(1n/TAU),if(V(D,S)>ARM,...))` | 关断消隐的起始锚点 |
| PRE 资格 | `models/sr_timing_v3.lib:113` `Bpl pl S V=...if(max(V(D1,S),V(D2,S))>ARM,1,0)` | 上电前置条件 |

在此之前只有 `C14`/`C15` 两个**固定 ARM=1.5 V** 的分支，阈值本身从未被动过。阈值一旦偏，
消隐窗口的起点整段平移——这正是需要“可解释的时序”而不是“看起来对”的地方。

## 2 台架

`sim/v2/verify_arm_bounds.cir/log`（`595a4ffd58e102bc` / `57c4647651742026`）直接复用
`verify_offblank_delayed_arm.cir` 的慢斜坡刺激，只把固定的 1.5 V 换成参数并在
`.step param ARM list 1.0 1.5 2.0 2.5` 上扫。`.step param TD list 5.35u 5.50u 5.70u 5.80u`
给出 4×4 = 16 档，`.tran 0 12u 0 1n`。

漏源斜坡在 4.80–5.30 µs 之间由 −0.6 V 升到 4.0 V，即 **9.2 V/µs**，所以 ARM 穿越时刻
必须满足 `t(ARM) = 4.80 µs + (ARM+0.6)/9.2 Vµs⁻¹`：

| ARM (V) | 预期穿越 (µs) |
|--:|--:|
| 1.0 | 4.974 |
| 1.5 | 5.028 |
| 2.0 | 5.083 |
| 2.5 | 5.137 |

四个穿越点都晚于 Q 的关断沿（4.889 µs），所以每一档都必须走“VD 比较器为锚点”的分支；
若某档跑到了“栅极关断为锚点”的分支，`off_t065 − arm_t` 就不再是常数，会被立即发现。

## 3 结果

### 3.1 锚点与阈值 1:1 跟随

| ARM (V) | `arm_t` (µs) | Δ 实测 | Δ 预测 | `off_t065 − arm_t` (ns) | 关断后阻塞 (ns) |
|--:|--:|--:|--:|--:|--:|
| 1.0 | 4.974071809 | −54.000 ns | −54.35 ns | 650.72 | 735.34 |
| 1.5 | 5.028071809 | 0 | 0 | 650.72 | 789.34 |
| 2.0 | 5.082528298 | +54.456 ns | +54.35 ns | 650.71 | 843.79 |
| 2.5 | 5.137071809 | +109.000 ns | +108.70 ns | 650.72 | 898.34 |

- 穿越时刻与解析预测的最大偏差 **0.35 ns**（ARM=1.0 档），来自 1 ns 最大步长；
- `off_t065 − arm_t` 在全部 16 档都是 **650.71–650.72 ns**，即 BOFF（650 ns）+ ≤0.72 ns 步长；
- 也就是说阈值只**平移**窗口，不**变形**窗口。没有一档出现“锚点改走栅极关断”的分支。

### 3.2 重新导通的时刻链

`q2rise`（状态机 Q 节点穿越 0.5）与栅极到达 2 V 的 `g1r2` 可拆成三段：

| 量 | 实测 | 解释 |
|---|---|---|
| `q2rise − 锚点` | 155.46–155.70 ns | TON 155 ns + Q 节点一阶上升（TAU=1 ns）穿越 0.5 的 +0.7 ns |
| `g1r2 − q2rise` | 11.82–11.85 ns | 栅极节点由 0 升到 2 V 的时间（6.7 nF 替身下的驱动限流） |
| 合计 | 167.3–167.5 ns | 与 `verify_t3_*` 台架里 167.26 ns 的 `g1_dly` 一致 |

16 档中 4 档（TD 5.70/5.80 µs × ARM 1.0/1.5 V）出现**第二段锚点**：消隐在重触发之前就已到期，
状态机于是等 `V(d1)` 下穿 ONTH（−0.265 V）才拿到合法请求，`q2rise` 相应变成
`TD + 9.27 ns + 155.7 ns`。9.27 ns 正是 4.0→−0.265 V 在 10 ns 内的插值位置。
这是设计行为（消隐到期后，合法的重触发必须被接受），不是计时错误。

### 3.3 没有一档在 VDS 为高时开栅

`vd_at_g1`（栅极穿 2 V 瞬间的 V(d1)）在**全部 16 档 = −0.600 V**。
这是本次扫描唯一真正的安全量：阈值无论偏低还是偏高，栅极都没有在漏源仍承受电压时导通。

### 3.4 阻塞窗口随 ARM 单调增，且不短于 BOFF

`block_after_qfall` = `off_t065 − qfall` = 735 / 789 / 844 / 898 ns（ARM 1.0→2.5）。
比 BOFF 长，是因为本波形的 ARM 穿越晚于栅极关断；结构上不可能比 BOFF 短，原因是
`Barm` 在 `V(Q)>0.5` 期间按 TAU=1 ns 衰减复位（`models/sr_timing_v3.lib:84`），
**阈值不可能在栅极导通时把锚点提前**。低 ARM 只会让消隐变长，不会变短。

### 3.5 PRE 资格不受影响

`ok_min`（4–6 µs 窗口内 `V(xsr:ok)` 的最小值）在 16 档全部 **= 1**。
四档 ARM 都低于 PRE 窗口的上沿 4.1 V，前置条件均正常置位。

## 4 ARM 的边界（本模型不设防的部分）

1. **ARM ≥ 4 V 时 PRE 永不置位**。`Bpl` 只在 `V(REG)<4.1` 期间比较 VD 与 ARM，
   因此 ARM 一旦高于 4.1 V，`ok` 恒 0、全桥永不导通。这是参数输入错误而非电路行为，
   datasheet 范围内（±0.15 V 量级）不会触及，但台架不报错——记在这里以免将来误读成“不导通”。
2. **模型没有数值噪声**。本次扫描只动了阈值，没有叠加 VDS 上的开关噪声；
   ARM 偏低时的误触发风险无法用本台架证明，只能说明“阈值平移不破坏时序”。
3. **只扫了慢斜坡**。快斜坡（ARM 穿越早于栅极关断）由 `verify_offblank_boundary.cir` 覆盖，
   两类的锚点规则不同（前者 VD 比较器，后者栅极关断），本台架不重复。

## 5 双路互锁与仲裁

五个既有台架，每个都跑两遍：原样（`sr_timing_v3.lib`，栅极带 6.7 nF 替身）与
`*_g0.cir`（`sr_timing_v3_1.lib` + `CGATE=0 CPIN=100p`，与主头条同口径）。

| 台架 | 检查什么 | 版本 | 结果 |
|---|---|---|---|
| `verify_t3_interlock` | 落败通道在胜者 on-blank 内的脉冲：拒绝而非排队 | v3 | 胜者 10.8905 V；败者窗口内最大 0 V；伪脉冲计数 0；overlap 0 |
| | | g0 | 胜者 10.8905 V；败者 0 V；伪脉冲 0；overlap 0；落败脉冲的首次导通推迟到 6.16507 µs（下一个合法事件） |
| `verify_t3_simultaneous` | 三次**精确同时**请求 | v3 | CH1 在 4.17653 / 7.17653 / 10.17653 µs 三次全胜；`gate2_max` 0；`a2_max` 0；overlap 0 |
| | | g0 | 三次全胜，时刻 4.16490 / 7.16490 / 10.16490 µs；CH2 连仲裁锁存都没置位 |
| `verify_t3_skew` | 50 ns / 5 ns 偏移，两个方向 | v3 | E1→CH2、E2→CH1、E3→CH2、E4→CH1，先到者恒胜；落败栅极 5.4e-40 V（数值零）；overlap 0 |
| | | g0 | 同样四个胜者，落败栅极严格 0；overlap 0 |
| `verify_tie_exact` | 两个独立源在**同一求解时刻**穿越 −265 mV | v3 | `tc1−tc2` = 0（`ddiff_hi=ddiff_lo=0`）；CH1 胜，栅极延迟 167.26 ns；CH2 从不置位 |
| | | g0 | `tc1−tc2` = 0；栅极延迟 155.63 ns；CH2 从不置位 |
| `verify_interlock_queue` | 被挡脉冲是否留下残余 on-delay 计时器 | v3 | 6.5 µs 前 0 V（250 ns 被挡脉冲 + 60 ns 亚 TON 脉冲都未触发）；300 ns 控制脉冲在 7.17671 µs 正常导通 |
| | | g0 | 6.5 µs 前 0 V；控制脉冲 7.16507 µs；`q2max_early` = 0 |

十六个 ARM 工况、十个单档台架日志，**overlap 全为 0**，且：

- **精确 tie 恒判 CH1**：`BSET` 的 `SECOND=1`（CH2）在 CH1 有同等有效原始请求时被挡
  （`models/sr_timing_v3.lib:59`），三次同时请求无一例外；
- **skew 恒判先到者**，50 ns 与 5 ns 两个尺度都不误判；
- **被否决不入队**：`verify_interlock_queue` 里若残余计时器存在，60 ns 的亚 TON 脉冲会在
  6.01 µs 立刻导通；实测 6.5 µs 前始终 0 V，而 300 ns 的控制脉冲按正常 TON 延迟导通。
- `pre_final` = 0.99999、`viol_final` = 0，说明 PRE 资格与上电顺序违规锁存都没有被仲裁路径污染。

### 5.1 两版模型的差异只落在栅沿

五个台架里唯一变化的量是 `V(g)=2` 的到达时刻，且**在每个台架里都是同一个数**：

| 量 | v3（6.7 nF） | g0（CGATE=0） | Δ |
|---|--:|--:|--:|
| `g1_dly`（tie 台架） | 167.26 ns | 155.63 ns | **−11.63 ns** |
| 同时请求的首次导通 | 4.17653 µs | 4.16490 µs | −11.63 ns |
| 控制脉冲 | 7.17671 µs | 7.16507 µs | −11.64 ns |

这 11.6 ns 就是 6.7 nF 替身电容让“栅极穿过 2 V”变慢的量，和
`design/v2/gate_load_calibration.md` §2.2 的 90.3↔214.3 ns 上升时间是同一件事的不同截面。
仲裁、消隐、队列逻辑一字未改，因此五台结果在 g0 下逐条保持。

## 6 复现

```bash
cd sim/v2
/d/ADI/LTspice/LTspice.exe -b verify_arm_bounds.cir
for f in verify_t3_interlock verify_t3_simultaneous verify_t3_skew verify_tie_exact verify_interlock_queue; do
  /d/ADI/LTspice/LTspice.exe -b $f.cir
  /d/ADI/LTspice/LTspice.exe -b ${f}_g0.cir
done
cd ../..
python tools/meas_table.py sim/v2/verify_arm_bounds.log
python tools/meas_table.py sim/v2/verify_tie_exact_g0.log
python -m pytest tools/test_meas_table.py -q
```

`tools/meas_table.py`（`ef71d7c0f7978d16`）本轮修掉了一个静默解析缺陷：`.meas ... WHEN V(x)=2 AT t`
与 `FIND ... AT=t` 的平面行里，“=”后面是**比较电平或采样时刻**而不是结果，旧实现会把
−0.265 或 5.9 µs 当成结果。现在按四种行型分别取值，并由 `tools/test_meas_table.py`（`4502b8f2c5366cbb`，5 个用例）锁住。
扫描类日志走 `Measurement:` 块，不受影响——已发布的八档/12 档表格取自该格式，未含此缺陷。

## 7 仍未覆盖

1. **ARM × BON/BOFF 的二维角**：两者各自单独扫过，未做联合；`BON` 典型值只剩 9.9 ns 裕量的结论
   是在 ARM=1.5 V 下得到的，联合角可能进一步压缩它。
2. **PRE 与仲裁的交叉**：本组台架都在 PRE 已置位后开始，没有测试“运行中 PRE 清除”的路径。
3. **两路交换的对称性**：`SECOND` 固定把 CH2 设为败者，没有跑 `SECOND` 交换的镜像台架。
4. **`sr_timing_v3_checks_{interlock,simultaneous,skew}.cir` 与 `verify_t3_*` 逐字节相同**
   （`diff -q` 无输出），属历史重复；保留是为了不让既有引用失效，新工作只引用 `verify_t3_*`。
