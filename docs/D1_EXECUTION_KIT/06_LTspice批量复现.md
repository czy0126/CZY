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
| P0 | sim/v3/sr_tank_dual_v33_ss_hotfault_50v_120a_cshunt_srprobe_prot_b_fast10u_1p8v_noclamp_control.cir | 与 PROT-B 同拓扑、仅钳位关闭的 50V 配对负对照；当前尚无 RAW |
| P0 | sim/v3/sr_tank_dual_v33_ss_hotfault_50v_120a_cshunt_srprobe_prot_a_oc1v_noclamp_control.cir | 同理 PROT-A 配对负对照 |
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
- 记录改变的唯一变量；添加 cshunt、理想开关、失压/软启动逻辑等均是**模型变更**。50V 旧比较有 13–18mV 故障前 Vout 偏移，未做配对确认前不能归因于保护。
- 每只 SR 单列 Vgs/Vds/Id、正反峰值、I²t、末端门态、触发/关断延迟、波形截图及客观判据。源漏反向电流不能仅按门压分割沟道/体二极管。

## 5. 数据回填及自动化边界

将一次运行填入 templates/simulation_run_register.csv 的**新副本**，不能改空白模板冒充结果。需要保存 SHA256、仿真版本、参数、测量时间窗、RAW 成功与否、审查状态。用户成本无限也不等于结果可以省略误差、重跑或只比较“最好一次”。

验证工具：

    python -m pytest tools/test_make_paired_protection_controls.py tools/test_protection_candidate_compare.py tools/test_protection_soa_table.py -q
    python tools/d1_fabrication_gate.py --require-release

前者检查脚本与已有分析数据；后者即使 Python 测试全绿也应暂时拒绝制造。
