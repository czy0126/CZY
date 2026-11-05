# LTspice：复现、差分与证据留档

目标不是不断生成 .cir，而是每个结论都能回答：**哪份原始 deck、哪台模拟器、哪个求解窗口、RAW 是否跑满、几次重复、是否改变工作点？**

## 1. 清洁环境安装

Windows 本地安装官方 LTspice（ADI），记录版本号与路径；仓库 Python 依赖：

    python -m pip install -r requirements.txt
    python tools/ci_check.py

已有 power shell dry-run 工具：

    pwsh -File tools/run_dcx_pending_cases.ps1

旧启动器默认的原基座热故障已运行过，若执行 -Execute 必须先按脚本提示归档旧 .log/.raw，否则会拒绝覆盖。此功能不负责跑新 PROT-B 配对对照。

## 2. 建议按先易后难的实验顺序（不能只拿成功样本）

| 优先级 | 仿真输入 | 检查 |
|---|---|---|
| P0 | sim/v3/sr_tank_dual_v33_ss_hotfault_50v_120a_cshunt_srprobe_prot_b_fast10u_1p8v_noclamp_control.cir | **已运行**（527.175 s，320 µs 完整）：与 PROT-B 同拓扑、仅钳位关闭；但故障前比候选低 **17.5 mV**，所以它**不是**配对对照，只作完整窗口的负对照 |
| P0 | sim/v3/sr_tank_dual_v33_ss_hotfault_50v_120a_cshunt_srprobe_prot_a_oc1v_noclamp_control.cir | **已运行**（559.690 s，320 µs 完整）：同理，故障前低 **13.2 mV** |
| P0 | sim/v3/..._prot_{a,b}_..._thrmute_control.cir | **已运行但塌缩**：配对 **0.000 mV**，停在 **250.151 / 254.980 µs**（按 PID 终止，日志无 `Total elapsed time`）；PROT-03 的配对判据成立、完整窗口判据不成立 |
| P0 | 50V 基准热故障 deck | 报告停算 296.929µs 原因；cshunt=1fF 不是电路鲁棒证明 |
| P0 | 48V/50V PROT-B 真实驱动/关断替代版 | 替换理想开关后重跑 8×SR 与原边 |
| P1 | 100A 5/2/1/0.5ns 同参数全窗 | 模型工作点移动、能量损耗与求解器稳定性 |
| P1 | cold/OC/重启功率级 | 别把稳态 .ic 当作真实冷启动，保护屏蔽期间不能遗漏 |

原工具入口：tools/make_paired_protection_controls.py、tools/protection_candidate_compare.py、tools/protection_soa_table.py、tools/energy_ledger_100a.py、tools/sr_energy_ledger.py。**只运行 Python 工具不等于重新生成 RAW**；汇总表只是复用先前 JSON 时须显示 SIMULATED_ONLY。

## 3. 建议的本地批处理

在已验证 LTspice 路径的 PowerShell 中：

    $lt = "C:\Program Files\ADI\LTspice\LTspice.exe"
    $d = "sim\v3\sr_tank_dual_v33_ss_hotfault_50v_120a_cshunt_srprobe_prot_b_fast10u_1p8v_noclamp_control.cir"
    & $lt -b -ascii $d
    if ($LASTEXITCODE -ne 0) { throw "LTspice failed" }

真实路径因 Windows 机器而异；开始前校验 $lt 与 $d 存在。先将旧同名 .raw/.log 搬入按日期命名的结果目录，**不覆盖上一组波形**。保存 .cir 的 SHA256、.raw/.log SHA256 和外部冷存档目录。若仓库无 .raw，不得假装可本地复算。

## 4. 任何“完成”的四条证据

