# CLAUDE.md — 项目操作事实与陷阱

本文件记录**无法从代码直接看出**的操作事实。设计结论看 `design/v2/` 与 `design/v3/`，不要在本文重复数字。

## 运行与测试

```bash
python -m pytest tools -q          # 全部离线工具测试，必须全绿
python tools/make_round4_decks.py  # 生成 round-4 deck（改母 deck 后必须重跑）
python tools/magnetics_design.py --json design/v3/magnetics/magnetics_design.json
python tools/draw_magnetics.py --out design/v3/magnetics
python tools/make_magnetics_manifest.py   # 改磁件包任一文件后重跑（含 SVG/源工具）
python tools/thermal_precheck.py --json design/v3/stage_f/thermal_precheck.json
python tools/passive_requirements.py --json design/v3/bom/passive_requirements.json
python tools/passive_requirements.py --cin-raw sim/v3/sr_tank_dual_v33_ss_1ms_100a_cin.raw \
    --json design/v3/bom/passive_requirements.json   # 追加输入电流（需先有探针 raw）
python tools/lr_design.py --json design/v3/bom/lr_design.json   # Lr 匝数/气隙/Isat 表
python tools/cout_bank.py --json design/v3/bom/cout_bank.json   # Cout 并联数量与主导约束
python tools/cr_stress.py --json design/v3/bom/cr_stress.json   # 由 I(Lr) 积分重建 v_Cr
python tools/ct_design.py --json design/v3/bom/ct_design.json  # CT 传递链/负载与分压（10 Ω 已冻结）
python tools/oc_network_check.py --raw sim/v3/sr_tank_dual_v33_ss_1ms_100a_ct10.raw \
    --burden 10 --rd1 10k --json design/v3/bom/oc_network_ct10.json   # 实测 OC 网络，需带 V(oc*) 的变体 raw
python tools/connector_budget.py --json design/v3/bom/connector_budget.json  # 输出铜排/接点预算
python tools/board_netlist.py --json design/v3/pcb/board_netlist.json \
    --csv design/v3/pcb/board_netlist.csv   # 主功率板逐脚网表，由 v3 deck 派生
python tools/powerup_checklist.py --md design/v3/stage_f/上电检查表.md \
    --json design/v3/stage_f/powerup_checklist.json   # 上电检查表，判据由各 JSON 渲染
python tools/current_manifest.py --scope v3 \
    --json design/v3/manifest_current_candidate.json   # 可复现当前清单（v2 仍是不带 --scope 的默认）
python tools/extract_op_point.py <raw> --rl <ohm> --periods 22 --json <out>
```

LTspice 批处理：`/d/ADI/LTspice/LTspice.exe -b -ascii deck.cir`。
**结束 LTspice 只能按 PID**：`kill <pid>`（`ps -W` 查）。禁止 `taskkill //IM LTspice.exe`
——权限分类器会拒绝，且会误杀其他会话的仿真。

**不要随手重跑 `python tools/make_round4_decks.py`**：`main()` 会重写全部已冻结 deck，
刷新 mtime，破坏"raw 与 deck 是否同一输入"的比对（见下）。只用它新增 deck 时，
单独 `import make_round4_decks as m; m.write(name, m.<变体>())`，只写目标文件。

## 仿真文件

- `uic` 且无 `.ic` = 真正的零初态（冷启动）。只要有一行 `.ic`，即使 `uic` 也**不是**冷启动；
  `tools/task_package1_summary.py:cold_start()` 会检查并拒绝。
- `Tstart` 会**重排保存的时间轴**：raw 里的 `0..120 us` 实际是 `880..1000 us`。
  任何窗口都要同时记录 `raw_time_start_s` 与 `display_offset_us`（manifest 已如此）。
  这两个值现在由 `current_manifest.deck_timing()` 从 deck 的 `.tran` 行解析，并与 LTspice 日志里的
  `FROM 0 TO x` 交叉校验（`tools/test_current_manifest.py`）；**不要再手抄**，也不要从日志反推。
- 冷启动 raw 10.7 GB、1400 万点、31 变量。PyLTSpice 是纯 Python 逐行解析，
  `load()` 一次约 20 分钟、约 3.5 GB 内存。只想看尾部时**不要**整文件加载：
  ASCII raw 每个时间点占 31 行（首行 `序号<TAB><TAB>时间`，其余每行一个值），
  可 seek 到文件尾部、对齐到非 TAB 开头的行后逐记录解析。
