# CLAUDE.md — 项目索引（薄）

> `D:\workshop\design_48v-2v` 的**操作事实与陷阱的索引**。设计结论看 `design/v2/`、`design/v3/`，不在这里重复数字。
> 详细内容已拆进 `docs/agent/`，**按需 Read**；本文件每个会话都进上下文，所以只留索引、纪律与热区。

## 〇、写契约 —— 加任何东西之前先读

本文件每会话都进上下文 ⇒ **加一行之前必须回答：它替换了什么、或者它的家在哪。**

- **一条事实一个家**：事实写进 `docs/agent/<主题>.md`，本文件只留指针。
- **重复的数字是债**：同一个数只在一个工具里生成、一个文件里解释。本文件不抄设计数字。
- **热区是投影，不是手写**：§三 由 `python tools/agent_docs.py --write` 从
  [`docs/agent/TRAP_INDEX.md`](docs/agent/TRAP_INDEX.md) 的 ★ 行**逐字节投影**；
  `--check` 断言逐字节相等 ⇒ **手改 §三 必被红**。要改热区 ⇒ 改索引表再投影。
- **不设字节预算**：增长必须能点名"替换了哪一条"；点名不出来就先别加。
- 加完跑：`python tools/agent_docs.py --write && python -m pytest tools -q`。

### 家的分布

| 主题 | 文件 | 里面有什么 |
|---|---|---|
| 命令与运行入口 | [`docs/agent/COMMANDS.md`](docs/agent/COMMANDS.md) | 全部离线工具、生成器、`--check`、LTspice 批处理、GBK 控制台 |
| 远端仿真主机 | [`docs/agent/ENVIRONMENT.md`](docs/agent/ENVIRONMENT.md) | winsrv、`ssh -b`、`schtasks`、tarfile 暂存、lane 深度、吞吐 |
| deck 与 raw | [`docs/agent/SIMULATION.md`](docs/agent/SIMULATION.md) | 冷启动、hotfault、塌缩、`Tstart`、探针、各候选 deck |
| 测量口径 | [`docs/agent/MEASUREMENT.md`](docs/agent/MEASUREMENT.md) | 能量账、储能、步长、选型点、磁通、SOA、CT、损耗 |
| 工具陷阱 | [`docs/agent/TRAPS.md`](docs/agent/TRAPS.md) | 已修勿回归的五条 |
| EDA（LCEDA / KiCad） | [`docs/agent/EDA.md`](docs/agent/EDA.md) | headless 边界、R8/取值 ECO、kicad-cli、D0 板 |
| 实验板与制造视图 | [`docs/agent/BOARDS.md`](docs/agent/BOARDS.md) | SR 验证板、fast-OC、路由器、铺铜、制造目录 |
| 磁件与占位 | [`docs/agent/MAGNETICS_BOM.md`](docs/agent/MAGNETICS_BOM.md) | 询价单、加工输入页、61 占位清单 |
| A5 主板 | [`docs/agent/MAIN_BOARD.md`](docs/agent/MAIN_BOARD.md) | 带网摆放、布线草稿、铺满研究、A6 剖面 |
| **硬规则逐条索引** | [`docs/agent/TRAP_INDEX.md`](docs/agent/TRAP_INDEX.md) | 一条一行的全表；★ 的才是 §三 热区 |

**旧文字里的「CLAUDE.md §小节名」按这张表解析**（工具、JSON、已发布 Markdown 里嵌的那些字符串**不用改**）：

| 旧小节名 | 现在在 |
|---|---|
| 运行与测试 / LTspice 批处理 / GBK 控制台 | `COMMANDS.md` |
| 远端仿真主机（winsrv） | `ENVIRONMENT.md` |
| 仿真文件 | `SIMULATION.md` |
| 测量口径（工具不变式） | `MEASUREMENT.md` |
| 已知工具陷阱（已修，勿回归） | `TRAPS.md` |
| 嘉立创 EDA / 装配排除 ECO / 原生取值 ECO / KiCad 10.0 CLI / D0 铜 | `EDA.md` |
| 单对真实 SR 关断验证板 / 布局 pass 3 / TLV3501 / 实验板制造目录 | `BOARDS.md` |
| 磁件询价单 / 磁件加工输入页 / 61 占位责任清单 | `MAGNETICS_BOM.md` |
| A5 带网摆放 / A5 已布出来的铜 / A5 铺满两层 / A6 机械剖面 | `MAIN_BOARD.md` |
| 数据与结论纪律 / 外部文件 | 本文件 §四 / §五 |

