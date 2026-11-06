# 完整命令表（改了什么 → 跑什么）

> 从 `CLAUDE.md` 拆出（2026-11-06）。**本文件不自动加载**。
> 家的分布与热区见 [`../../CLAUDE.md`](../../CLAUDE.md)，
> 一条一条的硬规则见 [`TRAP_INDEX.md`](TRAP_INDEX.md)。
> 旧引用里的「CLAUDE.md §小节名」按那里的表解析到本文件。

## 本文件目录

- 运行与测试

## 运行与测试

```bash
python -m pytest tools -q          # 全部离线工具测试，必须全绿
python tools/make_round4_decks.py  # 生成 round-4 deck（改母 deck 后必须重跑）
python tools/magnetics_design.py --json design/v3/magnetics/magnetics_design.json
    # 同一张表里有 catalogue_core_stack：五种 TDK ELP 套件在 D1 16 mm / D3 10 mm 下的 Z 预算
python tools/draw_magnetics.py --out design/v3/magnetics   # 含 winding_connections.svg（带 DOT 端子图）
python tools/winding_polarity.py --out design/v3/magnetics # 端子 DOT 表 + 首件极性记录（由 deck 派生）
python tools/make_magnetics_manifest.py   # 改磁件包任一文件后重跑（含 SVG/源工具）
python tools/thermal_precheck.py --json design/v3/stage_f/thermal_precheck.json
python tools/passive_requirements.py --json design/v3/bom/passive_requirements.json
python tools/passive_requirements.py --cin-raw sim/v3/sr_tank_dual_v33_ss_1ms_100a_cin.raw \
    --json design/v3/bom/passive_requirements.json   # 追加输入电流（需先有探针 raw）
python tools/lr_design.py --json design/v3/bom/lr_design.json   # Lr 匝数/气隙/Isat 表
python tools/transformer_flux.py --json design/v3/magnetics/transformer_flux_100a.json
    # 变压器磁通由副边实测电压积分（T1/T4 各半），不是方波公式；需 313 MB 100 A raw
python tools/cout_bank.py --json design/v3/bom/cout_bank.json   # Cout 并联数量与主导约束
python tools/cr_bank.py --json design/v3/bom/cr_bank.json   # Cr 容值带/配平耦合/容差与 E12 落点
python tools/cin_bank.py --json design/v3/bom/cin_bank.json # 输入电流要求/纹波表/ESR 预算（读三条 _cin raw）
python tools/cr_stress.py --json design/v3/bom/cr_stress.json   # 由 I(Lr) 积分重建 v_Cr
python tools/ct_design.py --json design/v3/bom/ct_design.json  # CT 传递链/负载与分压（10 Ω 已冻结）
python tools/oc_network_check.py --raw sim/v3/sr_tank_dual_v33_ss_1ms_100a_ct10.raw \
    --burden 10 --rd1 10k --json design/v3/bom/oc_network_ct10.json   # 实测 OC 网络，需带 V(oc*) 的变体 raw
python tools/make_startup_burden_probe.py --write   # 冷启动 burden 探针 deck：只加 V(ocd) V(ocm) I(Rbur)
python tools/startup_burden_pulse.py --json design/v3/bom/startup_burden_pulse.json
    # 冷启动 R3 脉冲：由 I(Lr) 经理想变比推导；传递比在 hotfault srprobe raw 上标定
    # 约 90 s（冷 raw 8 ms 全读），评级阶梯读 r3_vendor_rating_screen.json（PR 28）
python tools/startup_burden_direct.py --json design/v3/bom/startup_burden_direct.json
    # 冷启动 burden 直接测量：读 probe deck 的 8 ms raw（约 14 GB，不入 Git），
    # 与推导值比对峰/能量；raw 不在时 SystemExit
python tools/connector_budget.py --json design/v3/bom/connector_budget.json  # 输出铜排/接点预算
python tools/output_path_budget.py --json design/v3/pcb/output_path_budget.json  # 板上 100 A 平面方块数（读摆放）
python tools/cout_bank_path.py --json design/v3/bom/cout_bank_path.json  # Cout 整组铜箔/接点项（读摆放；SOURCE-04）
python tools/board_netlist.py --json design/v3/pcb/board_netlist.json \
    --csv design/v3/pcb/board_netlist.csv   # 主功率板逐脚网表，由 v3 deck 派生
python tools/powerup_checklist.py --md design/v3/stage_f/上电检查表.md \
    --json design/v3/stage_f/powerup_checklist.json   # 上电检查表，判据由各 JSON 渲染
python tools/current_manifest.py --scope v3 \
    --json design/v3/manifest_current_candidate.json   # 可复现当前清单（v2 仍是不带 --scope 的默认）
python tools/extract_op_point.py <raw> --rl <ohm> --periods 22 --json <out>
python tools/energy_ledger_100a.py --json design/v3/stage_f/energy_ledger_100a.json
python tools/sr_loss_audit.py --json design/v3/stage_f/sr_loss_audit.json
    # SR 量纲/步长/驱动功率专项排查；要本地有六条 raw（含 2.44+2.25+3.78 GB），约 20 min
    # 100 A 同窗口端口能量账；默认读 ..._100a_ledger.raw（424 MB，不入 Git）
python tools/vendor_soa.py --json design/v3/power_priority/vendor_soa_digitized.json
    # SOA/Zth 数字化；需 PyMuPDF（**不是项目依赖**，CI 上没有时该重生成测试自动 skip）
python tools/sr_soa_screen.py --json design/v3/power_priority/sr_soa_screen.json
    # 八只 SR 的一/三象限与 Zth 温升；需三条 srprobe raw（各约 1.1–1.2 GB）
python tools/ci_check.py            # pytest + 重新生成 v3 manifest 并逐项比对
python tools/ci_check.py --skip-tests   # 只查生成文件是否过期
python tools/make_control_board.py --check   # 控制验证板：重生成 + 网表 + ERC（需本机 KiCad 10.0）
python tools/main_board_mechanical.py --check   # A5 带网摆放（1:1）：重生成 + SVG/PNG + DRC + 老鼠线计数（需 KiCad 10.0）
python tools/main_board_power_copper.py --json hardware/dcx_mech/routed_copper.json
    # A5 布线草稿：从摆放板派生走线 + 量输出路径方块数 + 铺满两层解电阻网络
    # （DRC 可选，--no-drc 跳过并省掉铺铜；约 38 s 布线 + 约 2 min 铺铜）
python tools/main_board_power_copper.py --check   # 重布 + 重铺重解 + 比对板子/报告，约 3 min，不需要 kicad-cli
python tools/make_d0_protection_board.py --check   # D0 十路保护板：重生成 + 网表 + ERC（需 KiCad 10.0，缺了直接 SystemExit）
python tools/make_sr_fault_board.py --check       # 单对真实 UCC24624 SR 故障关断验证板：重生成 + 网表 + ERC + 争流算术
python tools/make_sr_fault_board_pcb.py --check   # 该板的布线 + 铺铜 pass 3：重生成 + kicad-cli DRC + 冲 fill.json + 导出 fab/
python tools/make_sr_fault_board_pcb.py --fab     # 同上，缺 kicad-cli 时直接失败；fab/ 里含 assembly.svg
python tools/assembly_drawing.py --check          # 装配/DNP 图（A4 1:1）：重生成并与 fab/assembly.svg 比对
python tools/make_fast_oc_eco.py --check          # TLV3501 快速过流 ECO 模块：重生成 + 网表 + ERC + 延迟/门限算术
python tools/make_fast_oc_pcb.py --check          # 该模块的布线板：重生成 + kicad-cli DRC（需 KiCad 10.0，缺了 SystemExit）
python tools/make_fast_oc_pcb.py --fab            # 同上 + 导出 pcb/fast_oc/fab/（13 个散列文件、9 层、assembly.svg、manifest）
python tools/manufacturing_index.py --check       # 四块实验板的制造目录 pcb/manufacturing/{index.json,README.md}（--write 重生成）
python tools/remaining_dependencies.py --check    # 主板剩余依赖表 hardware/dcx_main/remaining_dependencies.{json,md}（--write 重生成）
python tools/magnetics_rfq_package.py --write     # 磁件询价单：T1–T4/Lr/CT 各一张，UNKNOWN 必须显式列出
python tools/magnetics_manufacturing_input.py --write  # 加工输入页：每件冻结一个候选 + 首件判据 + 空白回填
python tools/magnetics_manufacturing_input.py --check  # 页面是否过期（与 --write 同源，只比字节）
python tools/placeholder_eco.py --write          # 61 占位逐件责任清单（json + csv），只连表不造 MPN
python tools/run_d1_50v_matched_cases.py     # PROT-03 50 V A/B 配对实跑（默认 dry-run）
python tools/run_d1_50v_matched_cases.py --variant shunt_2f   # PR 30 数值扫描（shunt_2f/5f/10f）
python tools/run_d1_50v_matched_cases.py --execute --run-id d1_50v_001 \
    --ltspice D:/ADI/LTspice/LTspice.exe     # 归档到 out/d1_50v/<RunId>/，只判 320 µs 完整性
python tools/d1_protection_precheck.py --check   # 十路硬件关断接口契约（--write 重生成）
python tools/d0_scope_sync_align.py --manifest out/d0_scope/sync.json \
    --csv out/d0_scope/aligned.csv --report out/d0_scope/aligned.json
    # 多示波器对齐 -> 第29章 12 列 CSV；网格不得细于最粗原始间隔，不外推
python tools/d0_evidence_chain.py --manifest out/d0_scope/sync.json \
    --alignment out/d0_scope/aligned.json --csv out/d0_scope/aligned.csv \
    --config out/d0_scope/limits.json --audit out/d0_scope/audit.json \
    --report out/d0_scope/chain.json
    # 绑定对齐/限值/审计四件套；审计报告必须能被同一 CSV+配置逐项复现
```