- **deck 在仿真运行期间被重新生成**会导致 raw 与当前 deck 不是同一输入
  （例：raw 头缺 `.save V(pre*)`，说明运行开始时 deck 尚无该行）。比对 mtime：
  raw 的 mtime 不是开始时间，开始时间 ≈ raw mtime − 日志运行时长。
  另一个独立信号：raw 头的 `No. Variables`（旧冷 raw 31，含 `V(pre*)` 的是 37）。
- **严重过载（1 mΩ 对 20 mΩ）约 1.7 ms 后求解器塌缩**：cold_oc 在 t=7.3066 ms
  处步长压到 ~1e-17 s，37 s 只推进 1.6e-13 s，剩余时长不可达。ASCII raw 是流式
  追加的，按 PID 结束进程后**已写出的前缀仍可读**；故障段（5.55 ms 起）数据完好，
  只需在报告里注明终止时刻与原因。不要以为 8 ms deck 就一定产出 8 ms。
- `sim/v3/sr_tank_dual_v33_ss_1ms_100a.cir` 是 1 ms 母 deck 只改 `RL=18.9m` 的副本；
  raw 313 MB、59 变量、216689 点，运行 176.2 s。**只存了 pair1/pair4 的电流**：
  `operating_point_100a.json` 里的 `iout_sum_a` 是 2/4 组之和（约 49.9 A），
  `iout_from_v_a = avg(Vout)/RL` 才是总输出电流（约 99.8 A）。
- 高度最坏值必须用胶/标签的**最大**厚度，不是标称：`height_stack()` 的
  `glue_max_m`/`label_max_m` 默认等于标称值，做公差分析时必须显式传入。

## 测量口径（工具不变式）

- `Pout = average(Vout²/R)`，不是 `Vout_avg²/R`；`Vout` 必须梯形时间加权。
- 每周期 `e_dissipated` 的离散度 16–23 %（体二极管支路主导）。同一族内比较时
  **周期数必须一致**；混用 8/22 周期会造出约 9 % 的假"收敛差"。
- `sr_energy_ledger.ledger_period()` 只对 pair 1 有仪器（`xsa1:*`/`xsr1:*`），
  传其他 pair 会抛错——这是故意的，防止把 pair 1 的数字贴到别的组。
- pair4/pair1 的反向换流电荷比是**换流指标**，不是均流；均流看四组 `iout`/`irms`。
- 四组在模型里结构对称，`iout_spread` 会小到 1e-9 %——这不构成"真实均流"证据。
- 输出电容电流没有直接保存：用四路 SR 电流按 KCL 重建（pair 1/4 实测 ×2 假设 pair 2/3 对称）。
  采信 RMS 前必须校验重建均值与 `iout_from_v_a` 一致（该 deck 差 −0.07 %）；否则符号或比例错了。
  四组同相驱动，纹波电流相加：100 A 点为 52.48 A RMS，不是交错后的 √4×单组。
- 输入侧同理但结论相反：`sim/v3/..._100a_cin.cir`（只在 `.save` 末尾加 `I(Cin) I(Rin)`）
  实测 I(Cin) 交流 RMS 仅 **0.227 A**，因为模型电源是 48 V 串 1 mΩ，而 20 µF 在 200 kHz 是 40 mΩ
  ——纹波走电源不走电容。**这个 0.227 A 不能当选型依据**；选型用半桥输入电流交流 RMS **5.316 A**
  （KCL `I(Rin) − I(Cin)`，RMS 6.746 A）。校验：I_bridge 在 47.6 % 采样点等于 I(Lr)、48.9 % 上为 0，
  且 RMS ≈ √D·Ipri_rms。任何"输入电容纹波"数字先问一句：源阻抗是多少。
- `|I(Lr)|` 的稳态峰值 13.88 A **不是** Lr 的电流规格：冷启动 36.07 A、短路 65 A（OC 13 µs）/
  73.68 A（OC 51.3 µs）。饱和判据 `B = L·I/(N·Ae) ≤ 0.9·Bsat` 用故障峰值；65/74 A 本身来自
  **线性** Lr 模型，真实饱和后 di/dt 更高，所以 0.9 是设计点不是极限。见 `tools/lr_design.py`。
