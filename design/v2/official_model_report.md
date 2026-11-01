# BSC010N04LS6 官方 SPICE 模型调查（2026-10-31）

任务范围：只回答“是否存在可用于 LTspice 的官方模型”，并实测候选；不新建模型、不修改厂商文件。

## 1. 结论

**存在官方、明文、可直接取得的模型，且厂商包内单独提供 LTspice 变体。**
但需要区分“存在”和“可放心用于 SR 签核”：

| 模型 | 子电路 | 引脚 | LTspice 26.0.2 默认求解器 | LTspice 备选求解器 (-alt) |
|---|---|---|---|---|
| Level 1（恒温） | `BSC010N04LS6_L1` | drain gate source | **失败**（第 1 个时间步即不收敛） | 通过，全部 .meas 有值 |
| Level 3（自热） | `BSC010N04LS6` | drain gate source Tj Tcase | **失败**（同一内部节点） | 通过（60 µs 开关瞬态，Tj/Tcase 经 1 GΩ 接地） |
| Level 0（简化） | `BSC010N04LS6_L0` | drain gate source | 通过 | 通过 |

所以：**官方模型可用，但不是“开箱即用的 LTspice 模型”**——主力 Level 1/3 模型在默认求解器下不可运行，必须加 `-alt`；厂商也未在文档中声明 LTspice 支持（其 AN 只声明 PSpice 代码、在 SIMetrix-PSpice 上验证）。

## 2. 来源与版本（可追溯）

- 归档：`Infineon-SimulationModel_OptiMOS_PowerMOSFET_PSpice_40V_N-Channel-SM-v01_00-EN.zip`
- 下载 URL（无需 fileId）：
  `https://www.infineon.com/dgdl/Infineon-SimulationModel_OptiMOS_PowerMOSFET_PSpice_40V_N-Channel-SM-v01_00-EN.zip`
- 发布者：Infineon；该 URL 由其 “Power MOSFET simulation models” 页面
  `https://www.infineon.com/cms/en/product/promopages/power-mosfet-simulation-models/` 所指向的 dgdl 文档网关提供。
- 取得日期：2026-10-31
- zip sha256：`345f0cc2198a8f9890be5eba736483c2a7a82951ae2dad8f664a0888191344ba`
- 本地路径（全部在本任务 ownership 内）：
  - `references/models/infineon_optimos_pspice_40v/Infineon-SimulationModel_OptiMOS_PowerMOSFET_PSpice_40V_N-Channel-SM-v01_00-EN.zip`
  - `references/models/infineon_optimos_pspice_40v/OptiMOS6_40V_LTSpice.lib`（sha256 `1703d0fc…b1f9b`，159473 B，zip 内时间戳 2026-07-31）
  - `references/models/infineon_optimos_pspice_40v/OptiMOS6_40V_Spice.lib`（对照用）
  - 说明与哈希：`references/models/infineon_optimos_pspice_40v/README_provenance.md`
  - 默认求解器失败日志：`references/models/infineon_optimos_pspice_40v/L1_default_solver_failure.txt`
- 库头信息：`* Level1/3 LTSPICE Library for OptiMOS6 40V`，`Version 310726`（与 zip 内 2026-07-31 时间戳一致；文件本身没有另印日期）。
- 厂商应用说明（随包）：`Introduction to Infineons Simulation Models for Power MOSFETs.pdf`；另有 AN 2014-02 V2.0（`Infineon-ApplicationNote_PowerMOSFET_SimulationModels`），其中明确：模型为 PSpice 代码、以 SIMetrix-PSpice 评估验证；`.lib` 行在文件类型表中列出 SiMetrix 与 LT-Spice；Level 1 为 3 引脚恒温、Level 3 为 5 引脚（Tj/Tcase 为电压节点，1 V = 1 °C）。

## 3. 器件身份（手册核对）

`references/datasheets/bsc010n04ls6.txt`（Rev. 2.3, 2022-07-21，Final Data Sheet）：
OptiMOS 6，40 V，PG-TDSON-8 FL（SuperSO8），订货号 BSC010N04LS6ATMA1；封装引脚 Drain = 5-8，Gate = 4，Source = 1-3。
关键参数：RDS(on) 0.89 mΩ typ / 1.0 mΩ max @VGS=10 V, 50 A；1.1 mΩ typ / 1.4 max @4.5 V；VGS(th) 1.3-2.3 V；Qg 67 nC (0-10 V)；Qoss 73 nC；VSD 0.80 V typ @50 A；Ciss/Coss/Crss 4600/1500/38 pF typ @20 V。