**D0 多仪器对齐的两个硬约束（`tools/d0_scope_sync_align.py`）**：输出 `dt_s` 必须 ≥ 所有原始记录的最大相邻间隔
（否则等于凭空造分辨率）；manifest 的 `trigger.threshold_v` 应与第29章的 `trip_high_min_v` 相同，
否则对齐后原点样点可能落在 `trip_low_max_v` 与 `trip_high_min_v` 之间，被审计器判为 ambiguous。
`basis_review_status` 不是 `ENGINEER_REVIEWED` 时仍会写 CSV，但退出码 1；物理同时性永远为 false。

**证据链绑定（`tools/d0_evidence_chain.py`）只证明四份工件是同一次采集**：对齐报告、CSV、限值配置、
审计报告按 SHA-256 与 `case_id` 互绑，并把审计报告**重新算一遍**逐项比对（`source` 之外的
全部字段，含 `capture_provenance` 回显与每路 `deadline_s`/`permanently_safe_from_s`；`source`
里的路径与摘要由哈希检查单独负责）。对齐报告自身不被任何哈希
绑定，所以工具也**重新运行第31章对齐**（`align.build` + 重写 CSV 比对字节），要求除路径外的**全部字段**
逐项相同——字段集取"全集减路径"而非白名单，所以 `limitations`/`warnings` 也在内，删掉"波形来源
未认证"这类安全声明同样会被抓；`output` 里由 `run()` 追加的 `csv_path`/`csv_sha256` 除外（摘要本就
直接与 CSV 比对）。手改 `post_s`、`declared_max_remaining_skew_s` 或伪造 `manifest_sha256` 都靠这一项抓
（`alignment_report_is_reproducible_from_the_manifest`）；CSV 的行数/等间隔/首末时刻三项仍然保留。
**原始仪器 CSV 必须在 manifest 写的路径上**才能复算：`_load_state` 对缺失文件抛的是
`InvalidAlignment` 而不是 `OSError`，所以可用性要先自己 `is_file()` 判断；缺失时记
`reproduction.status=UNAVAILABLE` 并降为退出码 1（`CHAIN_CONSISTENT_PROVENANCE_INCOMPLETE`），
不判伪造、也绝不放行。**审计报告没有 `physical_simultaneity_proven` 字段**（它不建模
物理同时性），所以该旗只在对齐报告上强制，其余四面两边都强制为 false；
`CHAIN_CONSISTENT_AUDIT_REJECTED`（退出码 1）是物理结论不通过，不是工具坏了，不要改配置让它变绿。