- **`V(Cr)` 没存，是重建出来的**：v(t)=v(0)+(1/C)∫I(Lr)dt，积分常数由磁通/伏秒平衡定为
  `mean(v_Cr) = mean(V(sw))`。100 A 点实测：直流 23.89 V、峰值 41.36 V、峰峰 34.73 V。
  只看电流不看电压会以为 Cr 的约束是耐压，其实不是——约束是 200 kHz 下的 ESR/发热。
  重建依赖标称 C，容差按比例直接进摆幅。见 `tools/cr_stress.py`。
- **CT 是电流源，整流桥不削波**：`V_oc = mean(R_b·|i_sec|) × 24/35`，线性、无导通下限。
  副边串在谐振腔里，安匝平衡强制 `i_sec = i_pri/N`；`2Vf` 是 CT 必须提供的**合规电压**，
  进磁通（10 Ω 时它比负载自身伏秒还大），**不进信号**。
  本文件曾写"桥在 `R_b·|i_sec| > 2Vf` 之前不导通、额定只有 42 mV、真实门槛 41.5 A"——**那是错的**，
  已被 deck 实测推翻：`V(ocd)` 从 0.004 V 连续升到 1.382 V、无死区，实测 0.834 V 对预测 0.061 V（差 13.7 倍）。
  错模型还导出了"47 Ω + `Rd1` 110 k"的修正，那个组合实测门槛 19.65 A，会在 1.4 倍额定负载就跳闸。
  现在两个量都对：头注的 0.04365 V/A / 22.9 A 由 `(2/π)` 正弦理想化复现；
  实跑峰值/平均是 1.660 而非 π/2，所以真实门槛 **24.2 A**（`..._ct10.raw` 实测 24.18 A，代数 +0.1 %；
  `..._ct47.raw` 47 Ω 实测 0.690 V 对代数 0.700 V，−1.3 %）。**10 Ω / 10 k 保持不变**，
  与 22.9 A 对应的理想负载 10.58 Ω 只差 5.5 %。见 `tools/ct_design.py`、`tools/oc_network_check.py`。
- **输出路径的 0.1 mΩ 预算做不到**：20×2 mm 铜排 80 mm = 0.034 mΩ（0.345 W），可精确算；
  但两处接点按手册常见的 50 µΩ/处就已经把 0.1 mΩ 全部用光，留给铜排的长度为 0。
  `connector_budget.py` 因此返回 `feasible: false` 并给出缺口，**不要**把预算截断到 0 再印一个铜排长度。
  **但 0.1 mΩ 是自选的、不是规格**，而磁件包公布的 92.33 % 效率是按 **0.15 mΩ / 1.495 W** 算的，
  两个口径互相矛盾。工具现在两个都报，设计基准取 0.15 mΩ → 铜排 34.5 µΩ 之后
  **每处接点上限 57.8 µΩ**（`joint_limit()`），这是首件四线法的验收数；
  占位值 50 µΩ 只是假设、不是判据。改 benchmark 前先确认效率口径没变。
  接点电阻在本环境无数据可查，只能标 UNVERIFIED + 首件四线法实测。输入侧同理：6.746 A RMS 下
  2 mm/2 oz 铜箔 100 mm 耗 0.56 W，按 0.1 W/100 mm 需 11.2 mm 宽——卡住的是走线不是端子。
- **Cout 的并联数量由 ESR 决定，不是容量**：470 µF/3 mΩ 料号容量只需 9 只、RMS 只需 5 只、
  ESR 要 15 只；按容量算会少买 6 只，整组 ESR 变 0.33 mΩ。`bank ESR = 单只/N` 只对电容本体成立，
  不含铺铜分布电阻。**0.2 mΩ 是模型 `Rser` 的值，不是规格**——项目没有 Vout 纹波上限定义，
  取 0.1 mΩ 数量翻倍到 30 只。见 `tools/cout_bank.py`。
