# 2026-11-10 G1复审及驱动布局增量

## 1. 实际交付

当前检出是`feat/d1-fab-package`，审核基线`d89f838`。11月7/8日对话中的偏置Rev B文件不在此分支，不能把它们算入当前集成状态。原G1文件保持MD5 `0d516efecae4c95b9baf2648b14c0a4f`。

新增可编辑候选：`dcx_main_board_g1_driver_eco.eprj2`。通过原生API在独立副本移动7件，`driver_apply.json`记录save=true；原有`.claude/`与`tmp_g1_probe/`工作未修改。此次并非只有报告修改。

| 位号 | 新中心位置mm（Y向下） | 目的 |
|---|---|---|
| U2 | 54,62 | 靠近QH/QL门极电阻 |
| C5 | 51,60 | 靠近HB/SW自举回路 |
| D_BT | 47,62 | 靠近自举电容 |
| C103/C104 | 57,65 / 57,67 | VCC12局部供电候选位置，值/料号仍须核实 |
| R18/R19 | 49,55 / 58,55 | 靠近相应MOS门源节点 |

**原生重开验证已通过（2026-11-10 补测）。** 首次重开读回曾 `REQUEST_TIMEOUT`，失败原文保留在 `driver_readback_timeout_2026-11-10T0208.json`；本轮按路径新开 session 后第一次 invoke 即返回成功（同一只读体在冷启动时可能超时、同 session 重试有效的已知现象）。读回 `driver_readback.json` 为 **77 件 / 299 焊盘 / 65 网 / 38 折线**，7 件新中心坐标逐项等于目标值，`audit_driver_eco.py` 非 preview 断言全部通过，生成 `driver_eco_report.json`（`reopened_readback: true`，`geometry_evidence: NATIVE_REOPEN_READBACK`）。候选重开当时仍没有走线、没有 DRC/ERC，也未取代基线用于投板。

**驱动短路铜增量（2026-11-10）。** 在候选的独立副本 `dcx_main_board_g1_driver_route.eprj2` 上用 `pcb_PrimitiveLine.create` 建了 **25 条第 1 层铜线**（GH_DRV 3、GH 8、GL_DRV 3、GL 8、HB 3），`driver_route_apply.json` 记录 25/25 成功、save=true。关会话后**按路径重新打开**读回：77 件 / 299 焊盘 / 65 网 / 38 折线全部不变，7 件移动位置漂移 0，25 条线逐条在网络、层、线宽与端点上覆盖计划（编辑器在 T 型节点把一条折线拆成两段，所以验收按“覆盖”而不是逐段同一）。`route_driver_eco.py --verify` 生成 `driver_route_report.json`，`driver_route.svg` 是同一份读回的驱动窗口平面图。**不是布通**：SW、D_BT、VCC12、PGND 回流仍未连，原因逐条写在计划的 `remaining_connections` 里；没有原生 DRC/ERC。

原G1文件保持MD5 `0d516efecae4c95b9baf2648b14c0a4f`。

## 2. 审核发现与已修复项

- **高优先级：报告将错网数写死为0。** `make_g1_report.py`现逐焊盘比较原理图快照，分开错网、未知脚、缺脚和重复脚异网，并绑定输入SHA。实际基线快照四项均0，但这只证明两个快照对应，不证明实时CAD、走线或DRC。
- **中优先级：同封装重叠不能全部自动豁免。** 新增不同网络内部包围盒重叠项；基线为0。包围盒是筛查，不能替代真实铜形状/层叠DRC。
- 修正“Lr未作为PCB器件放置”的错误描述；实际Lr已放置，仅T1–T4/CT仍是概念端子。
- **布局实质问题：U2远离功率管。** 原GH_DRV、GL_DRV端点距离81.48/75.61mm，自举HB/SW约62.45/61.22mm。重开读回后实测分别为6.00/4.41mm和2.97/3.10mm。实测未见跨器件焊盘包围盒碰撞或磁件区域侵入；尚未做courtyard/装配间距/走线验证。
- **重开读回暴露了快照比对口径错误（已修）。** `g1_pads.json` 由 `tmp_g1_probe/make_pads_json.py` 生成时把所有**器件焊盘** `Layer` 硬编码为 `1`，而真实重开读回把 J_IN/J_OUT 的 4 个通孔焊盘报成 `12`（多层）；另外 `POLYGON` 焊盘源是**绝对板坐标**，器件移动后整块平移，直接比字符串必然假红。`audit_driver_eco.py` 现在按「引脚号 + 网络 + 相对器件原点的形状 + 旋转 + 自由焊盘层」比身份，位置偏移按 **0.25 mil** 容差比较（本板实测最大重开漂移 0.112 mil，在 D_BT.2；真实改封装是整 mil 级）。`tools/test_g1_driver_eco_audit.py` 用平移、层差、形状改动、偏移超差四条锁住语义。