## 一、运行时环境（只放"会踩到"的）

| 事实 | 全文 |
|---|---|
| **仿真一律在远端 `winsrv` 上跑**（2026-11-04 用户指令）；本地仓库是真值，远端只执行 | ENVIRONMENT.md §远端仿真主机 |
| VPN 开着时 `ssh winsrv` 连不上 ⇒ 用 `ssh -b <本机 WLAN IP>`、`scp -o BindAddress=<同 IP>`；IP 是 DHCP，用前现查 `ipconfig` | 同上 |
| 远端 LTspice 用 `D:\ADI\LTspice-26.0.2\LTspice.exe`；同机的 `D:\ADI\LTspice\LTspice.exe` 是 26.1.1，**不得用** | 同上 |
| 并行必须由 `schtasks` 起（sshd 的 Job Object 上限 3，第 4 个退 0 且什么都不写）；经 schtasks 的树放 `C:\work\...` | 同上 |
| 暂存用 Python `tarfile` 解包，不用远端 `tar.exe`（GBK 下中文路径乱码） | 同上 |
| deck 的 `../../models` 只在 `sim/` 下一层解析 ⇒ 并行 lane 必须是 `v3` 的**兄弟目录** | 同上 |
| 判活看进程 CPU 时间是否增长；正常运行时 ASCII raw 结束前一直是 **0 字节** | 同上 |
| 跨主机数值不逐位相同（线程数不同）⇒ 一次比较的两侧必须都在同一主机产生 | 同上 |
| LTspice 批处理 `LTspice.exe -b -ascii deck.cir`；**结束只能按 PID**，禁止 `taskkill //IM LTspice.exe` | COMMANDS.md §LTspice 批处理 |
| `ps -W` 里的进程名是 **`LTspice`（没有 `.exe`）**，`grep LTspice.exe` 会返回空 ⇒ 看起来像"早就退出了" | 同上 |
| 本机 PowerShell 执行策略禁止运行 `.ps1`；批量入口用 `tools/run_d1_50v_matched_cases.py`（逐行移植） | 同上 |
| **GBK 控制台打不出 `µ`（U+00B5）与 `⇒`**：`print("µΩ")` 直接 `UnicodeEncodeError`，而它炸在最后一行、前面的数字都印出来了，看起来像跑完了。用 ASCII `uohm` 或希腊 `μΩ` | COMMANDS.md §GBK 控制台 |

## 二、最常用的命令

```bash
python -m pytest tools -q                      # 全部离线测试，必须全绿
python tools/ci_check.py                       # pytest + 重生成 v3 manifest 并逐项比对
python tools/ci_check.py --skip-tests          # 只查生成文件是否过期（含各视图）
python tools/agent_docs.py --write             # 从 TRAP_INDEX 投影 §三 热区（改索引后必跑）
python tools/agent_docs.py --check             # 热区是否逐字节等于投影（CI/提交前）
```

其余全部入口（每个工具一行、含前置条件与耗时）见 [`docs/agent/COMMANDS.md`](docs/agent/COMMANDS.md)。
三个最容易踩的入口：

```bash
python tools/make_round4_decks.py              # 会重写全部已冻结 deck 的 mtime —— 不要随手跑
python tools/main_board_power_copper.py --check  # 重布 + 重铺重解，约 3 min，ci_check 里最慢
python tools/main_board_mechanical.py --check    # A5 摆放 1:1 + DRC，需要 KiCad 10.0
```

## 三、热区（从 TRAP_INDEX 投影，不要手改）

<!-- HOT_TABLE:BEGIN -->