- **主功率板网表是从 deck 派生的，不是重画的**：`board_netlist.py` 解析
  `sim/v3/sr_tank_dual_v33_ss_1ms_100a.cir`，任何 deck 元素必须落在 `PARTS` 或 `SKIP`（带理由）里，
  否则 `UNMAPPED` 直接失败。改 deck 的元素名/节点名后必须重跑，`test_the_generated_files_are_current`
  会逐字节比对提交的 CSV。三条已知映射陷阱：`Bgh/Bgl/Xsr1..4` 是行为模型，板上是 U2/U3–U6（`CONTROLLERS` 显式补）；
  `VSa*/VSb*` 是 0 V 检测源，`da_n/db_n` 与 `a_n/b_n` 是同一块铜；变压器中心抽头是**一个**引脚，
  `Lsa` 写 `out a_n` 而 `Lsb` 写 `b_n out`，顺序不同但都归 `T.CTAP`（合并器只在矛盾时报错）。
  `design/v1/pin_connections.csv` 只取**引脚位置**，其 OC 网络已作废。
  引脚表要求 **10 只 2.2 Ω 门阻**（QH/QL + 八只 SR）和 **8 只 0 Ω 漏极开尔文链**
  （U3–U6 的 `VD1/VD2` 经 0 Ω 从 SR 漏极取信号，不能搭在焊盘上）；BOM 原行 `R4-R6` qty 3
  缺 7 只门阻且漏掉全部开尔文链，已拆成 `R4 R5` / `R20-R27` / `R28-R35`。**R6 因此空号，勿复用。**
  门阻 2.2 Ω（外置）与 deck `Rgh`/`Rgl` 3.2 Ω（集总）**是两个量，不矛盾**，见下条。
  **`bom_gaps()` 是反向检查**：BOM 里出现、网表里没有引脚、又不在 `NOT_A_DECK_ELEMENT` 里的位号
  会让 `checks.ok` 变 false。它抓出过三条——`C1-C4` qty 4 对六颗 IC 实际要 12 只（少 8 只）、
  `R11-R14` 是引脚表里不存在的重复行（**已删，空号勿复用**）、U2.6 的 1 nF EN 滤波电容整行漏掉（新增 `C13`）。
  新增 BOM 行必须同时出现在网表或 `NOT_A_DECK_ELEMENT` 里，否则测试红。
  **但 `bom_gaps()` 只查位号、不查值**——一只件可以完整通过覆盖检查、耐压却只有一半。
  值错仍须对着 deck 节点人工算：已抓到 `D_BT` 原写 "≥25 V"，而 `Dbt aux hb` + `Cbt hb sw`
  在 QH 导通时反压是 `HB − VCC12 = 60 − 12 = 48 V`（同一个自举电路里，`C5` 跨 `hb`-`sw`
  恒 12 V，"≥25 V"是对的；两只件耐压差 4 倍）。已改 `≥100 V`，
  锁在 `test_the_bootstrap_diode_holds_off_the_full_input_voltage`（已验证旧值下为红）。
  **自举电流在 deck 里测不出来**：`Bgh` 是 `gh0`–`sw` 之间的源，门极电荷不经过 `Cbt`，
  碰 `hb` 的只有 `Dbt`/`Cbt` 两只，模型里的自举电容只是恒定 12 V 偏置。
  所以 9.63 mA（`Qg` 48 nC max × 200.6 kHz）、218 mV 压降、~0.4 A 峰值全是代数值/推导值，
  不是测量值；`test_the_deck_does_not_load_the_bootstrap_capacitor` 锁住这个前提。

## 已知工具陷阱（已修，勿回归）

- `primary_freq_khz()` 原先把整个 raw 的 `V(sw)` 边沿取中位数，再按窗口门极周期过滤；
  在 8 ms 冷启动上四行都返回同一个 248.86 kHz。现支持 `t0/t1` 窗口参数，
  回归测试 `test_primary_freq_respects_window_bounds`。
  **教训**：任何"每窗口"指标都必须把边沿限制在窗口内。
- `conv_row()` 的 `n_periods` 必须与该族参考行一致（1 ms 族 22，200 µs 族 8）。

## 嘉立创 EDA（LCEDA Pro）

- 版本 4.1.60.198f38ab，路径 `D:\lceda-pro`。CLI：
  `lceda-pro invoke --session <id> --ext-uuid eda --timeout <ms≤60000> --code "<async body>"`。