`audit_driver_eco.py --preview`只生成明确标为PREDICTED的`driver_eco_preview_report.json`，保留reopened_readback=false。真实重开读回成功后，无参数运行才可生成验收报告。没有走线，无ERC/DRC通过结论。

验证：网络错误/漏脚/重复异网回归及制造门禁合计26项检查通过。编辑器API保存成功与离线测试通过，均不等价于电路或制造放行。

## 3. DeepSeek状态

已形成具体审核与整改任务，首次调用因原密钥文件不存在而终止；没有发出API请求、没有模型回复。`deepseek/20261110_g1/status.json`如实记录。已向用户询问新密钥文件路径，不要求粘贴密钥。

运行器增加`--key-file`及环境变量入口，避免固定旧路径成为永久阻塞；未读取其他服务的密钥。恢复凭据后发送`next_tasks.md`，要求以节点和实际CAD增量交付，不接受伪造执行。

## 4. 当前G1/G2/G3与三个工作包

**A：G1原生PCB，最高优先级。** 候选重开读回与驱动短路铜已完成：7件移动已持久化，25条第1层铜线经按路径重开读回验收（`driver_route_report.json`；一条计划段被编辑器在 T 型节点拆成两段，按覆盖校验通过）。
剩余连接的冲突已解到“可落板”的一步：GH_DRV 墙把 C5.1 封在楔形里，单层无解，因此改走第 2 层——13 个 0.5/0.2 mm 过孔、13 段第 1 层短引线、11 段第 2 层走线，覆盖 HB（D_BT.1→C5.1）、VCC12（D_BT.2/ U2.1/ C103.1/ C104.1）、PGND（U2.9/ R19.2/ C103.2/ C104.2）、SW（U2.5/ C5.2/ R18.2）。离线检查（`route_driver_eco.py --check`）端点、同层/跨层净距、过孔对焊盘/走线/过孔全部通过，新网最紧净距 0.164 mm；QH.1-3 的 100 A 源极连接明确不属于这层信号增量，留给铜排/铺铜。**尚未落到板文件**：LCEDA API 桥接被上一轮第 2 层探针弹出的模态框卡死（详见 `docs/agent/EDA.md`），需先恢复会话才能执行 `driver_route.js` 并导出原生 DRC。原生 DRC 入口已备好并离线测试（`driver_drc.js` 调 `pcb_Drc.check(true, false, true)` 取原始数组，`run_driver_drc.py` 按 `--path` 开、`--destroy` 关并做 md5 守卫），桥接恢复后直接跑；尚未对活板执行过。下一最小交付仍是“已落板的剩余连接 + 原生DRC原始结果”，不是只有计划的绿色报告。

**B：G2磁件接口，同步推进。** 按现有自研Maxwell路线完成Lr及变压器几何/矩阵、DOT、绕组出口与工艺剖面。解决T1–T4/CT端子超出原包络、Lr9mm与40mm端距冲突。厂家回件不是G1停工理由，但24概念PAD不能直接转为制造实脚。实体绕组/磁芯、材料与损耗仍需要模型及实物证据。

**C：G3器件/制造/关断。** 当前真实原理图仍缺机械表中部分撬棒组和Cout阵列，应先做有位号/网络/封装的原生ECO，再集成PCB。保留R8双字段DNP；独立故障关断、SR单对VGS/换流与必要SOA证据不能由版图计数替代。

## 5. 后续路线与停止条件

近期：候选重开验收（已完成）→原边门极/自举真实布线（第一批 25 段已完成，剩余连接见 `driver_route_plan.json` 的 `remaining_connections`）→四组SR和Cout局部布局/回流→磁件实端子与电流铜路集成。

中期：G2磁件/高度/铜厚工艺收敛→同一CAD修订的ERC、DRC、Gerber/钻孔/BOM/层叠/DFM→真实G3审查。保持NOT_FOR_FAB，不能仅修改布尔值放行。

样机：先低能量启动和关断，再25A/50A/100A阶梯，记录效率、均流、纹波、热点和SR反向换流。100A热稳态成立后再安排120A或≤10mm，不把后续指标加入首版阻塞。

接口连续超时已停止同一路径的重复重试；保留失败证据和候选，下一轮先解决工具读取条件。DeepSeek凭据缺失不阻止本地CAD/网表审核；实体波形、磁件和制造审查缺失则不能伪造通过。
