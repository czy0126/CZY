# TRAP_INDEX — 一条一条的硬规则（全索引）

> **本文件不自动加载。** 每条规则的全文在「家」列指出的文件中。
> **★ = 进 `CLAUDE.md` 热区**，由 `python tools/agent_docs.py --write` 从本表**逐字节投影**；
> 手改 `CLAUDE.md` 的热区必被 `python tools/agent_docs.py --check` 判红。要改热区 ⇒ **改本表再投影**。
>
> - 加新行：在本表加一行（默认不加 ★）→ `python tools/agent_docs.py --write`。
> - 找不到的规则：`grep -rn "<关键词>" docs/agent/`。
> - 「家」列里的 `文件 §小节` 是**锚点短语**，直接 `grep -n "<小节>" docs/agent/<文件>` 能定位。
> - 旧文档/代码注释里的「CLAUDE.md §小节名」按 `CLAUDE.md` 〇节的表解析到这些文件。

| ★ | 硬规则 | 触发（何时读全文） | 家 |
|---|---|---|---|
| ★ | 仿真一律在远端 `winsrv` 上跑；本地仓库是真值，远端只执行 | 起任何仿真 | ENVIRONMENT.md §远端仿真主机 |
| ★ | VPN 开着时用 `ssh -b <本机 WLAN IP>`、`scp -o BindAddress=<同 IP>`；IP 现查 `ipconfig` | 连不上 winsrv | ENVIRONMENT.md §远端仿真主机 |
| ★ | 远端 LTspice 用 `D:\ADI\LTspice-26.0.2\LTspice.exe`；`D:\ADI\LTspice\LTspice.exe` 是 26.1.1，不得用 | 起远端仿真 | ENVIRONMENT.md §远端仿真主机 |
| ★ | 并行必须由 `schtasks` 起（sshd 的 Job Object 上限 3，第 4 个退 0 且不写盘） | 并行仿真 | ENVIRONMENT.md §远端仿真主机 |
|  | 经 `schtasks` 跑的树放 `C:\work\...`（令牌受限）；不要为此放宽暂存树 ACL | 建并行暂存 | ENVIRONMENT.md §远端仿真主机 |
|  | 暂存用 Python `tarfile` 解包，不用远端 `tar.exe`（GBK 下中文路径乱码） | 上传代码 | ENVIRONMENT.md §远端仿真主机 |
| ★ | deck 的 `../../models` 只在 `sim/` 下一层解析 ⇒ 并行 lane 必须是 `v3` 的兄弟目录 | 放新 deck / lane | ENVIRONMENT.md §远端仿真主机 |
|  | 判活看进程 CPU 时间是否增长与 raw 是否出现；正常运行时 ASCII raw 结束前是 0 字节 | 判仿真死活 | ENVIRONMENT.md §远端仿真主机 |
|  | 跨主机数值不逐位相同（线程数不同）；一次比较的两侧必须都在同一主机产生 | 比两次运行 | ENVIRONMENT.md §远端仿真主机 |
| ★ | LTspice 批处理：`LTspice.exe -b -ascii deck.cir`；结束**只按 PID**，禁止 `taskkill //IM LTspice.exe` | 起/停仿真 | COMMANDS.md §LTspice 批处理 |
| ★ | `ps -W` 里的进程名是 `LTspice`（没有 `.exe`）；名字 grep 会误判"早退出了" | 判仿真死活 | COMMANDS.md §LTspice 批处理 |
|  | 本机 PowerShell 执行策略禁止运行 `.ps1`；批量入口用 `tools/run_d1_50v_matched_cases.py` | 跑批 | COMMANDS.md §LTspice 批处理 |
| ★ | GBK 控制台打不出 `µ`（U+00B5）与 `⇒`；用 ASCII `uohm` 或希腊 `μΩ` | 写 `print` | COMMANDS.md §GBK 控制台 |
|  | 不要随手重跑 `make_round4_decks.py`（会刷新全部已冻结 deck 的 mtime） | 加一个 deck | COMMANDS.md §不要随手重跑 |
|  | `tools/run_d1_50v_matched_cases.py` 只判 320 µs 完整性，三面旗恒 false | 跑 PROT-03 | COMMANDS.md §LTspice 批处理 |
|  | `asprintf` 型候选 deck 的 `.save` 整块从母 deck 复制，不是尾部追加 | 改候选 deck | COMMANDS.md §运行与测试 |
| ★ | `uic` 且无 `.ic` = 真冷启动；只要有一行 `.ic` 就不是 | 写冷启动 deck | SIMULATION.md §仿真文件 |
|  | `.ic V(ss)=4` 不是 5 V 稳态（0.5 mV/µs，1 ms 只到 4.485 V） | 改 hotfault deck | SIMULATION.md §仿真文件 |
| ★ | 48 V hotfault 才是完整证据（跑满 320 µs）；50 V 基座在 296.929 µs 塌缩，引用必须写"前缀" | 引用故障数 | SIMULATION.md §仿真文件 |
| ★ | trip 后 SR 门极锁存是**模型边界**，不是"已安全关断"，也不是"SR 直通" | 写 SR 故障结论 | SIMULATION.md §仿真文件 |
|  | cshunt 阶梯非单调（1/2/5 fF = 254.980/264.515/235.890 µs）；它只挪塌缩时刻 | 加 cshunt | SIMULATION.md §仿真文件 |
|  | 严重过载约 1.7 ms 后求解器塌缩；8 ms deck 不一定产出 8 ms，前缀仍可读 | 跑 cold_oc | SIMULATION.md §仿真文件 |
|  | cshunt 对冷启动过载无效，而且让塌缩更早（5.6141 vs 7.5714 ms） | 跑 cold_oc 变体 | SIMULATION.md §仿真文件 |
| ★ | 10 A SR_ON 默认设置塌缩在 1.3551 ms；只有 `gmin=1e-10` 能跑满，那是**声明过的求解器偏差**（5 A 对照差 0.5233 %），不得当默认模型证据 | 引用 10 A 数 | SIMULATION.md §仿真文件 |
| ★ | `Tstart` 重排保存时间轴；窗口必须记 `raw_time_start_s` 与 `display_offset_us`，由 `deck_timing()` 解析 | 报任何窗口 | SIMULATION.md §仿真文件 |
| ★ | deck 在仿真运行期间被重新生成 ⇒ raw 与 deck 不是同一输入；比 mtime / `No. Variables` | 比对 raw | SIMULATION.md §仿真文件 |
|  | 冷启动 raw 10.7 GB；只看尾部时 seek 到记录边界（31 行/点），不要整文件 load | 读冷启动 raw | SIMULATION.md §仿真文件 |
| ★ | `.save` 是多行续行块；只在第一行尾部追加会丢后面 18 个探针 | 给 deck 加探针 | SIMULATION.md §仿真文件 |
|  | 48 V/120 A 候选账本要 `--no-step-check`（仓库唯一 2 ns raw 属 100 A deck） | 跑候选账本 | SIMULATION.md §仿真文件 |
|  | 1 ms 母 deck 只存 pair1/pair4 的电流；`iout_sum_a` 是 2/4 组之和，`iout_from_v_a` 才是总输出 | 提输出电流 | SIMULATION.md §仿真文件 |
|  | hotfault 两个 deck 的 `.tran` / PWL 行是唯一真值，窗口从文本解析，不要手抄 | 改故障 deck | SIMULATION.md §仿真文件 |
|  | 50 V 的保护候选只能建在 `cshunt=1e-15` 变体上；`--base-deck` 默认是候选声明的父 deck | 跑 PROT-02 候选 | SIMULATION.md §仿真文件 |
|  | 2 fF 软轨对候选完全惰性（0–220 µs 逐位相同），`post_window_scan` 不测峰值 | 引用软轨配对 | SIMULATION.md §仿真文件 |
|  | PROT-03 的两条判据在 50 V 上不能同时成立；不许二选一当通过 | 报 50 V 配对 | SIMULATION.md §仿真文件 |
|  | 登记表的 `deck_sha256` 是 LF 规范化文本的散列，不是 LTspice 打开的 CRLF 字节 | 填运行登记表 | SIMULATION.md §仿真文件 |
|  | B 源的锁存清除项是 `+V(node)*(1n/TAU)`；重启 deck 的 `.tran` 步长须 ≤10 ns | 写重启 deck | SIMULATION.md §仿真文件 |
|  | 逐器件保护表不能混窗口（`post_trip` vs `saved_window`），差值不要相减 | 读 SOA 表 | SIMULATION.md §仿真文件 |
| ★ | `Pout = average(Vout²/R)`，不是 `Vout_avg²/R`；`Vout` 必须梯形时间加权 | 算效率 | MEASUREMENT.md §测量口径 |
| ★ | 每周期 `e_dissipated` 离散 16–23 %；同族比较**周期数必须一致** | 比损耗 | MEASUREMENT.md §测量口径 |
| ★ | 单个损耗项可引用精度约 **2.3 W**（四段步长摆幅）；效率只能引到 ±1 个百分点 | 引用 SR / 损耗项 | MEASUREMENT.md §测量口径 |
| ★ | 闭合残差 +0.33 W 是"测到了缺口"，不是收敛值；0.5 ns 段是 +0.5233 W | 引用闭合残差 | MEASUREMENT.md §测量口径 |
| ★ | `closure_status` 保持 `NOT_CLOSED`；闭合站住不等于 SR 损耗清单收敛 | 报闭合 | MEASUREMENT.md §测量口径 |
| ★ | 储能必须用三绕组耦合形式；旧式 `4×½Lp·Ip²` 夸大 2600 倍 | 算磁储能 | MEASUREMENT.md §测量口径 |
|  | 电容储能必须由电荷函数在端点求值；`∫v·i` 每通道每周期残留 −290 pJ | 算储能 | MEASUREMENT.md §测量口径 |
|  | `charge_energy_j()` 用闭式原函数；不要退回 Simpson（每点约 1 ms） | 改储能 | MEASUREMENT.md §测量口径 |
| ★ | 储能端点是**周期平均**；单点与周期平均两个读数都要报 | 报闭合 | MEASUREMENT.md §测量口径 |
|  | 对齐窗口 133 个门极周期 = 662.9 µs，由 `phase_alignment()` 算，不要手抄 | 选窗口 | MEASUREMENT.md §测量口径 |
|  | 对齐窗口上端口/损耗项各摆 0.6–1.3 W；`sem_w` 只含周期随机散布，不含步长 | 引用"能分辨 0.2 W" | MEASUREMENT.md §测量口径 |
|  | 50 V/120 A 的 0.49 W 缺口不是漏了耗散元件；不要把缺口当"还有物理没建模" | 解释缺口 | MEASUREMENT.md §测量口径 |
|  | `sr_loss_audit` 的 aligned 家族是从用例名派生的**四列**（5/2/1/0.5 ns），不许写死三列 | 改审计工具 | MEASUREMENT.md §测量口径 |
|  | SR 的步长不稳定在**体二极管正向导通**，不在沟道 | 解释 SR 不收敛 | MEASUREMENT.md §测量口径 |
|  | `loss_main` 与 `drv` 不在同一边界；闭合多算 `Rg + Rgs + Cpin` | 改闭合记录 | MEASUREMENT.md §测量口径 |
|  | `V(Cr)` 没存，是重建的；约束是 200 kHz 下的 ESR/发热，不是耐压 | 报 Cr | MEASUREMENT.md §测量口径 |
|  | CT 是电流源、整流桥不削波；真实过流门槛 24.2 A（不是 22.9 A） | 改 OC 网络 | MEASUREMENT.md §测量口径 |
|  | CT 负载功耗按 `mean(V²)/R`，且要看对的电流点（48 V/120 A = 125.7 mW） | 选 R3 | MEASUREMENT.md §测量口径 |
|  | 冷启动 R3 先推导后直接测量（−1.2 % / +0.12 %）；封装由启动能量主导 | 选 R3 | MEASUREMENT.md §测量口径 |
|  | `V(ovl1)` 不是过流脚；真正的过流节点是 `V(oc)` | 查过流 | MEASUREMENT.md §测量口径 |
| ★ | 选型点一律是 **120 A 过载点**（Cin/Cout/Cr/Lr）；读标量键前先看 `sizing_points` | 引用任何选型数 | MEASUREMENT.md §测量口径 |
|  | Cout 并联数量由 **ESR** 决定（15 只），不是容量 | 选 Cout | MEASUREMENT.md §测量口径 |
|  | Cout 三个点不是同一种测量：100 A 重建、两条 120 A 实测；RMS 必须梯形加权 | 报 Cout RMS | MEASUREMENT.md §测量口径 |
|  | `mean_check_pct` 属于**重建分支**，即使主值已经是实测 | 读 `stress_block` | MEASUREMENT.md §测量口径 |
|  | Cr 是带 **574.1–620.0 nF**；卡住它的是 Lr 窗口，不是时钟 | 选 Cr | MEASUREMENT.md §测量口径 |
|  | Cr 容差规则 `标称 ≤ 620/(1+t)`；±10 % 件无法配平 | 选 Cr | MEASUREMENT.md §测量口径 |
|  | Cin 选型点 **6.36 A**（120 A）；电容值不是约束；383 A 是伪影 | 选 Cin | MEASUREMENT.md §测量口径 |
| ★ | 实测峰值必须与它跑的那个 L 配对（`paired_flux()`），不能用别的电感换 B | 算磁密 | MEASUREMENT.md §测量口径 |
| ★ | 变压器磁通按副边实测电压积分；半周期的正负摆幅**不能相加** | 报磁通 | MEASUREMENT.md §测量口径 |
|  | 故障窗磁通只报"故障前摆幅 + 跳闸后伏秒上界"；跳闸后的积分不是磁通 | 报故障磁通 | MEASUREMENT.md §测量口径 |
|  | `I(SH)`/`I(SL)` 的千安级尖峰是集总电容充电，不是器件电流；RMS 必须时间加权 | 引用原边 SOA | MEASUREMENT.md §测量口径 |
|  | 端口乘积 `V·I` 含引线电感 `L·di/dt`，不是管芯耗散（351 W vs 190.7 W） | 算结温 | MEASUREMENT.md §测量口径 |
|  | SR 主要在第三象限；厂家 SOA 图只有第一象限 ⇒ 第三象限"图外、不评分" | 写 SOA 判据 | MEASUREMENT.md §测量口径 |
|  | Zth 叠加以窗口起点为参考；`peak_rise_k` 是相对故障前的温升 | 报温升 | MEASUREMENT.md §测量口径 |
|  | `V(xsa1:di)` 的实例名是 `xsa1`/`xsb1`（`xs`+侧+`1`） | 读管芯电压 | MEASUREMENT.md §测量口径 |
|  | 100 A 能量账只在同一窗口内成立；16 周期把损耗算高 0.386 W | 引用 11.117 W | MEASUREMENT.md §测量口径 |
|  | 16 周期窗口没有 0.2 W 的分辨率；闭合残差要引 133 周期值 | 报闭合 | MEASUREMENT.md §测量口径 |
|  | 步长检验里移动的大项是储能与端口，不是损耗清单 | 读 `step_check` | MEASUREMENT.md §测量口径 |
|  | 候选 deck 的 `Cout`/`LR_TOTAL` 与工具常量不同，储能必须从 deck 读 | 算候选储能 | MEASUREMENT.md §测量口径 |
|  | `window_terms()` 必须转发 `vin`/`rl`；否则复算会凭空造出 22.66 W | 复算候选闭合 | MEASUREMENT.md §测量口径 |
|  | 纹波不能用 10 µs 窗口；22 周期值是 49.73 mVpp（目标 50 mV，余量 0.27） | 报纹波 | MEASUREMENT.md §测量口径 |
|  | 94.47 %（电气端口）/ 93.06 %（加磁芯）/ 92.33 %（加路径与偏置）是三个口径 | 引用效率 | MEASUREMENT.md §测量口径 |
| ★ | `checks` 是报告不变量（只有它的 `ok` 是门），`results` 是物理结果 | 写任何 JSON | MEASUREMENT.md §测量口径 |
|  | x4 对称性只在 pair1/pair4 测过；`iout_spread` 1e-9 % 不是均流证据 | 报均流 | MEASUREMENT.md §测量口径 |
|  | 输出电容电流是四路 SR 按 KCL 重建的；四组同相，纹波相加 | 报 Cout 电流 | MEASUREMENT.md §测量口径 |
|  | 输入电容纹波 0.227 A 由源阻抗（1 mΩ）决定，不能当选型依据 | 报 Cin 纹波 | MEASUREMENT.md §测量口径 |
|  | `I(Lr)` 的稳态峰值不是 Lr 规格；饱和判据用故障峰值 | 选 Lr | MEASUREMENT.md §测量口径 |
|  | `sr_energy_ledger.ledger_period()` 只对 pair 1 有仪器，传别组会抛错 | 用能量账 | MEASUREMENT.md §测量口径 |
| ★ | `primary_freq_khz()` 必须把边沿限制在窗口内 | 改频率指标 | TRAPS.md §已知工具陷阱 |
|  | `conv_row()` 的 `n_periods` 必须与该族参考行一致（1 ms 族 22 / 200 µs 族 8） | 改收敛表 | TRAPS.md §已知工具陷阱 |
|  | hotfault 覆盖容差是一个积分步长（`.tran` 的 Tmaxstep），不是固定 1 ps | 改覆盖判据 | TRAPS.md §已知工具陷阱 |
|  | `ascii_raw_window.find_offset` 按 `n_variables + 2` 扫；换变量数更多的 deck 先想这条 | 读新 raw | TRAPS.md §已知工具陷阱 |
| ★ | 任何"每周期"的量，**构造**也必须限制在窗口内，不能只限制积分 | 改账本 | TRAPS.md §已知工具陷阱 |
| ★ | 只能用 `--path` 打开 LCEDA 工程，且必须是**绝对路径**；绝不调 `openProject(uuid)`（之后 save 恒 false） | LCEDA 任何操作 | EDA.md §嘉立创 EDA |
| ★ | `save()` 防抖约 20 s；判"写进去了"只能看被打开那个路径的 size/mtime | LCEDA 保存 | EDA.md §嘉立创 EDA |
|  | `otherProperty.Footprint` 会毒化整个文档（每次 save 都 false） | 改封装 | EDA.md §嘉立创 EDA |
| ★ | 保存与导出互斥：先放件→等写盘→内存注入封装 uuid→导出；注入后不能再 save；注入/构建实验**只开副本**——`save()` 写回的是被打开的那个文件 | 导出网表 | EDA.md §嘉立创 EDA |
|  | `getSvgFile` 在 83 位号时超 60 s；`main_board.svg` 是旧的，不要当当前图证据 | 引用主板 SVG | EDA.md §嘉立创 EDA |
|  | 原生 PCB 靠图元 API 搭（`pcb_PrimitiveComponent.create({libraryUuid,uuid},…)` + `pcb_PrimitivePad.modify(id,{net})`）；`importChanges` 导入 0 件；单位 mil、Y 向上，polygon 源 Y 向下要取负 | 建原生 PCB | EDA.md §原生 PCB 的 headless 构建 |
|  | 自由焊盘用 `pcb_PrimitivePad.create(...)` 17 个位置参数建（带网、不挂器件）；组件→焊盘只有 `getAllPinsByPrimitiveId` 一条链，焊盘上**没有** component 字段 | 放临时端子 | EDA.md §原生 PCB 的 headless 构建 |
|  | `getState_Polygon()` 是扁平数组（`'L'` 夹在数字里）⇒ 过滤数字后按 `nums[0::2]`/`[1::2]` 配对，按 3 步长解析读出垃圾 | 读折线/板框 | EDA.md §原生 PCB 的 headless 构建 |
|  | `doc api --class-name` 用 `PCB_PrimitivePad` 这种大写类名，invoke 正文里才写 `eda.pcb_PrimitivePad`；`--timeout` 只收 1…60000 整数 | 查 PCB API | EDA.md §原生 PCB 的 headless 构建 |
|  | LCEDA `eda` body 在 `open` 后约 20 s 内发出、或带未保存图元 `close --destroy`，都会**永久卡死** render（`return 1;` 仍 1 ms、真实 body 一律 59750 ms、新 session 同样卡）⇒ 只能 `lceda-pro stop` + 重开；协议固定为 open → 等 20 s → `return 1;` 探活 → 真实 body，body 内先 `save()` | LCEDA invoke 超时 | EDA.md §EDA 桥接的卡死与恢复 |
|  | 会话里没打开 PCB 文档就调 `pcb_Layer` / `pcb_Drc`，抛 `EXECUTION_ERROR … 指定的参数信息在对应的会话中没有找到`（不是卡死）⇒ 先 `dmt_EditorControl.openDocument(board.pcb.uuid)` 再等 1 s | PCB API 报参数找不到 | EDA.md §EDA 桥接的卡死与恢复 |
|  | 过孔尺寸/间距要现读板子自带的规则（`pcb_Drc.getCurrentRuleConfiguration()`）：G1 是内径 ≥0.3、外径 ≥0.5 mm、Track/Via 间距 0.152；按"嘉立创能力"记忆写 0.2 钻孔会出 13 条 `Via Size` | 定过孔/净距 | EDA.md §EDA 桥接的卡死与恢复 |
|  | 磁件符号的引脚号是逻辑端子名；`physical_pad` 全 null，不编厂商焊盘号 | 磁件封装 | EDA.md §嘉立创 EDA |
|  | 供应商回件审核只对当时那两份字节成立；合同重生成后必须重跑审核 | 审核回件 | EDA.md §嘉立创 EDA |
|  | R8 ECO 分两相：phase 1 注入**绝不保存**，phase 2 clean session 凭 attestation 应用 | 跑 R8 ECO | EDA.md §装配排除 ECO |
|  | 导出会把被排除件重新编号（R8 → R6）；对回原件的键是导出的 uid | 对回原件 | EDA.md §装配排除 ECO |
|  | `sch_PrimitiveComponent.modify` 整表替换 `otherProperty`；只传部分键会清空厂家属性 | 改原生取值 | EDA.md §原生主板的取值 ECO |
|  | 写完必须用**新句柄**读回（旧句柄是快照）；校验用发出去的表当期望值 | 改原生取值 | EDA.md §原生主板的取值 ECO |
|  | GBK 命令行带不了 `Ω`；invoke 正文必须纯 ASCII | 跑 value ECO | EDA.md §原生主板的取值 ECO |
|  | `native_inventory_raw.json` 是整个 CLI 信封，不是里面那个 `value` | 读原生清册 | EDA.md §原生主板的取值 ECO |
| ★ | kicad-cli 路径不许写进工具（Issue #11）；按 `KICAD_CLI` → PATH → `%LOCALAPPDATA%` 找 | 用 kicad-cli | EDA.md §KiCad 10.0 CLI |
| ★ | `.kicad_pro` 缺失会让 ERC/DRC 说假话（工程库不可见、courtyard 静默失效） | 跑 ERC/DRC | EDA.md §KiCad 10.0 CLI |
|  | kicad-cli 只绘板文件 `(layers)` 表里声明过的层，没声明的静默丢弃 | 出 gerber | EDA.md §KiCad 10.0 CLI |
| ★ | DRC JSON 有三个顶层数组：`violations` / `unconnected_items` / `schematic_parity` | 读 DRC | EDA.md §KiCad 10.0 CLI |
|  | 跑 DRC 先 `unlink` 报告；退出码 0 不代表没违规；子进程必须 `encoding="utf-8"` | 跑 DRC | EDA.md §KiCad 10.0 CLI |
|  | D0 的"十路全关"是逐路二极管取**最大值**，不是求和 | 改 D0 | EDA.md §KiCad 10.0 CLI |
|  | D0 的两个过流门限不在同一节点（24/35 与 1.0），不能共用一个 V/A | 改 D0 门限 | EDA.md §KiCad 10.0 CLI |
|  | 4xxx 门单元的输出脚不是每组最后一个号（4081/4071/4093 = 3/4/10/11） | 写 4xxx 原理图 | EDA.md §KiCad 10.0 CLI |
|  | D0 的 POR 折进故障锁存（`flt = fault_b or por`） | 改 D0 逻辑 | EDA.md §KiCad 10.0 CLI |
|  | D0 的 `D9 BZX84C3V0` 已删；门限 0.9419 V，对 1.3 V 只剩 0.058 V 余量 | 改 D0 门限 | EDA.md §KiCad 10.0 CLI |
|  | D0 响应预算的第一个坑是重复计数；许可轨释放由八只 4.7k 决定（删了就不能关断） | 算响应预算 | EDA.md §KiCad 10.0 CLI |
|  | UCC27524A 的 EN→输出 23 ns max、关断**拉低不是三态**；CD4081B 没有 max ⇒ 地板不是最坏值 | 算响应预算 | EDA.md §KiCad 10.0 CLI |
|  | 封装名必须真的存在于 vendored 库；**ERC 不看封装** | 写任何原理图 | EDA.md §KiCad 10.0 CLI |
|  | 默认 `sch erc` 不含 exclusions；"0 条"必须加 `--severity-all` | 判 ERC 干净 | EDA.md §KiCad 10.0 CLI |
|  | ERC 报告缺席/过期/指向别的原理图，都不能读成"0 条" | 判 ERC 干净 | EDA.md §KiCad 10.0 CLI |
|  | SR 板主关断是 REG 撬棒（12.11 µs），不是切 VDD、也不是门极钳位 | SR 板任何结论 | BOARDS.md §单对真实 SR |
|  | Q41 的 RDS 取慢的那一列 0.048 Ω；`q41_selection.qualified` 恒 false | SR 板 | BOARDS.md §单对真实 SR |
|  | R44 的能量/峰值在 4.748 Ω 下（122.7 µJ / 25.23 W），不是 1.5 Ω 占位的 14.8 W | SR 板 | BOARDS.md §单对真实 SR |
|  | 故障输入默认是**不撬棒**（fail-open）；状态输出 3.0 V 是下拉端分压 | SR 板接口 | BOARDS.md §单对真实 SR |
| ★ | **MPN 只在仓库有数据手册时写，其余一律 `TO_SELECT`** | 任何 BOM | BOARDS.md §单对真实 SR |
|  | 门极钳位默认 DNP；`VG1` 网络恰好 4 个成员，不许并入第二个驱动 | SR 板 | BOARDS.md §单对真实 SR |
|  | `VSS` 与 `PGND` 是两个网络，只经 R1 → SR_SRC → Rsh1 相连 | SR 板 | BOARDS.md §单对真实 SR |
|  | SR 支路 15.8 µs > 原边 1.29 µs；两支路并联**不许相加** | SR 板延时 | BOARDS.md §单对真实 SR |
|  | 布线：焊盘不是包围盒，按 shape 算到**铜**的距离 | 改路由器 | BOARDS.md §布局 pass 3 |
|  | rip-up 的**选择**顺序 ≠ 重布顺序；按主通路顺序重布 | 改路由器 | BOARDS.md §布局 pass 3 |
|  | 同网铜可以共用、同网钻孔不行（`_via_keepout` 不接受本网豁免） | 改路由器 | BOARDS.md §布局 pass 3 |
|  | 净空按格心盖 ⇒ 加 `PITCH_MM/2`，且只对走线和过孔加，不加焊盘 | 改路由器 | BOARDS.md §布局 pass 3 |
|  | `GAP_MM = 1.25` 是量出来的（0.75 mm 停在 117/119） | 调路由器 | BOARDS.md §布局 pass 3 |
|  | courtyard 可能关于原点不对称，必须整框平移 | 摆件 | BOARDS.md §布局 pass 3 |
|  | kicad-cli 把任何被旋转的封装报 `lib_footprint_mismatch` ⇒ 摆放全部 0° | 摆件 | BOARDS.md §布局 pass 3 |
|  | 热焊盘中心本来就不在铜上；判连通用重新填充后的 DRC | 铺铜 | BOARDS.md §布局 pass 3 |
|  | `island_removal_mode` 只能写在 `(fill ...)` 里；写到 zone 层 KiCad 拒绝加载 | 铺铜 | BOARDS.md §布局 pass 3 |
|  | `--save-board` 只对 `pcb/sr_fault_validation/` 里的临时副本用 | 测填充 | BOARDS.md §布局 pass 3 |
|  | `--exclude-dnp` 读封装的 `(attr ... dnp)`，不是件表里的标记 | 出坐标文件 | BOARDS.md §布局 pass 3 |
|  | 装配审核是拿板子和 `BOM.csv` 对，不是拿板子和自己的件表对 | 装配审核 | BOARDS.md §布局 pass 3 |
|  | 模块布线 `escape_mm = 0.0` 是实测选的；安装孔位号必须隐藏 | fast-OC 布线 | BOARDS.md §模块布线板 |
|  | `dcx.pretty` 必须先写再生成板文件 | 生成任何板 | BOARDS.md §模块布线板 |
|  | SOT-23 上放两脚稳压管 = 钳位开路（BZX84 阴极在 3 号脚） | fast-OC / SR | BOARDS.md §模块布线板 |
|  | 生成器的 `check()` 有两条**互为反向**的守卫，缺一条会被净空表骗过 | 改板生成器 | BOARDS.md §布局 pass 3 |
|  | 制造目录/剩余依赖是**视图不是审核**；表写死，不做设计判断 | 引用制造视图 | BOARDS.md §实验板制造目录 |
| ★ | 没有数据的字段写 `UNKNOWN`，不许填一个看起来合理的值 | 写询价单 | MAGNETICS_BOM.md §磁件询价单 |
| ★ | 高度限值从 `d1_staged_target_policy.json` 读，不许写死 | 写询价单 | MAGNETICS_BOM.md §磁件询价单 |
|  | ELP38 的气隙按它自己的 AL 重算（3 匝 2.1651 mm 出界 ⇒ Lr 按 2 匝报价） | Lr 套件 | MAGNETICS_BOM.md §磁件询价单 |
|  | 窗口净高 = 半芯总高 − I 片厚（数据手册不给单列尺寸） | 磁件叠层 | MAGNETICS_BOM.md §磁件询价单 |
| ★ | 变压器的磁通不许用 `L·I/(N·Ae)`（那是 Lr 的电感筛查） | 写 T 单 | MAGNETICS_BOM.md §磁件询价单 |
|  | 询价单与 `vendor_terminal_request.json` 的 24 个逻辑端子必须逐项相同 | 改磁件接口 | MAGNETICS_BOM.md §磁件询价单 |
|  | 24+2 包的 Lr 端距由板上原生封装决定（9.0 mm），不是概念里的 40 mm | 改 G1 端子包 | MAGNETICS_BOM.md §磁件询价单 |
|  | TBD 矩形是磁芯本体/A6 沉槽，不是器件包络；磁件端子出芯是设计意图 | 改 G1 磁件焊盘 | MAGNETICS_BOM.md §磁件询价单 |
|  | 气隙窗口必须按电感排序（L_min ↔ 最宽气隙），返回 `(narrow, wide)` | 写加工输入页 | MAGNETICS_BOM.md §磁件加工输入页 |
|  | 物理端子一律写「待商家提供」，不编焊盘号 | 写加工输入页 | MAGNETICS_BOM.md §磁件加工输入页 |
|  | 磁密只能写「仿真波形积分」或解析值，不写实测 | 写加工输入页 | MAGNETICS_BOM.md §磁件加工输入页 |
|  | CT 磁芯还没选 ⇒ `frozen: False` 必须在页头写明 | 写 CT 页 | MAGNETICS_BOM.md §磁件加工输入页 |
|  | 61 = 44 金网表 + 17 外围；`UNGOVERNED` 会让 `checks` 变红 | 加占位 | MAGNETICS_BOM.md §61 占位 |
|  | 12 行没有需求出处 ⇒ `next_action` 写"先定义需求再选型" | 占位清单 | MAGNETICS_BOM.md §61 占位 |
|  | `MAPPED` 只是逻辑端子名，不等于物理引脚已核实 | 磁件占位 | MAGNETICS_BOM.md §61 占位 |
|  | `energy_mj` 已经是毫焦，不要再乘 1e3 | 读占位清单 | MAGNETICS_BOM.md §61 占位 |
| ★ | A5 的三个数不是同一个量（262/278/150）；引用必须带版本，相减没有意义 | 报 A5 计数 | MAIN_BOARD.md §A5 带网摆放 |
|  | 老鼠线 = Σ(每网焊盘数 − 1)；新冒出来的网只贡献 k−1 条 | 预测摆放增量 | MAIN_BOARD.md §A5 带网摆放 |
| ★ | 焊盘名就是身份（Lr 用 `1`/`2`，不是原理图的 `N1`/`N2`） | 摆件 | MAIN_BOARD.md §A5 带网摆放 |
|  | 输出电容位号是 `Cout1`–`Cout15`；原理图把它们画成一只集总 `Cout` | 摆输出电容 | MAIN_BOARD.md §A5 带网摆放 |
|  | 只剩 3 条单焊盘网；`SINGLE_PAD_REASONS` 双向核对 | 改摆放 | MAIN_BOARD.md §A5 带网摆放 |
|  | 铜排中心由 `_sr_row_centre()` 算，不是字面量 | 移 SR 组 | MAIN_BOARD.md §A5 带网摆放 |
|  | `parts()` 不许 import 交叉模块（本文件会被当 `__main__` 再执行一次） | 改 A5 | MAIN_BOARD.md §A5 带网摆放 |
|  | vendored 封装的焊盘可能没有 `(uuid …)`；插入的缩进必须深一层 | 注入网 | MAIN_BOARD.md §A5 带网摆放 |
|  | `extract_pads` 不应用旋转 ⇒ A5 全部 0°，电阻用坐标贴到 FET 焊盘下方 | 改 A5 摆放 | MAIN_BOARD.md §A5 带网摆放 |
|  | `ROUTED_DRAFT_CONNECTIVITY_ONLY_AMPACITY_NOT_MET` 不是话术：2 oz 最差 142.284 mΩ vs 0.15 基准 | 引用布线结论 | MAIN_BOARD.md §A5 已经布出来的铜 |
|  | 全局 0.8 mm 走线出不了 UCC24624 引脚列 ⇒ 只有输出网 0.8 mm，其余 0.25 mm | 改布线宽度 | MAIN_BOARD.md §A5 已经布出来的铜 |
|  | 量布线电阻前必须先做"焊盘收缩"（同号焊盘并一个节点） | 量电阻 | MAIN_BOARD.md §A5 已经布出来的铜 |
| ★ | 铺满两层也不行：2 oz 串联 1.8204 mΩ = 0.15 基准的 12.1 倍 ⇒ 铜排才是输出路径 | 引用铺铜结论 | MAIN_BOARD.md §A5 铺满两层 |
| ★ | VOUT 带必须是**墙**（`barrier=True`）；加价只是偏好，保不住走廊 | 改铺铜/布线 | MAIN_BOARD.md §A5 铺满两层 |
| ★ | `island_removal_mode 0` 只问"碰到本网焊盘"，一条走线也算；焊盘数 0 不是孤岛 | 判铺铜存活 | MAIN_BOARD.md §A5 铺满两层 |
|  | 汇电流求和只算留在铜里的边（补零一圈 + `linked` 过滤） | 改求解器 | MAIN_BOARD.md §A5 铺满两层 |
|  | 铺满实验的 `solder_mask_bridge` 是这个实验的代价，不是缺陷 | 读铺铜 DRC | MAIN_BOARD.md §A5 铺满两层 |
|  | numpy 类型出不了 `json.dumps`（`np.bool_` / `np.float64`） | 写报告 | MAIN_BOARD.md §A5 铺满两层 |
|  | `--check` 会重铺重解（约 3 min）；只比板子字节不够，报告里的 `pours` 也要重算 | 维护 A5 | MAIN_BOARD.md §A5 铺满两层 |
| ★ | 沉槽只是把压块买回来（A = C = 9.94 mm）；TIM/冷板/紧固件无数据 ⇒ `null` | 改 A6 | MAIN_BOARD.md §A6 机械剖面 |
| ★ | 100 A 输出路径要用**方块数**看，不是微欧（0.15 mΩ 只有 0.46 个方块） | 改输出路径 | MAIN_BOARD.md §A6 机械剖面 |
|  | SR 板、fast-OC 板的 `--check` 缺 kicad-cli 时行为不同（前者跳过、后者 SystemExit） | 跑 `--check` | BOARDS.md §布局 pass 3 |
|  | `manufacturing_index.py` 的 `fab: None` 分支理由写"no gerber…" | 加板 | BOARDS.md §实验板制造目录 |
|  | `counts` 里三个字段是"名字的列表"不是计数，要 `len(...)` | 改视图工具 | BOARDS.md §实验板制造目录 |
|  | 磁件询价单放 `hardware/dcx_main/rfq/`，不放 `design/v3/magnetics/` | 加询价单 | MAGNETICS_BOM.md §磁件询价单 |
|  | `staged_magnetics_16mm_rfq.csv` 的 3.65 mm 与设计包 3.51 mm 是两个口径，不许互改 | 改高度表 | MAGNETICS_BOM.md §磁件询价单 |
|  | 文本文件的 SHA256 必须经 `text_identity.sha256_file()`（CRLF→LF）；裸 `read_bytes()` 哈希会让 LF 检出的 CI 红 | 给文本记哈希 | TRAPS.md §已知工具陷阱 |
|  | `Path.read_text(newline=)` 只在 Python 3.13+ 有；CI 固定 3.12 ⇒ 用 `agent_docs.read_text_exact()` | 读保留换行的文本 | TRAPS.md §已知工具陷阱 |
|  | G1 评审图必须写明画的是哪个板文件；提交的 SVG 必须等于提交的 `g1_pads.json` 现渲染 | 出 G1 评审图 | EDA.md §原生 PCB 的 headless 构建 |
|  | G1 建板脚本原先只在 `tmp_g1_probe/`（未跟踪）⇒ 摆放与 slice 正文现在由 `build_g1_board.py` + `g1_placement.json` 生成，`--check` 对读回比对 | 重建 G1 板 | EDA.md §原生 PCB 的 headless 构建 |