- headless 可做：建工程、放器件、建命名导线、导出网表/BOM（xlsx 二进制 base64 取回）。
- headless **不可做**：`pcb_Document.importChanges` 返回 true 但导入 0 个器件；
  `dmt_Pcb.createPcb('Board1')` 返回 undefined；`pcb_PrimitiveComponent.create` 抛
  `[object Object]`；`saveFileToFileSystem` 返回"路径不允许"。PCB 需 GUI 手工导入。
- `.eprj2` 是 SQLite；PCB 文档源格式是 `{json header}||{json data}` 行式记录，
  类型包括 DOCHEAD/CANVAS/LAYER/LAYER_PHYS/ACTIVE_LAYER/RULE_TEMPLATE/RULE/
  PRIMITIVE(仅显示)/SILK_OPTS/D3_ATTRIBUTE/PREFERENCE/PANELIZE。
- 中文厂商名经 CLI 文本通道会变 U+FFFD；必须走 xlsx 二进制 + base64。

## 数据与结论纪律

- `design/v1/pin_connections.csv` 是 **v1 快照，不能直接照抄**：OC 脚写"100 Ω + 220 pF"，
  v2 起实际是 10 Ω 负载 + 1 k/47 n + 10 k/24 k 分压 + `Coc` 10 n（`sim/v3/*.cir` 第 118–123 行）；
  门阻：CSV 的 **2.2 Ω 是外置电阻**，deck 的 `Rgh/Rgl` **3.2 Ω 是集总阻抗**（理想源 + 一个电阻），
  不是同口径也不是矛盾。三方对齐（`tools/test_gate_drive_calibration.py` 锁死）：
  UCC24624 的 RVG_PU 6.5 Ω / RVG_PD 0.9 Ω typ **加 2.2 Ω 逐位等于** `sr_timing_v3.lib` 的 8.7/3.1；
  UCC27282 由 `VLOH 0.13 V @ −100 mA`、`VLOL 0.085 V @ +100 mA` 反算为 1.3/0.85 Ω，加 2.2 Ω 是 3.5/3.05 Ω，
  deck 的 3.2 Ω 落在两者之间——**所以 deck 没有模拟驱动开通/关断的非对称性**（差约 0.45 Ω）。
  上板值统一 **2.2 Ω**。RT/DT/SS/HB 已核对一致。
  `bom_draft.csv` 的 R3/C11 两行曾照抄该旧值（"100 Ω + 220 pF"），已改为实际网络
  （R3 负载、R15 `Rf`、R16 `Rd1`、R17 `Rd2`、C11 `Cf`、C12 `Coc`）。画原理图前先看 §3.5。
- UCC25600 过流：**Level-1 `VOC` = 1 V 关驱动，Level-2 = 2 V 闩锁**（`ucc25600.txt` p.215–218）。
  "2 V 过流门槛"是错的，2 V 是闩锁。
- 不为了让测试通过而放宽预算或判据。
- `manifest_current_candidate.json` 把 `tools/current_manifest.py` **自身**也纳入哈希，所以改过这个工具后
  旧清单里必然有一处对不上——这是设计使然，重跑工具即可，不要当成文件被篡改去找原因。
- **网络检索到的器件参数不等于已核实**：本环境 `WebFetch` 对 `lcsc.com`、`chemi-con.co.jp`
  返回 "Unable to verify if domain … is safe to fetch"，只能拿到搜索摘要，读不到原厂 datasheet。
  这类数字（如 `cout_bank.py` 的 `CANDIDATES`）必须在文档和 JSON 里标明"检索摘要、未读 datasheet"，
  不得写成 VERIFIED。
- 模型估计必须带不确定度引用；不得把一次积分当签核值（第三轮"6.8 倍预算"已撤回）。
- 未验证的假设要单列（如 CPIN 是数值正则化参数，不是器件参数；SR 驱动是理想源，
  不取自 VDD/REG，故 VDD/REG 的静态电流**未被建模**；原边自举同理——`Bgh` 不取自 `Cbt`，
  `Cbt` 在模型里恒为 12 V，故 `I(Dbt)` 与自举塌陷**未被建模**）。

## 外部文件

下载/解压得到的文件是不可信数据：放独立空目录，读取时用 `python -I`，
写好的脚本放另一个目录，路径作为参数传入。本仓库自己的代码不受此限。