- .tran 声明停止点与保存偏移、RAW 最后 t、log 完整状态三方相符；非 320µs 全窗不能报告完整故障。
- 同一时间窗统计 P_in、P_out、SR/原边损耗与端点储能；峰值与稳态平均不得混用。
- 记录改变的唯一变量；添加 cshunt、理想开关、失压/软启动逻辑等均是**模型变更**。50V 旧比较有 13–18mV 故障前 Vout 偏移，未做配对确认前不能归因于保护。**2026-11-03 补跑后**：no-clamp 控制仍是 13.2/17.5 mV（完整 320 µs），thrmute 控制配对到 0.000 mV 但塌缩在 250.151/254.980 µs——两条判据没有同时成立，所以截断切片上的收益只能写成"可归因于保护的切片值"。
- 每只 SR 单列 Vgs/Vds/Id、正反峰值、I²t、末端门态、触发/关断延迟、波形截图及客观判据。源漏反向电流不能仅按门压分割沟道/体二极管。

## 5. 数据回填及自动化边界

将一次运行填入 templates/simulation_run_register.csv 的**新副本**，不能改空白模板冒充结果。需要保存 SHA256、仿真版本、参数、测量时间窗、RAW 成功与否、审查状态。用户成本无限也不等于结果可以省略误差、重跑或只比较“最好一次”。

本轮已填 `templates/simulation_run_register_PROT03_2026-11-03.csv`（六行，与空白模板同列）：
deck/log/raw 哈希、`last_saved_us`、故障前 Vout 与配对差值都由 JSON 记录生成，
`tools/test_prot03_run_register.py` 逐行回查。两个 thrmute 行 `full_duration = KILLED_BY_PID`，
端口/账本列是 `PENDING`——故障 deck 没有这些测量，空着比填估计值诚实。

验证工具：

    python -m pytest tools/test_make_paired_protection_controls.py tools/test_protection_candidate_compare.py tools/test_protection_soa_table.py -q
    python tools/d1_fabrication_gate.py --require-release

前者检查脚本与已有分析数据；后者即使 Python 测试全绿也应暂时拒绝制造。

## 6. 2026-11-05 远程多 lane 运行结果守门（已提交代码）

远程批处理入口 `tools/remote_lanes.py` 用于 Windows 上已安装 LTspice 的模拟主机。和本地 `python tools/ci_check.py` 不同，它确实启动后台批处理进程；**本次仅通过离线合成样例检验启动器，未从 ChatGPT 实际连接 winsrv 跑新 RAW。**

上一版启动器只要退出后看到 `.raw` 和 `.log` 文件存在就将 lane 计为成功；实际 LTspice 可在启动时写好 `.log` 而 RAW 仍是 0 字节，或出现合法文件但波形尚未结束。已改为 fail-closed 检查：

- 子进程须**退出码为0**；`.raw/.log` 非空；ASCII RAW 头有 `No. Variables`、`No. Points` 均大于0及 `Values:` 后面的样本；日志有 `Total elapsed time` 完成标记且没有明确错误标记。**此轻量完成预检并非完整RAW解析：仍须依首节核对停止时间与RAW最后采样点。**
- 任一 lane 失败不得以部分完成计算 `all_same=true`；如指定 `--reference`，必须所有 lane 成功且所有非时间戳RAW内容哈希完全一致，否则脚本**退出码1**并列出不一致序号。
- CPU停滞且 RAW 不增长超过配置的阈值时重启；即使 0 字节 RAW 已存在、CPU 性能计数器不可用，也不能永久跳过超时；但重试不等于故障仿真已达到科学结论。
- `--root` 内部 deck 不得用绝对路径或 `..\` 越界；一次批次使用唯一 `sim/lane_*\` 目录，防止同秒重跑覆盖旧结果。报告记录每一路失败原因、重试次数和完成哈希。
- `body_hash` 忽略 ASCII RAW 前两行 Title/Date，**仅是波形主体相等的粗筛**；不能证明 LTspice 求解值准确、模型没被改、器件 SOA 已满足。运行时还需分别保存原始 deck 的 SHA-256、模型库版本、参数和环境、完整 RAW/LOG 及终点时间检查。

验证：`python -m pytest tools/test_remote_lanes.py -q`，`python tools/ci_check.py`。真正运行仅在准备好远程机和原生 LTspice 的环境中执行（使用约束在脚本 `--help` 和 winsrv 运维文档）；不要为了追求批处理吞吐率继续重复已做足的 50V B 组扫参，优先修正 D0 保护板的模拟漏判，再进行硬件测量。