LTspice 批处理：`/d/ADI/LTspice/LTspice.exe -b -ascii deck.cir`。
**结束 LTspice 只能按 PID**：`kill <pid>`（`ps -W` 查）。禁止 `taskkill //IM LTspice.exe`
——权限分类器会拒绝，且会误杀其他会话的仿真。
`ps -W` 里的进程名是 **`LTspice`（没有 `.exe`）**，所以 `ps -W | grep LTspice.exe` 会返回空，
看起来像"仿真早就退出了"。判断跑没跑看 raw 是否在长大、以及 `rm` 是否报
`Device or resource busy`；不要信名字 grep。批量模式一次要跑十几分钟到数十分钟
（120 µs 窗口 176 s / 224 s；670 µs 约 2.4 GB、~40 min），别按"没输出"判死。

**本机 PowerShell 执行策略禁止运行 `.ps1`**：`powershell -File x.ps1` 直接报
`UnauthorizedAccess`（`execution policy`），会话权限也拒绝经 Bash 调 `powershell.exe`。
所以 PR 29 的 `tools/run_d1_50v_matched_cases.ps1` 在本机跑不起来；
`tools/run_d1_50v_matched_cases.py` 是它的逐行移植——同样四份 deck、同样三道 deck 门槛、
同样在 `sim/v3` 暂存（`../../models` 才解析得到）、同样拒绝覆盖归档与暂存文件、
manifest 里同样三面 false 旗——由 `tools/test_run_d1_50v_matched_cases_python.py` 锁住。
三处有意不同：搬运归档用 `shutil.move`（`os.replace` 不能跨卷，归档根可能在别的盘），
每例带 `--timeout-s`（默认 1800 s）——死区里求解器会一边把步长压到 1e-15 s 一边每 GB 级地写盘；
`--variant` 与 PR 30 的 `-Variant` 同步（`published`/`shunt_2f`/`shunt_5f`/`shunt_10f`，
换的是 `sim/v3/d1_prot03_<variant>_<case>.cir`），cshunt 门槛按变体取值，
且 manifest 额外记录 `variant` 与 `required_cshunt_farads`——扫描归档不得与 1 fF 已发布证据混淆。
变体名写进 manifest 是移植版独有的：`.ps1` 不记，两者归档因此不能逐字节比较。

**GBK 控制台打不出 `µ`（U+00B5 微符号），但打得出 `μ`（U+03BC 希腊字母 mu）和 `Ω`**：
`print("µΩ")` 直接 `UnicodeEncodeError: 'gbk' codec can't encode character '\xb5'`。
新工具的控制台输出要么写 ASCII `uohm`，要么用希腊 `μΩ`（`tools/cout_bank_path.py` 就是后者）。
JSON/Markdown 本身是 UTF-8，不受影响，只有 `print` 会炸——而炸在最后一行 `print(data["finding"])`
时前面的数字都已经印出来了，看起来像"跑完了"。`⇒`（U+21D2）同样不在 GBK 里。

**不要随手重跑 `python tools/make_round4_decks.py`**：`main()` 会重写全部已冻结 deck，
刷新 mtime，破坏"raw 与 deck 是否同一输入"的比对（见下）。只用它新增 deck 时，
单独 `import make_round4_decks as m; m.write(name, m.<变体>())`，只写目标文件。