| 硬规则 | 触发（何时读全文） | 全文在 |
|---|---|---|
| 仿真一律在远端 `winsrv` 上跑；本地仓库是真值，远端只执行 | 起任何仿真 | [ENVIRONMENT.md](docs/agent/ENVIRONMENT.md) §远端仿真主机 |
| VPN 开着时用 `ssh -b <本机 WLAN IP>`、`scp -o BindAddress=<同 IP>`；IP 现查 `ipconfig` | 连不上 winsrv | [ENVIRONMENT.md](docs/agent/ENVIRONMENT.md) §远端仿真主机 |
| 远端 LTspice 用 `D:\ADI\LTspice-26.0.2\LTspice.exe`；`D:\ADI\LTspice\LTspice.exe` 是 26.1.1，不得用 | 起远端仿真 | [ENVIRONMENT.md](docs/agent/ENVIRONMENT.md) §远端仿真主机 |
| 并行必须由 `schtasks` 起（sshd 的 Job Object 上限 3，第 4 个退 0 且不写盘） | 并行仿真 | [ENVIRONMENT.md](docs/agent/ENVIRONMENT.md) §远端仿真主机 |
| deck 的 `../../models` 只在 `sim/` 下一层解析 ⇒ 并行 lane 必须是 `v3` 的兄弟目录 | 放新 deck / lane | [ENVIRONMENT.md](docs/agent/ENVIRONMENT.md) §远端仿真主机 |
| LTspice 批处理：`LTspice.exe -b -ascii deck.cir`；结束**只按 PID**，禁止 `taskkill //IM LTspice.exe` | 起/停仿真 | [COMMANDS.md](docs/agent/COMMANDS.md) §LTspice 批处理 |
| `ps -W` 里的进程名是 `LTspice`（没有 `.exe`）；名字 grep 会误判"早退出了" | 判仿真死活 | [COMMANDS.md](docs/agent/COMMANDS.md) §LTspice 批处理 |
| GBK 控制台打不出 `µ`（U+00B5）与 `⇒`；用 ASCII `uohm` 或希腊 `μΩ` | 写 `print` | [COMMANDS.md](docs/agent/COMMANDS.md) §GBK 控制台 |
| `uic` 且无 `.ic` = 真冷启动；只要有一行 `.ic` 就不是 | 写冷启动 deck | [SIMULATION.md](docs/agent/SIMULATION.md) §仿真文件 |
| 48 V hotfault 才是完整证据（跑满 320 µs）；50 V 基座在 296.929 µs 塌缩，引用必须写"前缀" | 引用故障数 | [SIMULATION.md](docs/agent/SIMULATION.md) §仿真文件 |
| trip 后 SR 门极锁存是**模型边界**，不是"已安全关断"，也不是"SR 直通" | 写 SR 故障结论 | [SIMULATION.md](docs/agent/SIMULATION.md) §仿真文件 |
| 10 A SR_ON 默认设置塌缩在 1.3551 ms；只有 `gmin=1e-10` 能跑满，那是**声明过的求解器偏差**（5 A 对照差 0.5233 %），不得当默认模型证据 | 引用 10 A 数 | [SIMULATION.md](docs/agent/SIMULATION.md) §仿真文件 |
| `Tstart` 重排保存时间轴；窗口必须记 `raw_time_start_s` 与 `display_offset_us`，由 `deck_timing()` 解析 | 报任何窗口 | [SIMULATION.md](docs/agent/SIMULATION.md) §仿真文件 |
| deck 在仿真运行期间被重新生成 ⇒ raw 与 deck 不是同一输入；比 mtime / `No. Variables` | 比对 raw | [SIMULATION.md](docs/agent/SIMULATION.md) §仿真文件 |
| `.save` 是多行续行块；只在第一行尾部追加会丢后面 18 个探针 | 给 deck 加探针 | [SIMULATION.md](docs/agent/SIMULATION.md) §仿真文件 |
| `Pout = average(Vout²/R)`，不是 `Vout_avg²/R`；`Vout` 必须梯形时间加权 | 算效率 | [MEASUREMENT.md](docs/agent/MEASUREMENT.md) §测量口径 |
| 每周期 `e_dissipated` 离散 16–23 %；同族比较**周期数必须一致** | 比损耗 | [MEASUREMENT.md](docs/agent/MEASUREMENT.md) §测量口径 |
| 单个损耗项可引用精度约 **2.3 W**（四段步长摆幅）；效率只能引到 ±1 个百分点 | 引用 SR / 损耗项 | [MEASUREMENT.md](docs/agent/MEASUREMENT.md) §测量口径 |
| 闭合残差 +0.33 W 是"测到了缺口"，不是收敛值；0.5 ns 段是 +0.5233 W | 引用闭合残差 | [MEASUREMENT.md](docs/agent/MEASUREMENT.md) §测量口径 |
| `closure_status` 保持 `NOT_CLOSED`；闭合站住不等于 SR 损耗清单收敛 | 报闭合 | [MEASUREMENT.md](docs/agent/MEASUREMENT.md) §测量口径 |
| 储能必须用三绕组耦合形式；旧式 `4×½Lp·Ip²` 夸大 2600 倍 | 算磁储能 | [MEASUREMENT.md](docs/agent/MEASUREMENT.md) §测量口径 |
| 储能端点是**周期平均**；单点与周期平均两个读数都要报 | 报闭合 | [MEASUREMENT.md](docs/agent/MEASUREMENT.md) §测量口径 |
| 选型点一律是 **120 A 过载点**（Cin/Cout/Cr/Lr）；读标量键前先看 `sizing_points` | 引用任何选型数 | [MEASUREMENT.md](docs/agent/MEASUREMENT.md) §测量口径 |
| 实测峰值必须与它跑的那个 L 配对（`paired_flux()`），不能用别的电感换 B | 算磁密 | [MEASUREMENT.md](docs/agent/MEASUREMENT.md) §测量口径 |
| 变压器磁通按副边实测电压积分；半周期的正负摆幅**不能相加** | 报磁通 | [MEASUREMENT.md](docs/agent/MEASUREMENT.md) §测量口径 |
| `checks` 是报告不变量（只有它的 `ok` 是门），`results` 是物理结果 | 写任何 JSON | [MEASUREMENT.md](docs/agent/MEASUREMENT.md) §测量口径 |
| `primary_freq_khz()` 必须把边沿限制在窗口内 | 改频率指标 | [TRAPS.md](docs/agent/TRAPS.md) §已知工具陷阱 |
| 任何"每周期"的量，**构造**也必须限制在窗口内，不能只限制积分 | 改账本 | [TRAPS.md](docs/agent/TRAPS.md) §已知工具陷阱 |
| 只能用 `--path` 打开 LCEDA 工程，且必须是**绝对路径**；绝不调 `openProject(uuid)`（之后 save 恒 false） | LCEDA 任何操作 | [EDA.md](docs/agent/EDA.md) §嘉立创 EDA |
| `save()` 防抖约 20 s；判"写进去了"只能看被打开那个路径的 size/mtime | LCEDA 保存 | [EDA.md](docs/agent/EDA.md) §嘉立创 EDA |
| 保存与导出互斥：先放件→等写盘→内存注入封装 uuid→导出；注入后不能再 save；注入/构建实验**只开副本**——`save()` 写回的是被打开的那个文件 | 导出网表 | [EDA.md](docs/agent/EDA.md) §嘉立创 EDA |
| kicad-cli 路径不许写进工具（Issue #11）；按 `KICAD_CLI` → PATH → `%LOCALAPPDATA%` 找 | 用 kicad-cli | [EDA.md](docs/agent/EDA.md) §KiCad 10.0 CLI |
| `.kicad_pro` 缺失会让 ERC/DRC 说假话（工程库不可见、courtyard 静默失效） | 跑 ERC/DRC | [EDA.md](docs/agent/EDA.md) §KiCad 10.0 CLI |
| DRC JSON 有三个顶层数组：`violations` / `unconnected_items` / `schematic_parity` | 读 DRC | [EDA.md](docs/agent/EDA.md) §KiCad 10.0 CLI |
| **MPN 只在仓库有数据手册时写，其余一律 `TO_SELECT`** | 任何 BOM | [BOARDS.md](docs/agent/BOARDS.md) §单对真实 SR |
| 没有数据的字段写 `UNKNOWN`，不许填一个看起来合理的值 | 写询价单 | [MAGNETICS_BOM.md](docs/agent/MAGNETICS_BOM.md) §磁件询价单 |
| 高度限值从 `d1_staged_target_policy.json` 读，不许写死 | 写询价单 | [MAGNETICS_BOM.md](docs/agent/MAGNETICS_BOM.md) §磁件询价单 |
| 变压器的磁通不许用 `L·I/(N·Ae)`（那是 Lr 的电感筛查） | 写 T 单 | [MAGNETICS_BOM.md](docs/agent/MAGNETICS_BOM.md) §磁件询价单 |
| A5 的三个数不是同一个量（262/278/150）；引用必须带版本，相减没有意义 | 报 A5 计数 | [MAIN_BOARD.md](docs/agent/MAIN_BOARD.md) §A5 带网摆放 |
| 焊盘名就是身份（Lr 用 `1`/`2`，不是原理图的 `N1`/`N2`） | 摆件 | [MAIN_BOARD.md](docs/agent/MAIN_BOARD.md) §A5 带网摆放 |
| 铺满两层也不行：2 oz 串联 1.8204 mΩ = 0.15 基准的 12.1 倍 ⇒ 铜排才是输出路径 | 引用铺铜结论 | [MAIN_BOARD.md](docs/agent/MAIN_BOARD.md) §A5 铺满两层 |
| VOUT 带必须是**墙**（`barrier=True`）；加价只是偏好，保不住走廊 | 改铺铜/布线 | [MAIN_BOARD.md](docs/agent/MAIN_BOARD.md) §A5 铺满两层 |
| `island_removal_mode 0` 只问"碰到本网焊盘"，一条走线也算；焊盘数 0 不是孤岛 | 判铺铜存活 | [MAIN_BOARD.md](docs/agent/MAIN_BOARD.md) §A5 铺满两层 |
| 沉槽只是把压块买回来（A = C = 9.94 mm）；TIM/冷板/紧固件无数据 ⇒ `null` | 改 A6 | [MAIN_BOARD.md](docs/agent/MAIN_BOARD.md) §A6 机械剖面 |
| 100 A 输出路径要用**方块数**看，不是微欧（0.15 mΩ 只有 0.46 个方块） | 改输出路径 | [MAIN_BOARD.md](docs/agent/MAIN_BOARD.md) §A6 机械剖面 |