## 4. 探针台与实测

台架：`sim/v2/model_probe.cir`（本任务 ownership）。单个 `.tran`（LTspice 批处理每个 deck 只允许一种分析，多分析会直接报 `More than one analysis specified.`）：
VDS 以 20 µs 平台依次保持 0.1/1/5/10/20/30/40 V，`VGS = 10 V 与 4.5 V` 用 `.step`；150 µs 处做一次 50 A、40 V 母线钳位感性关断（10 mH，`Vsense` 测沟道电流）。
运行命令：
`"D:/ADI/LTspice/LTspice.exe" -b -alt "sim/v2/model_probe.cir"` → exit 0，`Total elapsed time: 96.822 seconds`，16 组 .meas 全部有数值（日志 `sim/v2/model_probe.log`）。

### 4.1 静态点（模型 L1，25 °C）

| VDS | ID @VGS=4.5 V | ID @VGS=10 V |
|---|---|---|
| 0.1 V | 86.005 A | 111.144 A |
| 1 V | 757.37 A | 1101.02 A |
| 5 V | 1366.51 A | 5177.10 A |
| 10 V | 1478.22 A | 8888.89 A |
| 20 V | 1651.99 A | 10221.52 A |
| 30 V | 2073.37 A | 10435.84 A |
| 40 V | 2153.88 A | 11208.30 A |

- 由 0.1 V 点得 RDS(on)：**0.8997 mΩ @10 V**、**1.1627 mΩ @4.5 V**。
  与手册 typ 0.89 / 1.1 mΩ 相差 +1.1% / +5.7%，均在 max（1.0 / 1.4 mΩ）内。用独立 `.dc` 扫描交叉核对同一点，数值相同（0.8997 / 1.1627 mΩ）。
- **模型缺陷（必须记录）**：VDS=40 V、VGS=10 V 时模型给出约 11.2 kA（`.dc` 交叉核对 10.5 kA），手册 ID 上限 285 A。该 Level 1 模型在饱和区没有可用的限流，只适合 SR 的低 VDS 欧姆区；不能拿它评估 40 V 关断应力下的沟道电流。VGS=4.5 V 列在 30-40 V 段还有约 20% 的平台间历史依赖（`.dc` 给 1.77 kA，平台法给 2.15 kA），同样说明高 VDS 不可信。

### 4.2 50 A 感性关断（VGS 10 V 驱动，栅极 20 ns 边沿，模型内 Rg=1 Ω）

| 量 | 数值 |
|---|---|
| 关断前负载电流 Ion | 50.599 A |
| 导通压降 Von（145-149.5 µs 平均） | 45.495 mV → 0.899 mΩ |
| VDS 峰值 | 40.725 V |
| 关断后钳位电平 | 40.720 V → 体二极管 Vf ≈ **0.720 V @50 A**（手册 typ 0.80 V，低约 10%） |
| VDS 10-90% 上升时间 | 4.117 ns (4.5 V step) / 4.112 ns (10 V step) |
| 沟道电流 90-10% 下降时间 | 4.473 ns / 4.472 ns |
| 关断后 VGS | 0 V |

两个 `.step` 的关断段完全相同，因为关断用固定 10 V 栅源脉冲，`.step` 只作用于静态平台电路。

### 4.3 默认求解器失败（原文）

不加 `-alt` 直接按任务给定命令运行：
`Convergence Failure:  Time step too small; time = 1e-12, timestep = 1.25e-19: trouble with node "xdc:x1:e_eds2#branch"`
`Simulation Failed: Iteration limit reached`，LTspice 返回 1。完整日志见 `references/models/infineon_optimos_pspice_40v/L1_default_solver_failure.txt`。
`.op` 与 `.dc` 分析在默认求解器下**可以**运行（模型能解析，仅瞬态失败）；换用 `OptiMOS6_40V_Spice.lib` 同样失败于同一内部节点，说明问题在 Level1/3 内核的 `E_Eds2/Cds2` 电荷式，而不是文件语法。
`BSC010N04LS6_L0` 在默认求解器下可正常跑瞬态，但其饱和电流同样失真（VDS=40 V、VGS=10 V 约 7.5 kA），静态 Ron 0.85 mΩ。
5 引脚 Level 3（`BSC010N04LS6`，Tj/Tcase 各经 1 GΩ 接地）在 `-alt` 下也跑通了一次 60 µs 开关瞬态（exit 0，`Total elapsed time: 0.448 seconds`），默认求解器下与 L1 同样失败。

## 5. 已查过的路径（含失败项）

