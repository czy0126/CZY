# D1 V17 集成候选：三工作包并行交接（2026-11-14，NOT_FOR_FAB）

> **入口与权威**：总体决策仍以 [D1_CURRENT](../D1_CURRENT.md) 的 A（功率PCB）、B（磁件）、C（保护）三包为准。本文是基于 `59da26982e4d208e85dc2bdbb5608fc64c147a96` 的**并行执行合同**，不是新的第二份状态表，也不允许覆盖已有本机成果。对应实际KiCad证据见 [V17集成审核](D1_V17_INTEGRATION_20261114_NOT_FOR_FAB.md)。

## 已核实的共同起点

- 此基线为 **KiCad 10.0.6重建的V17候选**，不是最新嘉立创V18的直接后继或已验收的制造主版；不允许将V17的DRC数字套在V18 `.eprj2` 上。
- 已归档12铜层、149 footprints、425 pads、11 zones、359 vias；实存KiCad DRC 0 rule violation、**9 unconnected**（SW 3，VIN_P 2，GH/GH_DRV/HB/OC各1）。这只是当前已进入KiCad的网络。**五个真实磁件（CT/T1–T4）与24物理端子没有入板**，是明确的另一个阻塞。
- 公开GitHub另有 [V18原生布置PR #130](https://github.com/czy0126/CZY/pull/130)，149组件/508线/106孔且106 Connection错误；它在Cin位置、T1-SR单元方面有真实改善，但不是这份KiCad候选的净表等价版本。对照后选择特定布置改动逐项移植，**不做二进制PCB合并**。
- 本机原目录 `D:\workshop\design_48v-2v` 已有大量未提交的T530 OEM land、Maxwell及预算修改；这些内容由原工作区负责保留，任何并行Agent不得强制checkout、clean、reset、覆盖冻结父板。

## 并行写入权与交付（WIP三个，集成者不算第四份独立设计）

| Lane（待指派） | 隔离修改范围与最小实体成果 | 验收/交给集成者 |
| --- | --- | --- |
| **A · PCB电气/EMC** | 自V17复制**独立候选板**，原边Cin/QH/QL/SW/Cr/CT/Lr功率回路重布局；先处理高电流铜颈、最短返回路径及GH/HB Kelvin。只改 A 分支的KiCad生成器、候选PCB和A专属证明；同时参考V18的5mm Cin热环改善，不把全部信号细线作为等效大电流连接 | 本分支真实KiCad PCB hash + DRC JSON；SW截面积/交流RMS与绕组端子假设；不得跨命名网短接；独立重开DRC，不得拿“0 physical”冒充9开路已闭合 |
| **B · 磁件/制造栈** | 从同一基线独立制作T1–T4、CT绕组图及24pin逻辑→实际铜层/脚/DOT端子表、Maxwell真实电流激励；检查12层绕组与VOUT/PGND平面争层、窗口高度和板厂可制性；保留实测/原始AEDT | 带真实绕组候选而非空逻辑Pad、每只极性/匝比/磁芯局部B与热损耗和网格收敛；供应商未签的字段必须继续false；提供几何/接口Patch而非直接覆盖A板 |
| **C · 保护+输出PI** | 只在专属设计/仿真/证据目录核查D0失偏置默认OFF、十路SR VGS/低能量关断、100A双极端子与冷板热态压降及接点模型；复用现有Maxwell/台架数据的真实来源 | 台架原始同步波形、25/50/100A分级的安全许可、真实四线接点阻抗（未测则明确PENDING）、铜路3D和温升；不得把理想仿真写成实测 |

**集成者（唯一主板写入者）**：持有集成分支、冻结待合并CAD hash；分别选取A的网络结构、B的24端子与层叠、C的保护/输出接口，按顺序执行 **源版本锁定→原理图逐脚核对→独立原生打开/网表/DRC→3D/热/EMI→制造审核**。冲突时由集成者重建完整新板，不以先到先得合并最后一个二进制。三个Lane只在自己专属worktree提交，可独立PR；集成之前给各Lane一份共同的输入PCB SHA。

## 防止“所有 Agent 都修好了”的假阳性

所有分支的交付备注至少包含：`base_commit`、`input_pcb_sha256`、`output_pcb_sha256`、`changed_net_list`、`native_drc_before_after`（含使用的真实工具、检查规则）、`new_connection_and_fab_blockers`、`validation_commands`。多分支之间文件SHA若不一致，DRC和网表数据**不允许混算**。任何 Agent 不拥有将 `NOT_FOR_FAB` 改成制造通过的授权。

可运行的源绑定门禁：

```powershell
python tools/d1_v17_release_audit.py --write
python tools/d1_v17_release_audit.py --check
python tools/d1_v17_release_audit.py --require-release  # 当前必须返回2，才是正确拒绝制造
python -m pytest tools/test_d1_v17_release_audit.py -q
```

该脚本读取**实存KiCad PCB、原生DRC、149器件逐脚读回、磁件24脚厂家回件记录**，KiCad板文件/其他证据用真实字节SHA，历史DRC JSON另按已确认的Windows CRLF存档SHA复核（同时保留本机实际字节SHA），拒绝任意内容改动；DRC 0违规和PGND/VOUT零开路只是其中两项，漏磁件/厂家物理PIN/DOT/正式封装/100A/EMC/保护证据必须另验，绝不自动放行。

## 此阶段集成优先级

1. **先建真实五磁件绕组与完整同版网表**；如果抢用In5..In8的电源面与12L绕组冲突，重新分层与走线，禁止维持现有形式只是为了报0 DRC。
2. **再重布原边功率热环和实铜连接**，重点不让细SW短迹变成3.5mm×0.45mm功率颈；V18的Cin局部结构只作为经原网表、铜厚与几何验证后的可移植子集。
3. **同步验证100A两极与D0安全**；若缺台架原始数据，只交机械/PCB/仿真输入，不准出Gerber或高能量上电。

本文件中的 Lane 名为工作包，**未指认任何具体Agent已接受任务，也未声称任何并行作业已被执行**。