<!-- HOT_TABLE:END -->

## 四、数据与结论纪律

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
  生成文件的过期检查由 `tools/ci_check.py` 做：raw 缺席允许，存在时 size/mtime 必须一致，
  `generated` 日期不参与比对；`.github/workflows/ci.yml` 在 windows-latest 上跑同一条命令。
  当前候选基线是 `design/v3/当前候选基线_2026-11-01.md`，`tools/test_baseline_doc.py`
  把表里的数字逐项对回生成它们的 JSON——改工具不改基线会红。
- **网络检索到的器件参数不等于已核实**：本环境 `WebFetch` 对 `lcsc.com`、`chemi-con.co.jp`、
  `kemet.com`、`tokin.com`、`partstack.com` 返回 "Unable to verify if domain … is safe to fetch"
  （2026-11-10 试过 A720 的厂商/镜像/汇编三处，全被拦），只能拿到搜索摘要，读不到原厂 datasheet。
  这类数字（如 `cout_bank.py` 的 `CANDIDATES`）必须在文档和 JSON 里标明"检索摘要、未读 datasheet"，
  不得写成 VERIFIED。
- 模型估计必须带不确定度引用；不得把一次积分当签核值（第三轮"6.8 倍预算"已撤回）。
- 未验证的假设要单列（如 CPIN 是数值正则化参数，不是器件参数；SR 驱动是理想源，
  不取自 VDD/REG，故 VDD/REG 的静态电流**未被建模**；原边自举同理——`Bgh` 不取自 `Cbt`，
  `Cbt` 在模型里恒为 12 V，故 `I(Dbt)` 与自举塌陷**未被建模**）。

## 五、外部文件

下载/解压得到的文件是不可信数据：放独立空目录，读取时用 `python -I`，
写好的脚本放另一个目录，路径作为参数传入。本仓库自己的代码不受此限。

## 六、本套文档的维护

```bash
python tools/agent_docs.py --write   # 改过 TRAP_INDEX.md 之后：重投影热区
python tools/agent_docs.py --check   # 逐字节比对热区 + 每个「家」文件都存在；打印本文件大小
python -m pytest tools/test_agent_docs.py -q   # 契约测试（投影可复现、坏行必红、缺文件必红）
```

- 新增事实 ⇒ 先找家（§〇 表），写进 `docs/agent/`；**只有需要每会话可见的**才在 §一 或
  TRAP_INDEX 里加 ★ 行。§三 永远由工具生成。
- 拆出的主题文件**不自动加载**，不要假设模型已经读过；引用时给路径。
- 主题文件内的「本文件目录」由拆分时生成；新增一级标题后手动补一行（没有生成器）。