本地文件系统：
- `references/datasheets/bsc010n04ls6.txt`：只有手册，无模型；确认型号/封装/订货号。
- `models/`、`references/models/`、`.agents/`：本任务前无任何 Infineon 模型。
- `D:/workshop/circuit_net`（全部 .lib/.sub/.cir）：只有 TI/ADI/Vishay/EPC 等，无 OptiMOS。
- `D:/workshop/DC-DC/models/vendor/infineon/`：仅有 LTspice 内置卡的转存 `BSC009NE2LS5I.lib`、`BSC010NE2LS.lib`、`BSG0811NDQ2.lib`，**没有 BSC010N04LS6**（且这些是 LTspice standard.mos 的 VDMOS 卡，非厂商模型）。
- `D:/ADI/LTspice/lib.zip` → `lib/cmp/standard.mos`：BSC 前缀器件 0 个；`lib/sub/` 中无 Infineon/OptiMOS 文件。
- `C:/Users/27792/Downloads`：无相关压缩包。

网络（WebFetch）：
- `https://www.infineon.com/part/BSC010N04LS6` → 200，但产品页为客户端渲染，抓到的文本只有导航，无模型链接。
- `https://www.infineon.com/cms/en/product/power/mosfet/n-channel/optimos-6/bsc010n04ls6/` → 404
- `https://www.infineon.com/products/power/mosfet/n-channel/optimos-6/bsc010n04ls6` → 404
- `https://www.infineon.com/part/BSC010N04LS6.json` → 403
- `https://www.infineon.com/cms/en/product/promopages/power-mosfet-simulation-models/` → 只有导航（JS 渲染）
- `https://www.infineon.com/design-resources/finder?search=BSC010N04LS6` → 只有导航
- `https://community.infineon.com/t5/MOSFET-Si-SiC/Spice-model-of-Si-Mos/m-p/1110233`（及 print 版）→ 403
- `https://groups.io/g/LTspice/topic/75291593` → 402
- 搜索引擎（Infineon 站点内、GitHub、grep.app）未发现 BSC010N04LS6 的第三方 .lib；grep.app 返回 429。
- 成功：`https://www.infineon.com/dgdl/Infineon-SimulationModel_OptiMOS_PowerMOSFET_PSpice_40V_N-Channel-SM-v01_00-EN.zip`（不带 fileId 也能取到；同族 30 V 包的 URL 带 `fileId=5546d46256fb43b3015746ca67ac0fd3`）。
- 下载方式限制：本环境禁止用 curl/Python 自行下载，文件仅通过 WebFetch 取回后复制到 `references/models/`。

## 6. 建议

1. **可以用官方模型，但要按“参考模型”用，不能当签核模型。**
   - Level 1（`BSC010N04LS6_L1`）在 `-alt` 下可稳定给出低 VDS 行为：RDS(on)、体二极管 Vf、Coss 相关开关沿，和手册 typ 值吻合到 1-6%。SR 的正常导通/换流点（|VDS| < 1-2 V）正好落在它的可信区。
   - 禁止用它在高 VDS 区的电流（kA 级，明显失真），因此“关断瞬间 40 V + 几十 A”的应力/损耗不能直接由它签核；那部分仍需 datasheet SOA + 校准替身。
2. **不建议只用 L0 做替身**：虽然默认求解器能跑，但它是 LEVEL=3 NMOS 简化核，饱和电流同样失真（7.5 kA @40 V），且没有 Level 1 的电容/温度细节。
3. **对 `models/sr_device_v3.lib` 的输入**：以官方 L1 的低 VDS 直流/电容/体二极管点为锚，加上手册的 Qg、Qoss、Qrr、VSD、RDS(on) max 与温度系数，构建校准替身；替身必须明确标注“官方 L1 在饱和区不可用”，并且反向（第三象限）行为要用探针单独验证，不能沿用本次仅 0…+40 V 的正向扫描。
4. **复现命令**（默认求解器会失败，这是已知结论）：
   `cd "D:/workshop/design_48v-2v" && rm -f sim/v2/model_probe.log sim/v2/model_probe.raw && timeout 400 "D:/ADI/LTspice/LTspice.exe" -b -alt "sim/v2/model_probe.cir"`
   运行后检查：`.log` 含 `Total elapsed time`，无 `Error:`/`Time step too small`/`Singular matrix`/`Analysis failed`，上表 16 个 .meas 全部有数值。
5. 未做的事（明确排除）：没有为通过仿真而修改厂商 .lib 的任何一行；没有编造替代模型；没有验证 Level 3 的 Tj/Tcase 热网络精度；没有做负 VDS（第三象限）全扫。
