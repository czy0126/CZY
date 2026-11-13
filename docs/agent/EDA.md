# 嘉立创 EDA、原生 ECO、KiCad CLI、D0 板

> 从 `CLAUDE.md` 拆出（2026-11-06）。**本文件不自动加载**。
> 家的分布与热区见 [`../../CLAUDE.md`](../../CLAUDE.md)，
> 一条一条的硬规则见 [`TRAP_INDEX.md`](TRAP_INDEX.md)。
> 旧引用里的「CLAUDE.md §小节名」按那里的表解析到本文件。

## 本文件目录

- 嘉立创 EDA（LCEDA Pro）
- 装配排除 ECO（R8，`hardware/dcx_main/gen/eco_r8_bom_pcb_inhibit.js`）
- 在 G1 候选板上重读清册（`hardware/dcx_main/g1/export_native_inventory.py`）
- 读活网表：`--path` 打开时所有制造导出都是 null（`hardware/dcx_main/g1/export_live_netlist.py`）
- 原生主板的取值 ECO（`tools/native_value_eco.py`）
- G2 OEM V5→V6 原生连通验收与超时隔离（2026-11-12）
- KiCad 10.0 CLI（headless，与 LCEDA 互补）
- D0 十路保护板的铜（已按 issue #36 延后）

## 嘉立创 EDA（LCEDA Pro）

- 版本 4.1.60.198f38ab，路径 `D:\lceda-pro`。CLI：
  `lceda-pro invoke --session <id> --ext-uuid eda --timeout <ms≤60000> --code "<async body>"`。
- headless 可做：建工程、放器件、建命名导线、导出网表/BOM（xlsx 二进制 base64 取回）。
- **"PCB 只能 GUI 做"已于 2026-11-09 更正**：`pcb_Document.importChanges` 返回 true 但导入
  0 个器件、`dmt_Pcb.createPcb('Board1')` 返回 undefined、`saveFileToFileSystem` 返回"路径不允许"，
  这三条仍然成立——但原生带网 PCB 可以用 PCB 图元 API 直接搭出来，见下面
  `### 原生 PCB 的 headless 构建（2026-11-09 已实跑）`。
  `pcb_PrimitiveComponent.create` 抛 `[object Object]` 是**参数形状错**（直接传了封装 item），
  按 `{libraryUuid, uuid}` 的形状调用能建件。
- `.eprj2` 是 SQLite；PCB 文档源格式是 `{json header}||{json data}` 行式记录，
  类型包括 DOCHEAD/CANVAS/LAYER/LAYER_PHYS/ACTIVE_LAYER/RULE_TEMPLATE/RULE/
  PRIMITIVE(仅显示)/SILK_OPTS/D3_ATTRIBUTE/PREFERENCE/PANELIZE。
- 中文厂商名经 CLI 文本通道会变 U+FFFD；必须走 xlsx 二进制 + base64。
- **原生工程保存**：`eda.sch_Document.save()` 会把 `.eprj2` 写回
  `%APP_PROJECT_DIR%` 工程目录。本项目已把 `Documents\LCEDA-Pro\config.json` 的
  `APP_PROJECT_DIR` 改到 **`D:\workshop\LCEDA-Pro\projects`**（C: 盘空间不足），
  保存路径随之变为 `D:\workshop\LCEDA-Pro\projects\DCX Main Board.eprj2`，再 `cp` 进
  `hardware/dcx_main/`。**改客户端配置后先确认实际落盘路径**，不要照旧找 C: 的副本。
  `dmt_Project` 没有任何 save 方法，`saveFileToFileSystem` 不可用。
  改图后必须同时重导 `gen/netlist_export_raw.json`（制造门槛读它），
  并重跑 `tools/d1_bom_coverage.py --write`、`tools/d1_fabrication_gate.py --write`。
  `main_board.svg` 现在导不出来，见下面 `getSvgFile` 那条。
- **只能用 `--path` 打开工程，绝不调 `dmt_Project.openProject(uuid)`**：后者会重新解析到
  库/云端副本，之后每次 `save()` 都返回 false、文件 mtime 不变。实测同一份编辑：
  按路径打开 → save true、文件 1572864→1576960 字节；调过 `openProject` → save false、mtime 不动。
- **`--path` 必须是绝对路径**：相对路径按**编辑器自己的 cwd** 解析，不是调用者的 cwd。
  失败是静默的——`open` 照样返回 sessionId、`return 1;` ping 照样答，之后每个 `eda` 体都在
  `getCurrentProjectInfo().data` 里找不到 PCB 而报 `PCB missing`（2026-11-10 为此连跑三次 DRC，
  收据里 `"path": "dcx_main_board_g1_kelvin.eprj2"` 是相对路径；改成绝对路径后同一份
  `driver_drc.js` 立刻返回结果）。`run_driver_drc.py` 现在在 `main()` 里 `args.board.resolve()`。
- **`save()` 是防抖的**：返回 true 后约 20 s 文件才变。判断"写进去了没有"只能看 size/mtime
  （`lceda_place_main_board.py --watch` 就是这么等的），true 本身不是证据。
- **`getCurrentProjectInfo()` 的 shape**：`{itemType, uuid, friendlyName, … , data}`。
  工程 uuid 在**信封**的 `info.uuid`；`data[0]` 是 `Board1`（`{itemType, name, schematic, pcb, parentProjectUuid}`），
  不是工程。按路径打开是异步的，刚 `open` 完 `data` 可能为空，要循环等到有 schematic page。
- **`otherProperty.Footprint` 会毒化整个文档**：`sch_PrimitiveComponent.modify()` 把这个 key
  搬进实例的 `footprint.uuid`——写封装**名字**进去就得到一个解析不了的引用，之后该文档
  **每次 save() 都 false**，而且 `sch_PrimitiveComponent.modify` 的 schema 里没有 `footprint` 字段，
  清不掉。`lib_Device.modify`/`lib_Device.create` 的所有封装关联形式在这个 build 里也全部失败
  （`footprintUuid` 抛 `[object Object]`、`{symbol, footprint}` 返回 false / null）。
- **保存与导出互斥**：磁件器件带不上封装时 `getNetlistFile()` 什么都不返回；
  一旦把封装注入已放置实例，文档又不能序列化。所以顺序固定：
  先放器件 → `--all … --watch` 等写盘 → `--netlist-ready` 在**内存**里注入封装 **uuid** → 导出。
  注入后不能再 save，也不会进 `.eprj2`（重开一个副本会看到 `footprint: {uuid:""}`）。
  导出只在**真工程路径**上有效，工程副本上 `getNetlistFile` 返回 undefined。
- **`getSvgFile` 在 83 个位号时超过 60 s invoke 上限**（实测两次 `REQUEST_TIMEOUT` 59750 ms），
  所以 `main_board.svg` 是**旧的**（还停在 78 个位号）。要在 GUI 里导或等 A1 收尾；
  不要把旧 SVG 当当前图的证据。
- **磁件符号的引脚号是逻辑端子名**（`PRI_A`/`SEC_A`/`CTAP`），不是厂商焊盘号：
  本仓库没有厂商端子图，编一个"1–5"就和真端子图分不出来了。`physical_pad` 因此全是 null，
  `physical_pad_map_verified` 全是 false；`magnetics_symbol_contract.py` 从
  `project_symbols.json` 的 `used_by` 派生 `native_symbol_present`，手改 JSON 会被 `main()` 判过期。
- **供应商回件审核报告只对当时那两份字节成立**：`magnetic_vendor_map_audit.py` 的输出带
  `input_sha256` 与 `contract.sha256`（合同 5 只磁件 / 24 逻辑端）。合同一旦重生成或手改，
  旧报告里的 `REVIEW_PACKAGE_COMPLETE_NOT_APPROVED` 就失效，必须重跑；不要拿旧 JSON 配新合同。
  `contract_entries()` 对重复 `(ref, logical_pin)` 直接抛错——字典合并会让期望端子数悄悄小于 24。
  **"合同冻结"本身也不再是信任前提**：审核前 `verify_contract_sources()` 用
  `magnetics_cad_contract.build()` 从 `design/v3/pcb/board_netlist.csv` +
  `design/v3/magnetics/winding_polarity.json` 重建合同，只逐端比对 `golden_net`/`polarity`；
  不一致 → `INVALID_PACKET`（退出码 2），报告仍带 `contract.sha256`。比较**有意忽略**
  `physical_pad`/`physical_pad_map_verified`/原生CAD字段——回件之后填真实焊盘是合法步骤，
  用整份 JSON 相等会堵死这条路。输入文件哈希另存 `contract_sources`。
- **17 个 BOM 外围在 `tools/main_board_schematic.py:PERIPHERALS`**，故意不进金网表：EN/RUN 默认电平、
  EN 滤波、每只 IC 的去耦在 SPICE 里不存在。网表比对把它们的 34 个焊盘记在
  `peripheral_pads_checked`，不混进 `pads_checked`（金网表 245）。新增/移动外围必须同时改 `SECTIONS`，
  否则 `test_every_placed_ref_sits_in_exactly_one_section` 红。外围网络名用**金网表里的名字**
  （U2.6=EN 叫 `RUN`，HI/LI 叫 `GD1`/`GD2`，`12V_P` 叫 `VCC12`），
  `test_every_peripheral_net_is_a_net_the_golden_netlist_already_uses` 锁住这一点。

### 装配排除 ECO（R8，`hardware/dcx_main/gen/eco_r8_bom_pcb_inhibit.js`）

第一份**可执行的**原生 ECO（不是计划文件）：把 EN 上拉 R8 的 `addIntoBom` / `addIntoPcb`
置 false。实跑记录在 `hardware/dcx_main/gen/r8_eco_run_2026-11-06.json`，
`tools/test_r8_eco_run_record.py` 八条锁住它（含"原生文件 sha 前后相同"与"交付文件里只有一条排除"）。

- **invoke 体共享 render 的全局作用域**：体里 `let info` 会留下来，同一 session 的下一次
  invoke 再声明就 `SYNTAX_ERROR: Identifier 'info' has already been declared`
  （第一次撞在 `tools/lceda_place_main_board.py` 的 `NETLIST_READY` 上）。而且**体的 `return`
  是整次 invoke 的返回值**，所以把两段脚本拼在一起时，前一段的 `return { injected }`
  会让后一段根本不执行（第二段静默不跑，看起来像"导出没结果"）。规矩：**每一段脚本各包一层
  `return await (async () => { … })();`**，操作者开关用 `globalThis.CZY_*` 读，不用新声明。
- **导出需要注入后"落定"一下**：五只磁件封装在内存里注入完**立刻**调
  `getNetlistFile()` 返回 undefined（实测两次，报的是 `NO FILE`）；等 **2.5 s** 再调就给出
  83 个器件的网表。这一步的失败长得像"封装没注入"，其实注入列表是齐的（`injected` 五项）。
- **守卫与保存互斥，所以分两相**：导出要五只空白磁件封装**在内存里**注入；注入之后文档
  不能再序列化，`save()` 返回 false。于是
  **phase 1 注入 + 校验引脚 + 绝不保存**（`CZY_R8_VERIFY_ONLY=true`，返回
  `PIN_MAP_VERIFIED_NO_SAVE` 与 attestation），
  **phase 2 干净 session + 凭 attestation 应用**（`CZY_APPLY_R8_DNP=true` +
  `CZY_R8_PIN_MAP_VERIFIED=<attestation>`）。
  **相位必须是声明的旗，不能从"导出成功"反推**：注入过的 session 在 CT/T1–T4 上同样能看到
  封装 uuid，等厂家端子图到位、封装是真的那天，"导出成功 ⇒ 这一相被注入过"就整个反了。
- **attestation 是 FNV-1a 32 位指纹 + 器件数**（`fnv1a32:69b8252c:n83`），绑住位号集合；
  改任一 `parts`/`inventory_fingerprint`/`r8_designator` 都会被拒，clean session 无法自证引脚
  （`pins_reverifiable_here: false`）。
- **导出会把被排除的件重新编号**：R8 在网表里出现为 **R6**，引脚原样（1=VCC12、2=RUN），
  `Add into BOM=no` / `Convert to PCB=no`，R7 不动。**rename 不是第二个缺陷**，别去"修"它；
  对回原件的键是**导出的 uid**（`gge67`），不是位号。
- **引脚只能从导出读，形状是 `components[*].pinInfoMap[pin].net`**，属性在
  `components[*].props`（`Designator`/`Add into BOM`/`Convert to PCB`）；顶层**没有** `nets` 表。
- **`save()` 约 14 ms 返回，文件约 20 s 后才变**：phase 2 的副本 2 355 200 → 2 363 392 字节
  （+8192），sha 换成 `e6732ca9…`；原生文件 2 355 200 / `11b444eb…` 前后一致（全部改动落在副本）。
  重开副本再跑得到 `ALREADY_DNP`，原语 id `c36641dcb5f791fe` 跨重开稳定。
- **冷启动楔子会复发**：`destroy` 全部 session、睡 8 s、开副本、再睡 15 s，仍可能撞上
  `REQUEST_TIMEOUT … 59750ms`（同一段体在别的 session 4–7 s 就返回）。只读的导出**在同一
  session 里重试**是有效的（第 1 次超时、第 2–3 次成功）；写相位不要靠重试，靠"改没改"的读回。
- **按路径打开时用文件主干做身份**：保存过的副本连开两次在本轮给出**同一个** `session_uuid`，
  而两份不同字节的副本给了不同的 —— 所以 uuid 随内容而变、不能当稳定身份；
  闸门仍是"文件主干 `dcx_main_board`" **或** 存储的 `14837d10…`，`identified_by` 记下来源。
- **关掉的/headless 的 session 会占着工程文件**：客户端进程没退干净时，仓库里那份
  `.eprj2` 对 `cp`/`git` 都是 `WinError 32`（另一个程序正在使用此文件）。这不是文件坏了，
  等后端进程退出即可；**不要为此去删工程或重启编辑器之外的进程**。

### 在 G1 候选板上重读清册（2026-11-10 已实跑）

`tools/native_inventory_bom_gate.py` 默认审计的是 **Nov 6 的主板快照**
（`hardware/dcx_main/gen/native_inventory_raw.json`），而当前交付板是 G1 候选。
重读用 `hardware/dcx_main/g1/export_native_inventory.py`：`--path` 只读打开
`dcx_main_board_g1_lr_repack.eprj2`（前后 sha256 必须不变），先**在同一 session** 设
`globalThis.CZY_EXPECTED_PROJECT`，再跑 `gen/read_native_inventory.js` 本体——
不复制第二份读取器，两个 `globalThis.CZY_*` 默认值保持不变，`docs/agent/COMMANDS.md`
里那条老命令仍然逐字节有效。

- **G1 的读数里没有位号 R8，`R6` 两个标志都是 false**——正是上面那条 rename，
  不是"R8 被删了"，也不是"R8 还开着"。`g1_native_inventory_raw.json` 是 83 个器件。
- **闸门按"注册库器件 + BOM/PCB 双 false + 唯一命中"解析改名**：
  `--inventory <capture> --out <report>` 会在位号查不到时走这条路，命中写进
  `r8_identified_by: double-dnp-designator-fallback` / `r8_capture_designator: R6`；
  改名但**有装**（任一标志 true）的一行匹配不上，照样 `missing native R8` fail closed。
- **默认候选没有改指向**：`tools/d1_fabrication_gate.py` 的 `real_r8_dnp` 决定要不要把
  网表里 R8（VCC12→RUN）从"无条件上拉"里排除，而 `gen/netlist_export_raw.json` 是 **ECO 前**
  的（有 R8、没有 R6）。让清册指向 G1 就等于拿"ECO 后清册"放行"ECO 前网表"，
  所以 G1 报告另存一份、只作读数证据，不参与放行判定。

### 读活网表：`--path` 打开时所有制造导出都是 null（2026-11-10 实测）

`hardware/dcx_main/g1/export_live_netlist.py` 要的是"同一个板子自己的活网表"，
但先测到一条硬边界——**`--path` 打开的工程，一个制造导出都拿不到**（同日逐个调用）：

| 调用 | 返回 |
|---|---|
| `sch_ManufactureData.getNetlistFile` | `null` |
| `sch_ManufactureData.getSimulationNetlistFile` | `null` |
| `sch_ManufactureData.getBomFile` | `null` |
| `sch_Net.getCurrentProjectAllNets()` / `getAllNets()` / `getAllNetsName()` | `[]`（**打开 P1 页面并等 2.5 s 之后仍是 `[]`**） |
| `sch_Netlist.getNetlist(...)` | `undefined`（传 `[]`、page uuid、page 对象都是） |

`gen/netlist_export_capture_2026-11-06.json` 的 provenance 写的是
`.probe_live_netlist.json`、session `D:/workshop/_eco_probe3.eprj2` —— 那次
`getNetlistFile(...)` **确实返回了网表**，而会话标记是磁盘上的绝对路径（`--path` 的形状）。
那份 probe 脚本没进仓库，所以**"当时也走 `--path`"是推断、不是实测**。能确定的是：
同一套加载路径**曾经导出成功**，今天全 `null`，原因未测出。所以不要写死成"API 不存在"，
也不要反复重试导出。

**能读的是图元库**（不是导出）：`eda.sch_PrimitiveWire` 每条线自带
`getState_Net()`（编辑器自己算的网名）+ `getState_Line()` 端点坐标；
`sch_PrimitiveComponent.getAllPinsByPrimitiveId()` 给出每个引脚的 schematic 坐标。
所以连通性可以**读**出来：

- 读取器 `hardware/dcx_main/gen/read_schematic_connectivity.js`（只读，不 `modify`/`save`/导出；
  `globalThis.CZY_*` 两个身份覆盖写法与清册读取器一致）。
- 重构 `tools/schematic_connectivity.py`：引脚坐标 → 落在同一点的所有线 → 该线的网名。
- 运行 `python hardware/dcx_main/g1/export_live_netlist.py`（两块板前后 sha256 必须不变）；
  `--check` 用已提交的 capture 重算，不开编辑器，CI 可跑。

**方法必须先自证**，否则只是我们自己的记账：同一套 `reconstruct()` 跑
`hardware/dcx_main/dcx_main_board.eprj2`，必须**逐脚**复现
`hardware/dcx_main/gen/netlist_export_raw.json`（Nov 6 编辑器自己导的那份）——
83 个位号、285 个引脚、连"编辑器导成 `""` 的 5 个脚"（`D_CT1..D_CT4` 的 2 脚、`U2` 的 2 脚）
也一致。复现不了就 `STOP`，不往下描述任何别的板子。

fail-closed 的三条（任一即 `ValueError`，不猜）：线没有网名；同一坐标上出现两个不同的网；
引脚落在某条**线段中间**而不是端点上。

G1 读数（`hardware/dcx_main/g1/g1_live_netlist.json`）：83 个位号，
与 Nov 6 导出**只差一个位号**——`R8` 只在旧导出里、`R6` 只在 G1 里，其余逐脚全同
（`diff.changed == []`），且 `R6` 的两个脚仍是 `VCC12` / `RUN`，与历史 `R8` 完全一致。
这填上了 `g1_schematic_pcb_alignment.json` 里 `current_schematic_netlist_reexported_from_same_board: false`
的空缺，也印证了清册那条"改名不改编线"。

**边界**：这是**原理图侧**。那条唯一的 EasyEDA `Netlist Error`（"PCB and schematic netlist
does not match"）是**原理图 vs PCB** 的差，本工具**没有**解决它，报告里写死
`schematic_versus_pcb_netlist_match_proven: false`；逐脚差见下一节（2026-11-10），仍不是
ERC/DRC 通过或投板批准。

### 原理图↔PCB 逐脚差异：对比器 PCB 列不可用，用 PCB 自己的网表导出（2026-11-10 已实跑）

`hardware/dcx_main/g1/read_import_changes.py`（对比器读数）、`probe_pcb_netlist_model.py`
（PCB 网表模型探针）、`export_pcb_netlist.py`（PCB 网表导出）、`tools/g1_import_changes_diff.py`
（配对报告）四个只读步骤，全部在候选副本上，前后 SHA 一致。

- **`sys_Tool.netlistComparison(schUuid, pcbUuid)` 能吃裸 uuid，但 PCB 列在本类板上恒空**：
  66 行（65 NET + 1 COMPONENT），**每一条 NET 的 `netlist2Name` 都是 `[]`**，连逐脚完全相同的
  47 个网也一样。传 `{projectUuid, documentUuid}` 对象返回 `undefined`；反序传参得到严格镜像
  （`net1: []`）；原理图自比、PCB 自比都是 0。**所以它不是差异清单**，只能证明"编辑器认为
  PCB 侧没有可配对的脚"。
- **PCB 网表并不空**：同一份副本上 `pcb_Net.getNetlist('JLCEDA')` 返回 **165 556 字符 / 5 531 行**，
  77 个器件、62 个有名网络、254 个已分配脚；`getAllPrimitivesByNet`（VOUT 23 / PGND 105 /
  SEC1_A 7）与 `getAllNetsName()`（65）都非空。注意它和 `getNetlistFile` 不同——后者在
  `--path` 打开的工程上恒 `null`（上一节）。
- **逐脚差异（`g1_import_changes_diff.json`）**：原理图 65 网 / 278 脚，PCB 62 网 / 254 脚；
  **只有 24 个脚不配对，全部是 CT(4) 与 T1–T4(各 5) 的逻辑端**；PCB 侧不配对脚 **0**；
  `PRI_12`/`PRI_23`/`PRI_34` 只因脚全在磁件上而只存在于原理图；47 个共有网逐脚完全相同；
  两侧都未分配的 5 个脚（`D_CT1–D_CT4`、`U2` 的 2 脚，即上一节那 5 个 `""`）完全一致。
  结论只到这里：**配平不等于实体端子/DOT**（见 D-07），DRC 只报条数、不能逐项映射。
- **`pinInfoMap[pin].net == ""` 是"未分配"，不是 `null`**；按 `None` 统计会得到 0。
- **一个 invoke 只问一个有把握的问题**：把 `getAllNetsName`+`getAllNets`+5×
  `getAllPrimitivesByNet`+3×`getNetlist` 捆在一个体里，**三次都 59 750 ms 超时**，整次结果全丢；
  `lceda-pro stop` + 重开后拆成每次一问，分别 9.6 s / 2 ms / 5 ms / 1 ms / 1.0–1.2 s。
  这也修正了 §嘉立创 EDA 里"只读导出在同一 session 重试有效"的旧说法：**本 case 重试 3 次全败，
  真正生效的是停服务重开**。
- **诊断入口**：`lceda-pro doctor`（endpoint/connected）、`lceda-pro session list`（本机
  7 个 headless 会话全 `closed` 仍不算可用）、`lceda-pro stop`（优雅停服务，四个 helper 进程一起退）。
  `sch_Netlist.getNetlist()` 不带参数在本 build 抛 `i is not iterable`（且已标 deprecated）。

### 原生主板的取值 ECO（`tools/native_value_eco.py`）

`hardware/dcx_main/placeholder_eco.json` 把 61 个占位按"主板能对它做什么"分类，
`value_eco.js` 只执行 `NATIVE_VALUE_EDIT` 一类——因为这是编辑器 API 唯一能完成的一类。
**批次已跑完（2026-11-05）**：37 行取值写进了唯一原生工程并落盘，
`ECO class` 从 **12 / 37 / 12** 变成 **49（ALREADY_CONFORMS）/ 0 / 12（NATIVE_DEVICE_CHANGE）**，
剩下 12 行（C5、Cin、Cout、Cr、D_BT、Lr、CT、R3 与 T1–T4）必须 GUI 换器件/封装。

- **`component_decision_register.json` 是生成物，手改会被静默回滚**：`tools/d1_sourcing_register.py`
  从 `design/v3/bom/bom_draft.csv` 取 `existing_value_or_rating`、从 `pin_footprint_review.csv`
  取引脚状态重写它。要改结论先改 `bom_draft.csv`（手工维护、无生成器）再重跑。
  这一条踩过一次：手改 34 行 `issues` 后差异消失得无影无踪。
  **改一行 BOM 要求要顺着五个 `--write` 重跑，顺序不能换**：`d1_sourcing_register.py`（读
  `bom_draft.csv` 的 `value_or_rating` → 寄存器的 `existing_value_or_rating`，`source` →
  `source_path`；**`basis` 列根本没人读**，改它只是给人看的）→ `d1_reference_kit.py`（两张
  seed）→ `export_d1_vendor_packets.py`（无旗时 `SystemExit("stale template: …")`）→
  `verify_vendor_candidate_matrix.py`（61 行候选矩阵）→ `placeholder_eco.py`。少跑一步的后果
  是供应商拿到旧数量，而 `ci_check --skip-tests` 只看得见 `remaining_dependencies` 这类视图，
  看不见这几张 CSV。
- **`--path` 打开的工程保存回它自己的路径，不是 `%APP_PROJECT_DIR%`**：上面那条
  "保存到 `D:\workshop\LCEDA-Pro\projects\...eprj2` 再 `cp` 进仓库"只对**按名字打开**的工程成立。
  这次按 `--path hardware/dcx_main/dcx_main_board.eprj2` 打开，`save()` 直接把仓库里那份
  从 2 338 816 写成 2 355 200 字节（防抖约 20 s），而 `projects` 里那份纹丝不动。
  当时盯着错的文件看，差点把成功的保存判成失败——**判据要盯被打开的那个路径**。
- **按路径打开时工程 uuid 不稳定**：同一个文件三次打开给出三个 uuid
  （`f7433cc3…`、`0054c1e0…`，探针副本又是另一个），所以身份判据只能是 `friendlyName`（文件主干）。
  `read_native_inventory.js` 里旧注释说"两次打开稳定"，结论对但理由错，已改。
- **`sch_PrimitiveComponent.modify(id, {otherProperty})` 整表替换**：只传部分键会把
  `LCSC Part Name`/`Datasheet`/`JLCPCB Part Class` 等厂家属性清空。必须传**完整的现有表**、
  只改 `Value`。原语 id 取 `getState_PrimitiveId`（`getState_Id`/`getState_Uuid` 也可能答，
  但本 build 上答的是它）。
- **写完必须用新句柄读回**：同一原语的 `getState_OtherProperty()` 是取句柄时的**快照**，
  在同一个 invoke 里 `modify()` 之后立刻读会读到旧值。实测一次 37 行的批次报了
  **37 个 `EDIT_FAILED`**，而重新 `getAll()` 一看 37 个值全对；单独的自检把这条钉死：
  把 R4 改回 `10kΩ` 后新句柄读到 `10kΩ`、写它的那个句柄仍读 `2.2Ω`。
  所以 `value_eco.js` 的校验是**第二遍**遍历新 `getAll()`，且拿"发出去的那张表"当期望值
  （`attribute_loss` 与它逐键比），不是拿写之前的快照比。
- **GBK 命令行带不了 `Ω`（U+03A9）**：`--code` 里出现字面 Ω 会被转成代理项并
  `UnicodeEncodeError`。`native_value_eco.render()` 用 `json.dumps(..., ensure_ascii=True)`
  把正文渲染成纯 ASCII（`\u03a9`），`test_the_body_is_pure_ascii_...` 锁住。
- **执行完之后计划文件就是"执行记录"，不能再按"等于现算的清单"判新鲜**：
  `build()` 现在为空（那 37 行已变 `ALREADY_CONFORMS`），若仍要求 plan == build()，
  一次成功的运行会把自己的记录判成过期。`stale_reason()` 因此接受两种状态：
  与 ECO 表一致（执行前），或**每一条编辑都等于落盘后主板的读数**（执行后）。
  `--write-plan` 在"记录非空且主板逐条匹配"时**拒绝**用空计划覆盖它。
- 核对链：`python tools/native_value_eco.py --check` 打印
  `executed record current: all 37 edits read back from the saved board`；
  原始读数在 `hardware/dcx_main/gen/native_inventory_raw.json`（**文件是整个 CLI 信封
  `{ok,value,logs,durationMs}`**，不是里面那个 `value`——写错会让 `placeholder_eco` 报
  `is not an inventory dump: None`）。

### 原生 PCB 的 headless 构建（2026-11-09 已实跑）

从原生原理图网表建原生 PCB **不需要 GUI**：`pcb_Document.importChanges` 与 `dmt_Pcb.createPcb`
都走不通，但 PCB 图元 API 能把板子逐件搭起来。下面每条都是实跑读数，不是计划。

- **单位与坐标系**：PCB API 的坐标单位是 **mil**；PCB 笛卡尔坐标 **Y 向上**。
  `pcb_MathPolygon.createPolygon` 的多边形源是 **SVG 约定 Y 向下** ⇒ 两个坐标系之间必须对 Y
  取负，否则板框会上下镜像。
- **放器件**：`eda.lib_Device.searchByProperties({supplierId:'C<LCSC号>'})`（或按 name 搜）拿
  `{libraryUuid, uuid}` 命中，再
  `eda.pcb_PrimitiveComponent.create({libraryUuid, uuid}, 1, x_mil, y_mil, 0, false)`；
  第 2 个参数是层（**1 = 顶**）。设计位号用 `setState_Designator`。
- **焊盘挂网**：`eda.pcb_PrimitivePad.modify(padId, {net:'NAME'})`，回读用 `getState_Net()`。
  网表读取用 `eda.pcb_Net.getAllNetsName()`；**没有** `pcb_Net.getAll()`。
- **对象没有 `getState()`**：PCB 图元只能逐字段 `getState_X()` / `getState_Y()` /
  `getState_PrimitiveId()` / `getState_PadNumber()` / `getState_Net()`；笼统 `obj.getState()`
  不是函数。
- **板框**：必须是**第 11 层（板框层）上的闭合折线**，用
  `pcb_MathPolygon.createPolygon([x, y, 'L', …])` + `pcb_PrimitivePolyline.create('', 11, polygon, 10, false)`。
  `pcb_PrimitiveLine.create` **只在第 1 层（铜）能用**，3/11/13 层一律报"无法找到图元…参数错误"。
- **铜线读写口径**：`pcb_PrimitiveLine.create(net, 1, x1, y1, x2, y2, width, false)` 的坐标是
  **mil、PCB 笛卡尔 Y 向上**（板面 Y 向下 ⇒ 取负），`width` 也是 **mil**（0.2 mm = 7.874）。
  读回字段是 `getState_StartX/StartY/EndX/EndY`，**没有** `getState_X1/Y1`（照抄焊盘命名会
  `EXECUTION_ERROR: getState_X1 is not a function`）。**保存时编辑器会重排折线**：T 型节点处把
  一条线拆成两段、重合段合并 ⇒ 验收不能逐段比对，要按「同网、同层、同线宽、共线且区间覆盖」
  判（`hardware/dcx_main/g1/route_driver_eco.py --verify`）。
- **文本图元**：`pcb_PrimitiveString.create` 在所有试过的层/字体上都失败（"无法找到文本图元"）
  ⇒ headless 画不出丝印/文档层文字；待锁区只能用**第 13 层（文档层）矩形**圈出，不能写字。
- **磁件封装放不进去**：
  `pcb_PrimitiveComponent.create({libraryType:'4', libraryUuid:'project', uuid})` 抛
  `Cannot destructure property 'libraryUuid' of 'i'`；直接传封装 item 抛 `Error: [object Object]`。
  项目库里查封装用 `eda.lib_Footprint.search('XFMR', 'project')`（**按 uuid 查返回 0 条**）。
- **保存会写回被打开的那个文件**：内存里做过封装注入的 session，之后任何 `save()`（或关闭时落盘）
  都会把被污染的工程写回打开的 `.eprj2` ⇒ 注入类实验**只能开副本**，绝不能打开仓库里那份真文件；
  每次实验后用 md5 确认真文件没变。
- **自由焊盘（不挂在器件上）能 headless 建**：
  `eda.pcb_PrimitivePad.create(layer, padNumber, x, y, rotation, pad, net, hole, holeOffsetX,
  holeOffsetY, holeRotation, metallization, padType, specialPad, solderMaskAndPasteMaskExpansion,
  heatWelding, primitiveLock)`——17 个位置参数，少传会抛 `[object Object]` 这类无信息错误。
  `pad` 形状是 **mil**：`['ELLIPSE', w, h]` / `['RECT', w, h, corner]` / `['OVAL', w, h]` /
  `['POLYGON', [x0, y0, 'L', …]]`；`layer 1` = 顶层；`rotation` 用 PCB 的笛卡尔角度。
  删用 `eda.pcb_PrimitivePad.delete([id…])`。磁件还没有厂商封装时，就用它把**带真网名的
  临时端子**放上板（G1 的 24 个设计自有焊盘就是这么来的）——它们是**占位，不是实体 PAD**。
- **组件→焊盘只有一条链**：`pcb_PrimitiveComponent.getAllPinsByPrimitiveId(id)`。焊盘对象上
  **没有** component 字段 ⇒ 要判"哪些焊盘是自由的"，先收集所有组件的 pad PrimitiveId 再做差集。
- **`getState_Polygon()` 是扁平数组**：返回 `{polygon: [x0, y0, 'L', x1, y0, x1, y1, x0, y1]}`，
  `'L'` 夹在数字中间。按 3 步长解析会读出垃圾（曾把 31.75 mm 的待锁区读成 31.0 / 69.0 / 107.0
  三个宽度）⇒ 过滤出数字后按 `nums[0::2]` / `nums[1::2]` 配对。
- **`doc api --class-name` 用 `PCB_` 大写的类名**（`PCB_PrimitivePad`、`PCB_PrimitivePolyline`、
  `PCB_PrimitiveComponent`、`IPCB_PrimitivePad`）；写成 `pcb_PrimitivePad` 会报"eda 命名空间下
  不存在类型"。invoke 正文里才是小写 `eda.pcb_PrimitivePad`。`--timeout` 只收 1…60000 的整数。
- **实测规模（2026-11-09 终值）**：原生原理图 **83** 器件 → PCB **77** 器件（T1–T4/CT 无厂商封装、
  R8 双字段 DNP 排除）、**65** 个网、**299** 个焊盘（275 封装 + 24 设计自有临时焊盘）、
  **14** 条折线（1 条板框 @第 11 层 + 5 个待锁区 + 8 个 DOT 标记 @第 13 层）；
  每只网都有焊盘、逐焊盘网络与编辑器网表**零不符**。焊盘旋转必须从 `getState_Rotation()` 读，
  不能默认 0（本板有 80 只焊盘是 90/180/−90°）。

- **重开读回与旧快照不是同一口径**：`g1_pads.json` 生成器把所有**器件焊盘** `Layer` 硬编码成
  `1`，真实重开读回把通孔焊盘（J_IN/J_OUT）报成 `12`；`POLYGON` 焊盘源又是**绝对板坐标**，
  器件一移整块平移。逐焊盘比对必须按「引脚号 + 网络 + 相对器件原点的形状 + 旋转 + 自由焊盘层」
  做身份，位置偏移给约 0.25 mil 容差（编辑器重开会重新舍入）——直接比原始字段会把正常重开判成
  改封装。见 `hardware/dcx_main/g1/audit_driver_eco.py` 与 `tools/test_g1_driver_eco_audit.py`。

- **建板脚本必须在仓库里**：G1 的板原先由 `tmp_g1_probe/g1_build.py` 建（未跟踪），30 个控制区
  器件的摆放只存在于临时脚本和板上，仓库无法重建那块板。现在
  `hardware/dcx_main/g1/build_g1_board.py` + `g1_placement.json`（77 行，mm / Y 向下）是唯一
  摆放，slice 正文只由它生成，叠 `native_inventory_raw.json` 与 `netlist_export_raw.json`；
  `--check` 对读回逐件比对（0.25 mil 容差），`tools/test_g1_build_board.py` 锁住"提交的摆放
  = 提交的读回所推出的摆放"。24 个自由端子焊盘同样在覆盖内——坐标由已提交的端子包
  `design_owned_G1_pads_24plus2.csv` 加板自身的 `tbd_zones` 算出，按位置回对（脚号会跨核重复）。
  **还没覆盖**板框/待锁区/DOT 折线与走线（`frame_js()` 能生成，但没有对着活板的回执）。
- **两极电流路已落到 `_power_rails` 候选**：`route_power_rails.py` 从已读回的焊盘画出 VOUT
  （4 个 CTAP + Cout.1 + J_OUT.1，经两过孔下第 2 层跨过 PGND）与 PGND（8 个 `SR*.3` 源极
  大焊盘 + Cout.2 + J_OUT.2），`--check` 把**已有的原边驱动铜一起**放进同一套净距/端点检查
  （只查两极会漏跨线）。焊盘引线只能 1.0 mm——2.0 mm 过不了源极大焊盘与相邻 SEC/漏极焊盘之间
  0.856 mm 的净距；`tools/test_g1_power_rails.py` 有用例证明检查不是空转。CTAP 正下方 7 mm
  是同组 `SEC_B` 焊盘，必须横移 2 mm 再下行。`apply_power_rails.py` 从 `_driver_route` 复制
  出 `_power_rails`（**只开副本**）、20 s settle + ping 后 invoke，重开读回 84 线/15 过孔、
  覆盖与摆放漂移全空（`power_rails_report.json`；84 是 50+34，编辑器在 T 型节点拆线）。
  **DRC 未在这个新候选上重跑**，仍是 `NOT_FOR_FAB`。
- **CS1/CS2 两条 CT 检测网已落到 `_kelvin` 候选**：`route_kelvin.py` 用同一套检查、同样把
  已有驱动铜与两极一起放进计划（0.3 mm 检测线宽，不是电流额定）。CS1 横穿 CS2 的 y=65
  走廊 ⇒ 三只 0.3/0.505 mm 过孔绕到第 2 层（`(106.2,56)`、`(110.1,66.5)`、`(119,69)`），
  CS2 全第 1 层。`apply_kelvin.py` 从 `_power_rails` 复制（**只开副本**），重开读回
  98 线/18 过孔、覆盖与漂移全空（`kelvin_report.json`）；原生 DRC 在该候选上重跑：
  0 物理错误 / 206 连接错误 / 1 条既有网表错误，不是通过。SR 门极/漏极的 Kelvin 对仍未布——
  8 条 `GA*`/`GB*` 在当前摆放下第 1 层出不来（SR 的 PGND 源极引线横在门极电阻与门极焊盘之间，
  焊盘排上方只有 0.554 mm 的缝），理由与读数在 `hardware/dcx_main/g1/README.md` §5 驱动对。
  **写入协议收进 `apply_increment.py`**：`apply_power_rails.py` / `apply_kelvin.py` 只差
  模块、父候选与回执前缀。该编辑器保存时**合并共线重叠的线** ⇒ 计划里不要给一条长横穿再补
  一段共线支线，回来的读回线是一整条，`_covered` 要求两个读回端点都落在计划段内，会判缺线。
- **无网焊盘也是铜**：`D_CT1–4.2`、`U2.2` 五只焊盘在原理图里没有网络名，但读回里是真实铜。
  `route_driver_eco.load_pads()` 第一版把它们跳过了，于是 CS1/CS2 直接竖下、从 D_CT1.2 /
  D_CT2.2 中间穿过时离线 `--check` 仍报 0 问题，而原生 DRC 报两条 `SMD Pad to Track`
  （0 mil，规则 ≥ 6 mil）。现在 `load_pads` 按 `net=""` 保留它们（永远不等于任何计划网），
  `tools/test_g1_driver_route_plan.py` 用一条穿 D_CT1.2 的假线段锁住。离线检查绿不等于
  DRC 绿：只有原生 DRC 是净距的门，离线检查器只是它的快速近似。
- **评审图必须写明它画的是哪个板文件**：G1 目录里现在同时有基板
  `dcx_main_board_g1.eprj2`（无铜、无走线、无 DRC）与候选 `..._driver_eco` /
  `..._driver_route` / `..._power_rails` / `..._kelvin`（`_driver_route` 读回 50 条铜线 /
  13 个过孔，另有原生 DRC raw `driver_drc_raw.json`；数以 `driver_route_report.json` 为准）。
  图下只写"无铜、无走线、无 DRC"
  会被读成对整块板说的 ⇒ `make_g1_layout_svg.py` 把 `BOARD` 常量写进 caption，
  **提交的 SVG 必须等于提交的 `g1_pads.json` 现渲染结果**（`tools/test_g1_layout_svg.py`
  逐字节锁住；`render()` 与写文件分开是这个测试的前提）。待锁区只有 CT+T1–T4 五块磁芯本体，
  Lr 是已放器件、没有待锁区。

交付物：`hardware/dcx_main/g1/dcx_main_board_g1.eprj2`（G1 原生带网 PCB，非投板）。

### EDA 桥接的卡死与恢复（2026-11-10 实测）

**签名**（所有触发共用同一种死法）：`return 1;` 这类不触达 `eda` 命名空间的 body 仍在约 1 ms
返回；任何真实 API body（哪怕只是 `getCurrentProjectInfo()`）一律 `REQUEST_TIMEOUT` 59750 ms
（budget 60000）；**新开 session 也一样**（`open` 仍返回 sessionId，durationMs 约 2 s）
⇒ 卡住的是**共享的主进程 render**，换 session 不解。

已确认的三个触发（最早的归因"可见 `#32770` 模态框"只是同一种卡死的一个实例，不是原因）：

| 触发 | 证据 | 对策 |
|---|---|---|
| `open` 后约 20 s 内就发真实 `eda` body | 四次冷启动：1–3 s 发 → 永久卡死；等 20 s 发 → 同一 body 3 ms 返回 | 固定 `SETTLE_S = 20`，先打 `return 1;` 探活 |
| 带着**未保存图元**的 session 被 `close --destroy` | 关闭后整机卡死 | body 末尾先 `save()` 再等过防抖（约 20 s）才关 |
| 会话里没有打开的 PCB 文档就调 `pcb_Layer` / `pcb_Drc` | `EXECUTION_ERROR: Error: 指定的参数信息在对应的会话中没有找到`（不是卡死） | 先 `dmt_EditorControl.openDocument(board.pcb.uuid)` 再等 1 s |

恢复只有一条路：`lceda-pro stop` → 重新 `open --path` → 等 20 s → `return 1;` 探活 → 真实 body。
`return 1;` 单独成功**不足以**判活，必须再打一次只读 API（`probe_alive.py` 会返回
`{"ok":true,"value":1}`，而 `probe_open_document.py` 仍 59750 ms 超时）。不要用 PowerShell /
Python ctypes 等 Win32 互操作去关窗口——用户规则禁 PowerShell，绕过去等于违约。

脚本侧另有一个假死：`subprocess.run(capture_output=True)` 会被分离的 app 继承的管道挂住，
永不返回；用文件重定向的 `Popen` + `wait(timeout)` + `kill()`（见 `run_driver_drc.py`）。

判"写进去了"只能看被打开路径的 size/mtime：`save()` 约 20–30 s 后才落盘，落盘可能落在下一次
读之前，让 md5 守卫报一次假的"变了"——对静止的板重跑一次得到 `unchanged: true` 即可，
不要当成 DRC 写盘。

规则值也要现读，不要按"嘉立创能力"记忆写：`pcb_Drc.getCurrentRuleConfiguration()`（需先打开
PCB 文档）返回板子自带的全表；生产入口是 `run_driver_drc.py --rules`（同一套 open/settle/ping/
close 协议，只读、不保存，输出 `driver_rules_raw.json`）。G1 的 `hardware/dcx_main/g1/driver_rules_raw.json`
里内径 0.3–6.3 mm、外径 0.5–10 mm、Track/Via 间距 0.152 mm（1 oz 表），0.2 mm 钻孔会被 DRC 判 13 条
`Via Size`。编辑器把 mil **截断**到 0.1（0.5 mm → 19.6 mil、0.3 mm → 11.8 mil），所以贴着规则
下限的尺寸要往上留 0.1 mil（外径写 0.505 mm 才落到 19.8 mil）。

## G2 OEM V5→V6 原生连通验收与超时隔离（2026-11-12）

- V5 源头是已保存、关闭、重开并运行原生 DRC 的真实 16×5 OEM PCB：`g2_t530_oem_v5_vcc12s_c111_c112_drc_delta.json` 记录 Connection **173→172**、Netlist **1**、Physical **0**。新增强制 `confirm_island_joins()`：只有目标 `C111.1` 与 `C112.1` 在**实际读回的铜岛图中合并**才认可，不能只看 DRC 项数下降；反例测试会把未经连接的源板拒绝。
- 下一单独控制网候选 `route_t530_oem_v6_ocm_one_real_island_join.py --check`：V5 实际读回中 `OCM R17.2` 与 `C11.2` 位于不同铜岛；0.15 mm 顶层三段走线在 y=63.4 mm 的预扫描中未发现异网/磁芯区域冲突。**此时只是几何计划，不等于已保存的 PCB 铜线。**
- 首次 V6 `--apply` 取得原生 open/ping，但写入时返回 `REQUEST_TIMEOUT`（59750 ms）。该次实际候选路径与 V5 父文件在异常后 **SHA256 相同** (`6635ddd9c7d0b48f1b6189f2989045101d4df17d4ff1a3f38d36a360c0b38863`)，未得到可核验的保存新铜或原生 DRC 下降。其日志回执应保留，**V6 副本绝不再次执行 `--apply`**；如果主进程仍卡死，先核实 render 是否健康，修复进程状态后从冻结 V5 建立**另一个全新路径**的后续试验。
- 代码已补 `open_board` **真实 readback API 探活**（而非只信 `return 1;`），并核对打开板的 77/443/400/90/65 件/焊盘/线/孔/网计数；真实 API 超时/对象数漂移即拒绝任何写入。未来任一后续批次仍需原生保存→防抖落盘→关闭→只读重开→已验证铜面连续→真实 DRC Connection 下降且 Physical 不增加，不能把独立几何筛查替代 EDA 或制造签核。
- **V7 独立恢复实验实测**：通过 `lceda-pro session list` 核实仅有已关闭的 headless 会话，`lceda-pro stop` 成功，然后用唯一未覆盖的 V7 路径从相同冻结 V5 复制。重启后的新 renderId=1，open 14.097s、ping 2ms **成功**；紧随其后的真实 native readback probe 再次 `REQUEST_TIMEOUT` 59750ms。增强守卫生效，没有创建新铜或调用保存，V7 副本和 V5 父 SHA256 依然相同。原始 open/ping/probe/close 与源锁定 route_plan 均在 `hardware/dcx_main/g2/g2_t530_oem_v7_ocm_r17_c11_*`。不能再对同一 V7 运行 `--apply`。
- **停止无效重试的条件**：V6 写入超时，V7 重启后的首次真实只读 API 同样超时，证明根因尚未解决。恢复下一阶段先独立验证：已打开 PCB document、真实 API 最小只读请求在正常时限内完成、完整 77/443/400/90/65 readback、GUI 端无挂起 render/模态对话框，然后**再**生成唯一新副本。未取得这四项不得反复 V8/V9 或降低 DRC/安全门槛。
- 仍未取得 72 颗正式原理图/封装的同版匹配、100 A 双极母线和端子、五磁件供应商 24 个 PAD/DOT、D0 十路实物失电与故障保护；V5/V6/V7 一律 `NOT_FOR_FAB`。

## G2 V8：保留可见 GUI 后的原生写入恢复（2026-11-12 实跑）

- **真实阻塞不在铜线规划，而在被关闭的 GUI 与未激活的 PCB 文档**：早期 headless V6 真实写入超时、V7 真实读回超时，不可重新对这两份副本写入。Windows 交互用户任务 ChatGPT-CZY-EasyEDA-Visible-20261112 拉起真实可见窗口，使用绝对路径及 --headless false。后续通过现存 sessionId 直接调用 API：先 getCurrentProjectInfo 确认工程，再 dmt_EditorControl.openDocument(pcb.uuid) 激活，再 read_driver_route.js 读回。不要以 return 1 ping 作为真实文档可用证据，**不得因为只读检查失败擅自关闭/停止现有可见 GUI**。
- **V5 真实 readback + DRC**：会话 alive 时，openDocument 返回正常（约 7.4 s）；原生 77 components / 443 pads / 400 lines / 90 vias / 65 nets 完整读回；原生 DRC Connection=172，Netlist=1，Physical=0；原版源 SHA256 为 6635ddd9c7d0b48f1b6189f2989045101d4df17d4ff1a3f38d36a360c0b38863，检查前后未变。
- **V8 单独新副本，已真实写入而不是计划**：route_t530_oem_v8_gui_real_ocm.py --apply 绑定唯一可见 V8 工程，确认 V5 原始哈希及原生 77/443/400/90/65，确认 OCM 的 R17.2 与 C11.2 原本属于不同铜岛；写入前建立只允许一次的 attempt 回执。随后经 pcb_PrimitiveLine.create 真实新增 3 段 0.15 mm 顶层 OCM 铜，pcb_Document.save() 返回 true，等待防抖后独立 V8 .eprj2 源 SHA256 改为 058e67293932ab7b6b46efd8200dc3f7642a03166814829f23b2385592123b3d。V5 仍原字节。--verify 在**同一个仍然打开的可见 V8 GUI** 实读 77/443/403/90/65，验证铜岛合并、旧铜完整覆盖、原生 DRC Connection 172→170 / Netlist 1 / Physical 0；原生证据为 g2_t530_oem_v8_gui_ocm_verification.json。**这不是关闭重开的独立读回，不能声称那一步已完成。**
- V5 与 V8 界面保持可见且会话 alive，禁止对 V8 重复 --apply，也不得执行 lceda-pro stop 或 session close --destroy。需要下一次正式变更，必须从已存版再建不覆盖的新文件并进行图元/DRC 实验。
- **Cout 真正器件库仍未配平**：可见 GUI 中系统库 lib_Device.search(T530X477M006ATE004)、lib_Device.search(C2158170)、lib_Device.searchByProperties({supplierId:C2158170}) 均无命中；通用 7343 类型封装不代表匹配厂家 Table2 的 Density-B 双焊盘尺寸、极性或 72 个原理图实例。当前 144 裸焊盘仍不是 72 个真实器件，100A 双极铜排、磁件 24 物理 PAD/DOT 与 D0 实物故障关断均未验收，保持 NOT_FOR_FAB。


### P0-A：已做的原生 KEMET 封装试验（沿用可见 V9，2026-11-12）

- 只在现有 V9 可见嘉立创窗口的内部标签，使用 G1_R34_REC10K_v3_TEST 试验库生成 X1 / 7343-43 Density-B 试验封装（UUID c9bdf53e779d4dd6a2eee1e6cecd4462），原生创建 PAD 1（右侧正极）与 PAD 2（左侧负极）。采用 KEMET 2026 年 Table 2 的 L=2.37 mm、W=2.43 mm、S=3.87 mm，端子中心 x=±3.12 mm。封装 API 的 pcb_Document.save() 返回 true；本次没有跨编辑器独立重开验收。
- 原生封装源为 hardware/dcx_main/g2/T530X477M006ATE004_X1_DENSITY_B_NATIVE_FOOTPRINT_NOT_FOR_FAB.efoo，证据为 t530_x1_density_b_library_pilot.json，测试为 tools/test_g2_t530_native_footprint.py。实际保存源中两个 PAD 记录均为矩形、顶层，且尺寸/坐标与原厂规划脚位在 mil 量化误差内一致。
- 重要限制：PCB 上通过 footprint search-item、简单库 UUID、带 numeric type 的 PCB_PrimitiveComponent.create 仍不能实例化此自制封装，三种均失败，V9 PCB 保持原 77 器件、443 焊盘；还需真正建立 device / symbol / footprint 关联、补足 courtyard / 丝印、完成 72 位号匹配和厂家审查。**当前封装不准用于正式下单生产**。
- 用户要求所有后续 EDA 工作优先沿用已经打开的 V5、V8、V9 窗口及其内部标签，不允许每一步重新 open GUI；不得自行关闭、重启或 stop 现有会话。只有确有安全隔离必要且现有会话无法复用时才单独处理新会话。


### P0-A：V9 72 颗真实 T530 原生 PCB 器件已验收（2026-11-12）

- **解决器件放置的根因**：先以 lib_Device.create 将已保存 T530 X1 Density-B native footprint 和系统 CAP symbol 真实关联成试验库 Device（UUID 903d14a6c07f4df992b7da8bfe2d4952），再以完整 lib_Device.search 返回值调用 pcb_PrimitiveComponent.create；单给 footprint 的三种参数都是前轮历史失败。这一流程在已打开的 V9 GUI 内成功放置 72 个 CHB01..CHB72，并经 pcb_PrimitivePad.modify 分别将真实编号 1=VOUT、2=PGND 连接，检查坐标完全重合后删除原有 144 个 CHBxx_N/P 裸焊盘。未增加额外嘉立创 GUI 窗口。
- **真实原生独立读回**：149 个器件（原 77 + 新 72）、443 焊盘（原 299 + 新 144）、403 铜线、90 过孔、65 网络；每颗 CHB 的两个数字焊盘原生网络都正确，原有 144 个裸焊盘计数归零。g2_v9_real_t530_72_checkpoint_NOT_FOR_FAB.json 记录逐位号验证、g2_v9_chb_*_native_NOT_FOR_FAB.json 记录每个可复核小批次及首次 CHB03 native 0.1mil 双坐标量化故障恢复（原有 0.06mil 二维欧氏容差过小，改为 0.11mil）。
- **真实保存**：调用 pcb_Document.save() 返回 true，等待写盘后，最新二进制 dcx_main_board_g2_T530_OEM_DENSITY_B_V9_REAL_72_COMPONENT_TRIAL_NOT_FOR_FAB.eprj2 SHA256 为 b4b09841247ae9c15bad1e3de6acde44f47bd907ec08ed5a4077138e6d459960，V8 原版未变。原生 DRC Connection=170、Netlist=1、Physical=0；记录在 g2_v9_real_t530_72_native_drc.json。**这不是完整消除 DRC**。
- 库资源保留有实际二焊盘 .efoo 原生源、CAP 两引脚 .esym 原生源及 t530_x1_real_device_association_NOT_FOR_FAB.json 器件符号/封装关联可追溯。**仍未在同版本原理图添加并连接 72 个 CAP 符号**，现有 CAP 符号未显式标正负极，丝印、courtyard 及厂家最终生产 land signoff 均未做；100A VOUT/PGND 完整主铜、磁件 24 物理 PAD/DOT、D0 保护实测及全部剩余 DRC 也未闭环，因此保持 NOT_FOR_FAB。


### G2 V9 Cout 同版真实原理图与 PCB 验证（2026-11-12）

- 保留全部可见嘉立创 EDA V5 / V8 / V9 窗口；只在原 V9 内部打开原理图标签页。在原生 Schematic1 中创建 Cout 第二页 COUT_T530_72，UUID 4de189e79beba629，第一页 P1 保持原有 83 件、280 条线（临时 CHB01 探针已删除）。第二页通过原生 API 新增 72 个 CHB01–CHB72 关联库器件符号及 144 条网线，脚 1=VOUT、脚 2=PGND。g2_v9_sch_cout72_native_checkpoint_NOT_FOR_FAB.json 原生读回 72/72 符号、144 条线、无缺失；批次见 g2_v9_sch_chb_*_NOT_FOR_FAB.json。
- 原生 sch_Document.save() 各页返回 true，PCB pcb_Document.save() 返回 true。之后逐一跨页比对 72 个原理图器件和 72 个 PCB 器件的 1、2 脚编号、PCB 1=VOUT 2=PGND，结果绑定最新 eprj2 SHA256 598e896935093e3c7c86bb18258c3e00c11edf1005c13fd0c885cb33085c6ce9，见 g2_v9_native_72_cout_schematic_pcb_pin_parity_NOT_FOR_FAB.json。只能说明 Cout 72 颗脚号/网络匹配，不代表其他 77 个器件都已配平。
- 同版原生 DRC（g2_v9_schematic_cap72_native_drc.json）：Connection 170 / Netlist 1 / Physical 0；未解决 100 A VOUT/PGND 主铜路、磁件 24 物理 PAD/DOT、D0 保护及投板。保持 NOT_FOR_FAB。后续不再重复打开新的 EDA GUI 窗口。


### G2 V9 真实 VOUT 变压器输出至 Cout 铜岛馈电试验（2026-11-12）

- 以新 V9 已保存的双页原理图与 72 个真实 T530 PCB 器件为基准，原生 readback 显示 VOUT 分成两个独立实际铜岛：四个变压器 CTAP 裸物理焊盘所在的源铜岛，以及 72 个 Cout 正极和负载输出端所在的阵列铜岛。直接基于 V9 443 焊盘 / 403 铜线 / 90 孔原生数据预扫对异网的几何间隙，沿 x=37、75、151 mm、y=20→94 mm 在底层布三条 1.6mm 铜线，并在三个 CTAP 源头放置直径 1.0mm / 钻孔 0.4mm 金属化孔；x=113mm 路径因异网 pad/trace 撞线未写入。plan: g2_v9_vout_source_bottom_feeder_plan_NOT_FOR_FAB.json。操作全部使用持续可见的 V9 原生编辑器窗口，没有新开、关闭或重启 EDA GUI。
- 本次 native PCB API 实际创建 3 个过孔和 3 条馈线（原生重合线自动拆段，实际总线数 403→407、过孔 90→93），pcb_Document.save() 返回 true，并经原生 PCB 再读回确认 149 器件 / 443 焊盘 / 407 线 / 93 孔 / 65 网；VOUT 的**源 CTAP 与 Cout 正极不再分离**，实际铜岛几何筛查由 2→1。同一文件真实 EDA DRC Connection 170→168、Netlist 1、Physical 0，见 g2_v9_vout_source_bottom_feeder_verified_NOT_FOR_FAB.json，最新 V9 源 SHA256 d26197ca04d986d010e9a6af096a6b71edbb188e1b076c41e1ff8e21ce0a43a2。
- **必须严守功率额定界限**：这三条 1.6mm PCB 铜线、3 个 0.4mm 钻孔过孔和既有 1.6mm Cout 收集母线仅证明实际连通，*绝不等于 100A 电流容量*，不存在温升、via 金属孔壁、并联均流、板厚铜厚/环境温度、金属接触/螺栓孔、底层叠层绝缘验证，不能发布制造 Gerber。剩余 PGND 仍有 39 个独立几何铜岛，多条逻辑网仍开路。继续需要重新设计 VOUT/PGND 两极成体系的实质载流铜结构；当前保持 NOT_FOR_FAB，不为形式 DRC 数字宣称完成。

### G2 V9 跨进程独立重开与源锁定只读审核（2026-11-12）

- `audit_v9_independent_reopen.py` 使用**已保存 V9 的独立逐字节副本**，在另一个可见 GUI 会话只读打开，逐项核查 149/443/407/93/65、72颗 CHB01–72 真实封装脚1=VOUT/脚2=PGND、COUT_T530_72 原理图72件/144线、实际 VOUT CTAP+电容一铜岛；相关检查已经运行，但该次**独立会话的原生DRC读取失败**，回执 `g2_v9_independent_gui_reopen_verified_NOT_FOR_FAB.json` 必须保留 `INDEPENDENT_REOPEN_NOT_VERIFIED_NOT_FOR_FAB`，绝不可当全部通过。原始V9和V8字节、原有V5/V8/V9三个可见窗口均保持不变；仅新增验证会话已关闭。失败的副本不能再次作为单步施工目标。
- 使用既有 V9 可见会话原生 API 对同一保存文件重新执行只读 DRC，得 **Connection 168 / Netlist 1**，来源 SHA 未变，原始原生DRC回执 `g2_v9_live_drc_readonly_followup_NOT_FOR_FAB.json`。此结果证明该原工程编辑器DRC可以运行，**不能**弥补独立会话DRC失败，也不证明整板无断线。保存的 native PCB 读取 `g2_v9_live_native_full_readback_20261112_NOT_FOR_FAB.json` 用于100A铜排机械覆叠而非额定证明。
- **第二次独立新副本真正完成所有只读验收**：针对首次失败时先切到 SCH 再切回 PCB 运行 DRC 的顺序，V2 改为**原生 PCB 图元→DRC→72颗原理图**，所有 API 调用成功。唯一新会话实际 readback **149/443/407/93/65**、72颗原生PIN1/PIN2 与一份COUT_T530_72第二页72器件/144线、VOUT一个铜岛，**原生DRC在独立会话返回168 Connection/1 Netlist**（调用耗时13.672s）。SHA前后完全一致，旧三GUI仍alive，新验证GUI已关闭，`g2_v9_independent_gui_reopen_v2_verified_NOT_FOR_FAB.json` 的状态是 `INDEPENDENT_NATIVE_GUI_REOPEN_VERIFIED_NOT_FOR_FAB`。历史V1失败回执保持原样不可覆盖。V2只证明可独立重开和当前DRC可执行，**168/1不合格、无100A资格**。
- 原生两焊盘 `.efoo` 与 CAP `.esym` 在默认 Windows `core.autocrlf` 下会变为CRLF而不改变电路图元；`-text` Git属性和 LF 正规化SHA 校验解决平台误报，但真正内容篡改仍然触发失败。完整72颗的原生器件与原理图已存在，不应再重复添加，未闭合的是其他原理图/PCB网表和真正100A双极实体载流连接。保持 `NOT_FOR_FAB`。

### G2 V11：八路SR栅极连接真实修补并经独立 GUI 重开（2026-11-13）

- 在单独分支复制源锁定、已独立重开DRC的V10真二进制（SHA `8dede88bf7b3cea52ff6f752b6ca573f7a3b9e7c7a3f665ca071dae8376f8c0c`）作为新V11，**不修改现有V5/V8/V9/V10用户窗口**。V10真实149/443/435/93/65，DRC=165 Connection/1 Netlist。`g2_v11_eight_sr_gate_escape.py` 基于真实图元为GA1–GA4、GB1–GB4的8条门极网提出**8段PGND纵线各移0.5mm**，32段新Native走线（8段新PGND纵线、24段0.15mm门极信号），全局几何异网名义间距0.18mm，离线全网预检查0异网冲突；每路门极原2铜岛→1，PGND 37岛保持。
- 原生 `pcb_PrimitiveLine.delete(8 ids)` 确认八段旧铜均消失，32次真实 `pcb_PrimitiveLine.create` 全部返回原生UUID，编辑器在PGND纵线与横向母线相交时自动将另**9段旧横线拆分为15段**，真实465线，不是简单 `435−8+32=459`。最初写入脚本因此按459判断失败并停止，并**未盲目重复写入**；实时只读盘点确认旧8段全消失、新32段全存在、编辑器原生 DRC=149 Connection/1 Netlist（不新增其他物理错误）。编辑器随后自动持久化V11，SHA `d90ca22079ad7245e8c3904eb8369da58c705ae39b56574bf7843dad34cad89b`；脚本现已修订预期465并保留首次历史失败回执。
- **独立保存文件重开真的通过**：`g2_v11_independent_native_reopen.py` 在另一个**新会话**对拷贝独立读回149/443/465/93/65、实际八路门极闭合和PGND不恶化、旧8线消失/新32线UUID存在、72颗T530 PIN1 VOUT/PIN2 PGND及原生原理图第二页72件144线；按`PCB→DRC→SCH`顺序执行真实嘉立创DRC，**149/1**。完整回执[`g2_v11_independent_native_reopen_verified_NOT_FOR_FAB.json`](../../hardware/dcx_main/g2/g2_v11_independent_native_reopen_verified_NOT_FOR_FAB.json)。用户原有所有GUI均保留，仅独立验证GUI已关闭；临时验证拷贝因Windows文件锁未清，**不为清理而结束用户窗口**。
- **制造限制未消失**：0.15mm线宽/0.18mm几何屏障未取得厂家的蚀刻/阻焊DFM签核。GA/GB连通不等于栅极稳定性、保护真实可靠或功率母排100A载流；仍有149 Connection、1 Netlist（五磁件缺实体关联）、真实铜柱与绝缘、16mm叠层、N97 100°C磁件、电流温升、D0十路快速关断等。所有V10/V11都是`NOT_FOR_FAB`。

## KiCad 10.0 CLI（headless，与 LCEDA 互补）

本机路径 `C:\Users\27792\AppData\Local\Programs\KiCad\10.0\bin\kicad-cli.exe`（10.0.6）。
**不在 PATH 里**：`where kicad-cli` 返回空，容易误判"没装"；`/c/Program Files/KiCad` 也不存在，
装在 `%LOCALAPPDATA%\Programs\KiCad`。

**这个路径不许写进工具**（Issue #11）：写死用户名会让 GitHub Actions 的 Runner 复现失败，
而失败的是"A5 工件能否重建"这条回归测试。`main_board_mechanical.find_kicad_cli()` 按
`KICAD_CLI` 环境变量 → PATH → `%LOCALAPPDATA%`/`%PROGRAMFILES%` 通配的顺序找；
找不到是**正常状态**（板文件不需要 KiCad，只有 DRC 和出图需要），
`--check` 会明说"DRC 未复现"而不是静默通过。
官方封装用 `hardware/stock_footprints/` 里的 vendored 副本（来源、版本、sha256、许可见同目录
`PROVENANCE.md`），生成器因此**完全不需要 KiCad 安装**；`report()` 的 `toolchain` 里记着
每个 vendored 封装的 sha256，KiCad 版本记在 `drc.json:kicad_version`，
`placement_report.json` 本身**不放本机版本号**——否则它会在开发机与 CI 之间逐字节不同，
正是这条 Issue 要修的病。
`missing_courtyard` 在 KiCad 里默认是**忽略**：`kicad-cli` 会把 `ignored_checks` 写成 5 项，
板子一个 courtyard 都没有也报"0 条违规"。`project_file()` 把它提到 **error**，
`test_the_courtyard_check_can_fail` 用"删掉一个 courtyard 必须报错"锁住（已验证）。

- 有 `sch erc`、`sch export netlist/pdf/bom`、`pcb drc`、`pcb export gerbers/drill/position`、
  `pcb render`（3D PNG）。**"PCB 这一层 LCEDA headless 做不了"已更正（2026-11-09）**：
  原生带网 PCB LCEDA headless 能建（见 `### 原生 PCB 的 headless 构建（2026-11-09 已实跑）`），
  但 LCEDA 侧还没有**已证明**的 Gerber/DRC 出口 ⇒ **投板包继续走 KiCad**。
- **`.kicad_pro` 缺失会让 ERC 说假话**：`kicad-cli` 只在原理图旁边有工程文件时才读
  `sym-lib-table`；没有工程文件则 `${KIPRJMOD}` 未定义，两张工程库（`UCC24624`、`SR`）
  整体不可见，每个来自它们的符号都被报成"当前配置不包含符号库"。
  实测（`--severity-all`）：无 `.kicad_pro` → **3 条 warning**；加上工程文件 → **0 条**。
  **`-D KIPRJMOD=<dir>` 命令行覆盖不管用**——表根本没被读。
  这三条 warning 与电路无关，但看起来像设计缺陷，足以诱人去改符号（改了也没用）。
  `tools/make_control_board.py` 的 `project_file()` 现在生成它，`tools/test_control_board_erc.py`
  用"删掉工程文件后必须变红"锁住（已验证：删掉后 2 个测试红，且三条 warning 原样复现）。
- **4xxx 门单元的输出脚不是每组的最后一个号**：4081/4071/4093 四单元的布局是
  1,2→**3** / 5,6→**4** / 8,9→**10** / 12,13→**11**（不是 6、13），4069 是
  1→2 / 3→4 / 5→6 / 9→8 / 11→10 / 13→12。写成 4,5→6 会把**输出脚接到电源轨**、
  把输入脚当输出用，而 ERC 只会报一条看起来无关的 `pin_to_pin`。
  `tools/make_d0_protection_board.py` 的第一版就这么错了两处（4093 unit 2 的输出脚 4
  挂在 `PGND`、unit 4 的输出脚 11 挂 `ACK_RAW` 而输入脚 13 挂 `ACK_N` ⇒ token 时钟
  根本没有驱动）。`tools/test_make_d0_protection_board.py` 从零件表重推电路、
  与 `hardware_step()` 逐组合比较，才把这类错误变成测试红而不是 ERC 行。
- **D0 板的 POR 折进了故障锁存**：`flt = fault_b or por`，所以冷启动就是锁存关断，
  等操作员合闸。参考模型 `two_tier_fault_logic.py` **没有 POR 输入**（它把上电表达成
  初态 `latched_off=True`），因此 POR 为真时没有"逐步相等"可比，测试只断言
  板子不比模型更早放开（`test_the_latch_update_is_the_reference_transition`）。
- **D0 板的封装名必须真的存在于 `Diode_SMD.pretty`**：这个 KiCad 里没有
  `D_SOT-23_ANK`（只有 `D_SOD-123` 一族），SOT-23 的稳压管要写
  `Package_TO_SOT_SMD:SOT-23`（与 Q1/Q2 相同）。ERC 把它报成 `footprint_link_issues`
  ——warning 级，但 `check()` 对任何 severity 都 fail-closed，所以名字错会让 `--check` 直接红。
  同一类陷阱还咬过一次：`Device:D_Zener` 之前不在 `STANDARD` 映射里，`build_symbols()`
  直接 `SystemExit`。
- **D0 的"十路全关"现在是逐路二极管取最大值，不是求和，也不是每路比较器**（2026-11-05 整改，
  issue #36 的 P0-1/P0-2）。旧结构是十路 10k 星形经 1k 到地：单管 10 V 只给 **0.500 V**、
  单管 3 V 只有 **0.150 V**，而参考是 **0.200 V** ⇒ 一路停在 3 V 被报成"全关"。
  现在是每路 `1k + BAT54`（阳极接门极、阴极共 `GSMAX`）再经 **R76 22k / R77 6.2k**
  进 LM393：只有**最高**那一路正向导通，其余九路反偏、不贡献，单路 3 V 读 **0.637 V（3.2× 参考）**。
  **门限 0.9419 V（理想二极管）+ Vf**，对 SR 的 `VGS(th)` 下限 1.3 V；按 0.3 V 压降占位只剩
  **0.058 V** 余量——这是明写的残余缺口，不是通过。
  **`D9 BZX84C3V0` 已删**：齐纳的 3 V 是 5 mA 测试点的标称，而该节点只给约 **0.30 mA** 上界；
  分压比在任何电流下都成立（`GATE_SENSE ≤ Vgate × 6.2/28.3`：12 V→2.629 V、15 V→3.286 V，
  按 25 °C 共模反算门极轨上界 **15.976 V**、按全范围 **13.694 V**），Vf 只让节点更低 ⇒ 对任何压降都成立。
  **LM393 的共模上限现在有两行、不再是一个假设**：`references/datasheets/lm393.txt` §5.8 的 `VICR`
  在 25 °C 是 `VCC−1.5 = 3.5 V`、全温度范围是 `VCC−2 = 3.0 V`；15 V 钳位时 3.286 V **过 25 °C 那行 0.214 V、
  超全范围那行 0.286 V**。**分压比为此没有改**：数据手册脚注允许"只有一个输入在范围内"，
  另一个输入是 0.200 V 参考、永远在内；改分压比会把门极门限从 0.9419 V 抬到约 5.04 V，直接赔掉检测灵敏度。
  所以 JSON 同时报 `all_ten_inside_common_mode_at_15v`（25 °C 行，true）与
  `all_ten_inside_full_range_common_mode_at_15v`（false），两项都是物理结果；
  仍未验证的只剩**温度两端的余量**（`lm393_common_mode_margin_verified_over_temperature` 恒 false）。
  它**说不了是哪一路**：一只二极管或 1k 开路会盲掉一路而全高测试照样读到 2.629 V，
  所以 `gate_sense_bring_up()` 给逐路首件判据（`tools/test_make_d0_protection_board.py`）。
  `ANALOG_SAFETY_NOT_QUALIFIED` 与新结构同一条命：逐只 FET 的安全关断 VGS、BAT54 的 Vf 温度带、
  LM393 共模余量的温度两端都还没关。
  **ACK 释放令牌是电平锁存而不是边沿采样**
  （`ACK_ARM = READY ∧ ¬ACK_RAW` 置位，任何故障或失去 READY 复位）：边沿采样只在
  **松开**时采样，开机后第一次按下会被吞掉。同样锁在
  `tools/test_make_d0_protection_board.py`。
- **D0 的两个过流门限不在同一个节点，不能共用一个 V/A**（P0-3）：`slope_v_per_a_peak`
  （0.0412755 V/A）是 **burden 峰值电流 → OC 脚**的量，`OC` 在 `Rf/Rd1/Rd2` 分压之后
  （增益 **24/35 = 0.6857142857**），而 `V(ocdf)` 直接在 burden 上（增益 1.0）。混用会把
  快通道门限**凭空放大 1.46 倍**（42.9 A 对真值 29.39 A）。这一条在
  `d0_trip_timing.py`、`make_d0_protection_board.observations()` 与
  `d0_analog_preflight.ct_fast_path()` 三处各错过一次。
  实测（`design/v3/stage_f/d0_trip_timing.json`）：故障后快通道 **10.21 µs** / **29.39 A**、
  硬通道 **40.10 µs** / **24.23 A** ⇒ **"早 29.88 µs" 成立、"更灵敏"不成立**，两句话必须分开写，
  `fast_threshold_lower_than_hard` 恒 false。
- **响应预算的第一个坑是重复计数**（`tools/d0_response_budget.py`）：`d0_trip_timing.json` 的 10.21 / 40.10 µs
  是 deck 上跑真的 burden 与两级 RC 得到的，**它本身就是检测段**；再加 `filter_poles_us`（47 / 75.4 µs）
  会把 10 µs 的快通道算成 130 µs。预算只加检测之后的三段。
  **许可轨的释放不是 R44/C28 决定的**：`PERMIT_RAIL` 到地并联 R44 10k、R35 100k、U18 `R_EN` 250k 与
  **八只 4.7k**（UCC27524A 的 EN 默认关断下拉），合成 **550.6 Ω**、八只占 **93.7 %**。
  **但节点不落到 0 V**：八只 ENA/ENB 各有约 **200 kΩ 上拉到 12 V**（并联 25 kΩ），所以它弛豫到分压器
  戴维南**上限 0.259 V**，τ 用**戴维南电阻 538.8 Ω**（不是 550.6）⇒ **0.539 µs**，过 `VDIS` 上限 1.21 V
  要 **0.865 µs**、下限 0.70 V 要 1.279 µs，画出来的滤波器只有 TDIS 的 **0.577 倍**。
  **这八只不是"看起来冗余"的速度件，是功能件**：削弱十倍到 47 kΩ，上限升到 **1.481 V**，正落在 EN 自己的
  0.3 V 迟滞带里（1.21 < 1.481 < 1.54），使能与否取决于此前状态；**删掉它们上限升到 3.12 V，高于 VDIS 也高于 VEN
  ⇒ 许可轨永远不能关断任何东西**（不是"晚一点"，是"不关"）。上限按 200 kΩ *typical* 算
  （`ucc27524a.txt` 现已入库，但 ENABLE 表只给 typ、**没有 min/max**），0.259 V 是标称值不是保证值。`permit_rail_release()` 因此按**位号 R36–R43** 选那八只
  （按阻值过滤会把人改过的件悄悄剔出去），并同时报 `ceiling_v`/`without_pulldowns_ceiling_v`；
  上限高过 VDIS 时它返回 `fastest_us: None`（不是"更久"），`build()` 在那里 fail-closed。
  **TDIS 1.5 µs / TEN 18 µs / VEN 1.54–2.0 V / VDIS 0.70–1.21 V / REN 250 kΩ 现在出自
  `references/datasheets/ucc27282.txt`（SNVSAQ5B）**，不再只是第 15 章的转述；`VDIS` 是 min/max 两点，
  延迟要用**两点夹住**，不许挑一个当最坏值（与 SR 板 `VREGOFF` 3.63/4.0/4.25 同一条纪律）。
  §7.3.1 还定下方向：250 kΩ 在**引脚与 VSS 之间**（悬空即关断）⇒ UCC27282 是下拉，只有八只 UCC27524A 是上拉。
  **门极**：驱动器在时 SR **32.8 ns**、主桥 **19.6 ns**（只算外置 2.2 Ω，`RHOL/RLOL` 手册只给符号
  ⇒ 下界）；驱动器失电只剩 10k 下拉**并联检测支路**（R66/R74 那只 1k + BAT54 + R76 22k + R77 6.2k
  = **29.2 kΩ**，并联后 **7.45 kΩ**），SR **110.9 µs**、主桥 66.2 µs（与 32.8 ns 差 **3400 倍**）。**支路里是那只 1k，不是 2.2 Ω 门阻**
  ——门阻在驱动器与门极之间，不在这条通路上，拿它顶替会读成 7.38 kΩ（−0.9 %）；`_detector_branch_resistor()`
  因此按**拓扑**找（门极 → 某节点 → 被 Schottky 接到 `GSMAX`），不按位号也不按阻值。
  **两支路并联不相加**：两族驱动器共用许可轨，谁先失能由各自引脚门限决定——UCC27524A D 版
  `VEN_L` 最大 **1.35 V** 比 UCC27282 的 `VDIS` 最大 1.21 V **先被下降指数穿过**，八只 SR 在
  **0.791 µs** 就失能（比原边早 74 ns；用 1.21 V 去读 SR 会多算这 74 ns）。SR 支路
  0.791 + 0.023 + 0.0328 = **0.847 µs**，原边支路 0.865 + 1.5 + 0.0196 = **2.385 µs**，"十路全低"取较慢的原边。
  合计地板 **44.93 / 15.30 µs**。**解码链按通道计价，不是一段共用**（2026-11-05）：硬通道从
  `HARD_TRIP` 直接进 U10.1，只走三只 CD4071B OR（3 × 250 ns = **0.75 µs**，全有 max）；
  LM393 快通道还要过 U19.1 的 OR（+250 ns）与 U6.4 的 CD4081B AND ⇒ **1.00 µs**；
  外部快通道再多一只 U11F 反相器 ⇒ **1.11 µs**。所以两者之差是 **29.63 µs = 检测差 29.88 − 0.25**
  （快的多走一只 OR），**不再"恰好等于检测差"**——给硬通道摊一只它不过的 AND 和给快通道摊 0 一样错。
  **U6.4 没有 max**：`references/datasheets/cd4081b.txt`（SCHS057C）只有静态表与 Fig. 4 的
  **典型**曲线、**没有动态电气表**（2–4 页是扫描件，`cd4081b_p{2,3,4}.png` 是证据），
  所以它按 0 计、列进 `unpriced_gates`，两条快通道的总数因此**仍是地板**；不许借 CD4071B 的 250 ns。
  U10.4（`FLT|NOT_READY → FF2_RESET`）也定价 0.25 µs，但**不在任何跳闸通路上**，单列 `ff2_clear`。
  `decode_chain()` 逐单元从零件表读回引脚与供电轨，换件/换脚/换网直接 `SystemExit`。
  **比较器与锁存器不再是 `null`**：检测终止于比较器输入端（`d0_trip_timing.py` 头注写明 deck 里这些延迟是理想 0 s），
  所以 1.3 + 0.4 + 2.385 = **4.085 µs** 三段串联。LM393 取 §5.11 的 **1.3 µs typ**（5 mV 过驱；
  同表 TTL 阶跃 0.3 µs，取较慢者）——**只有 TYP 列、没有 MAX**，过驱越小越慢，所以它只让总时间变长；
  CD4013B 取 §6.6 的 SET→~Q **`tPHL` 0.4 µs max**（200 typ，VDD = 5 V、25 °C、20 ns 沿）。
  **边缘按接线选**：FF1 的 SET = `FLT`、~Q 是许可项，所以是 SET→输出下降沿那一行，不是时钟行。
  **1.3 µs 的测试条件是 5.1 kΩ / 15 pF，本板六个 LM393 输出全是 10 kΩ，但差值只落在上升沿上**：
  §7.2.2.4 把两沿分开（`τ_R ≈ R_PULLUP·C_L`、`τ_F ≈ R_CE·C_L`），§7.2.2.1 定极性
  （`IN+ > IN−` 输出高阻、否则灌电流）⇒ **U3A/U3B/U5B 的传感节点在 IN+，故障抬输出；U4A/U4B/U5A 是供电良好分压，故障拉低输出**。
  预算付费的 U3A/U3B 正是上升沿，所以进账，量是**多一个时间常数** 4.9 kΩ × 15 pF = **73.5 ns（1.3 µs 的 5.7 %）**；
  写成时间常数而非延迟（到 1.4 V 只走完上升的一部分，故偏高），且对真实 C_L **线性**、本板 C_L 未测。
  **总时间不加这个数**——给只有 TYP 的数字加增量会显得比实测更准。三个供电监控器的下降沿与上拉无关，
  别把 10 k 记到它们头上。锁存在 `test_d0_response_budget.py` 的 `test_the_two_priced_comparators_assert_on_the_rising_edge` 等五条。
  两处出处是 `references/datasheets/{lm393,cd4013b}.txt`。
  UCC27524A 的 EN→输出 **23 ns max / 13 ns typ** 来自仓库内的
  `references/datasheets/ucc27524a.txt`（SLUSBP4C，D 版列；DGN 版是 17/27 ns，别混），
  **关断时输出拉低还是高阻也已由原厂表回答**：Device Logic Table 6-2 的 `L L Any Any → L L`
  ⇒ **拉低、不是三态**，所以 SR 门极保留 2.2 Ω 通路，110.9 µs 不适用于被释放的许可轨。
  但该手册自己写明 **switching parameters 不是量产测试项**（且指定 12 V / 1.8 nF / 125 °C），
  `RENx` 也只给 typ 200 kΩ ⇒ `RESPONSE_BUDGET_INCOMPLETE`，**地板不是最坏值**。
- 默认 `sch erc -o x.rpt` **不含 exclusions**；"0 条"要成立必须加 `--severity-all`。
- **ERC 报告缺席/过期/指向别的原理图，都不能读成"0 条"**：`kicad-cli` 报违规时**退出码仍是 0**，
  所以 `check=True` 只挡硬失败；`d0` 的 `erc_violations()` 自己校验文件存在、`source` 等于
  `d0_protection.kicad_sch`、mtime 不早于原理图，再加"`sheets` 非空"，任一不满足直接 `SystemExit`。
  旧版缺文件时返回 `[]`，于是崩溃的和跑通的都印出 "0 violation(s)"。
- **指向 deck 的出处写元件名，不写行号**：`deck_line('Rbur')` 解析第一列令牌，改动/改名会当场
  `SystemExit`；手写行号已经错过——R8（10 Ω burden）引来的是第 117 行，即 0 V 测试源 `Vctg`，
  D7/D8 也一起指到了 D2 那一行。测试里另外维护一张**独立的** ref→element 表回查，不从生成器读回答案。
- **值里的电压和 `rating` 必须相等**：电容把电压写了两遍（`100nF/16V` 与 `16 V X7R`），
  四只驱动 bulk 曾写 `1uF/16V` 配 `25 V X7R`——25 V 不会"否决"16 V，只会悄悄指向另一种货，
  所以判据是相等而不是 `<=`。
- `-o` 给 `/tmp/x.json` 会被改写成 `C:\Users\...\Temp\x.json`，回读时按 Windows 路径找。

### D0 十路保护板的铜（已按 issue #36 延后）

`make_d0_protection_board.py` 只到原理图/网表/ERC，**没有已提交的 PCB 生成器**。

- **`d0_protection.kicad_pro` 由 `make_d0_protection_board.project_file()` 单独拥有**，
  里面必须带 `"missing_courtyard": "error"`；谁后写谁决定这条检查，而没有 courtyard 的板子在
  默认设置下报"0 违规"。**不要给这块板另写一份 `.kicad_pro`。**
- **`manufacturing_index.py` 的 `fab: None` 分支**是给"有铜、DRC 干净、但没有任何
  gerber/drill/position"的板写的 ⇒ `NO_FAB_PACKAGE`，理由写"no gerber…"，**不是**
  "manifest does not exist"（那个分支会让人去跑一个没有 fab 导出的生成器）。目前四块板里
  没有一块落在这个状态，分支由 `test_a_routed_board_with_no_package_path_...` 用合成目录锁住。

**D0 的铜已经试过，按 issue #36 停在这里**：2026-11-05 的评论把关键路径改成
"真实驱动器决策（D0A：TI EVM 对 onsemi）→ 10 路保护小板（D0B）"，并明确否掉
"先为两种路线各画 176 器件板"。当时的工作状态：板 180×96 mm，10 个分区、176 只件只占
**18.3 %** 面积，PGND 有 118 个焊盘，最佳一版仍差 40 条连接；每条失败网**单独**都能布通
（HO/HB/OPERATOR_RUN 各 2/2），所以不是几何不可布，是**拥塞与顺序**问题。
0.5 mm 间距的 `Texas_S-PVSON-N10`（焊盘高 0.28 mm ⇒ 边到边 0.22 mm）在 0.25 mm 走线 +
0.2 mm 净空面前根本出不来线，**这种密度要的是地平面，不是再多的 rip-up**。
不要因为这里留了三个杠杆就以为板已经能布通。
- ERC JSON 是 UTF-8，中文描述用 GBK 控制台打出来是乱码；**读 JSON 必须显式
  `encoding="utf-8"`**（默认 GBK 会 `UnicodeDecodeError`）。
- 给已存在的原理图补 `.kicad_pro` 会改变导出网表的 `Sheetname`/`Sheetfile`
  （`Root`→工程名、绝对→相对）。**连接关系不变**：本项目实测 107 个 node 完全相同。
- **封装库的陷阱与符号库完全同构**：`pcb drc` 也只在板子旁边有 `.kicad_pro` 时才读
  `fp-lib-table`。缺了它，每个 `dcx:` 封装报 `lib_footprint_issues`，而且**解析不了的封装
  连 courtyard 都不查**——那种板子的 DRC 会显示"干净"，实际什么都没检查。
  `tools/main_board_mechanical.py` 的 `project_file()` 就为这个存在。
- `pcb export svg --mode-single --scale 1 --page-size-mode 2` 的 `width` 属性**就是**
  板子的真实毫米尺寸（实测 155 mm 板 → `width="154.9908mm"`，差的是 cropped 到图元外沿），
  所以 1:1 打印是成立的；`pcb export svg` 不给 `--mode-single` 时 `-o` 会被写成
  一个**同名文件**而不是目录，下一次运行报"当文件已存在时无法创建该目录"。
- **自定义封装的焊盘要对着摆放间距校核，不是只对着自身外框**：7.3 mm 体的电容按 7.6 mm
  间距摆、焊盘放在 ±3 mm（宽 2 mm），相邻焊盘重叠 0.4 mm，DRC 报了 70 条 clearance；
  改成 ±2 mm 才通。同理 courtyard 是体 +0.25 mm/边，7.6 mm 间距会让 courtyard 相碰
  （换成 8.2 mm）。这两条都不是"看起来对"能发现的。
- `pcb render` 只画**有 3D model** 的封装。生成的占位封装没有 model，所以磁件在 PNG 里
  只剩焊盘——要看轮廓用 1:1 SVG，不要以为渲染图里的空白是漏画。

### G2 V17（2026-11-14 Agent-A 信号布线，KiCad 原生工程，仍非制造版）

- **事实与边界**：本 worktree 的 `hardware/dcx_main/g2/dcx_main_board_g2_V17_KICAD_PGND_VOUT_WIP_NOT_FOR_FAB.kicad_pcb`
  是实际可打开的 KiCad 10 PCB，不是只有老鼠线的画面，也不代表制造就绪。冻结 V15 数据源
  的 149 个器件、419 个实际焊盘、12 层定义、已填充的 7 个铜区保持不变；
  本轮重新生成后是 359 个通孔过孔、135 段走线。
- **原生 DRC 对比（必须带版本）**：2026-11-13 原版 42 条 unconnected、2 条 clearance；
  2026-11-14 本轮继续实布 U1 供电、U2 GD1/GD2 扇出及五条主桥本地门极/自举支路，
  当前最终结果 **24 条 unconnected、2 条 clearance**，未出现新违规；其中 **PGND 未连接 0 条**。
  这只证明当前 KiCad 计算的网表/铜区连续性，不代表高频回路、铜排承载或 EMC 已签核。
  余下的两项全部来自 **U2** 原生导入的 0.5 mm 邻脚（0.2000 mm 规则，
  实际 0.1981 mm），不可通过降低 DRC 阈值来“修复”；必须核对真实 OEM 封装。
  `schematic_parity: []` **不证明**与原理图匹配，仍需独立 parity 回读。
- **F.Cu 两阶段信号路由**：`tools/g2_v17_route_conservative_signal.py` 先保留原始
  38 条短折线路由（含 SS / OCD 与两个 12 V 的明确本地支路），再尝试使用有界 45° A*
  规避其它网铜焊盘和已有信号线；当前生成 45 条规划连接。寻路是铜几何预筛，
  **原生 DRC 才是实际连接判据**。PGND、VOUT、SW、VIN_P、SEC、原边门驱功率回路
  不在该算法的自动布线权限中。
- **短 B.Cu 桥（本轮真实写板）**：`tools/g2_v17_bcu_short_control_bridges.py`
  只允许 RT、CS2、OCM 三条低电流信号使用 6 颗通孔 via-in-pad 与 B.Cu 的
  3 段短铜（8.98 / 12.04 / 5.95 mm），每一颗必须通过 F.Cu/B.Cu 原生
  异网焊盘、已有 F.Cu 走线和全部预留过孔的间距检查，然后由 KiCad 再做 DRC。
  长距离敏感故障信号 OC 仍未强行使用跨板 B.Cu 捷径；U2 细间距 GD1/GD2 另用单独的短扇出约束（下节）。
  SR Kelvin/gate 已有部分顶层候选走线，但尚需与开关电流、回流路径和 EMC 共同复核，
  不得以导通判定为设计完成；仍应优先缩短其环路并核对驱动返回路径。
  via-in-pad 填孔盖帽、焊点热工艺未确认，**不可直接制造**。
- **PGND 铜岛已作实际回流修正**：C101–C112 的 12 个去耦电容 PGND 焊盘均增加真实
  0.30 mm 机械钻径 / 0.70 mm 环径的接地返回过孔；真实 R9.2、R10.2 PGND 焊盘另各加 1 颗接内层的
  局部过孔，连接 GD1/GD2 顶层走线分割的两块 PGND 岛。原生 DRC 的 PGND 开路保持 0，
  没有跨网短接。R1.2 / R10.2 采用局部 solid zone，消除 2 项 `starved_thermal`；
  未全局放宽 DRC。所有 via-in-pad 填孔盖帽和焊盘工艺必须经厂家确认。
- **本轮控制器实布增量**：`U1.7[VCC12]` 增加 1 颗与现有 `In4.Cu` 供电平面接通的真实通孔过孔；
  `tools/g2_v17_u2_fine_escape.py` 通过冻结 PAD 编号和 V15/V17/SIGNAL/BCU/PGND SHA 独立校验
  `U2.7[GD1]` 的 F.Cu 三段扇出、`U2.8[GD2]` 的顶层两段短扇出及底层一段联络。
  GD2 的 0.70 mm 通孔**放在 U2.8 焊盘以外**，另一颗在真实 `R10.1`，避免在 0.5 mm pitch
  上强塞通孔；均沿已有 PGND 返回层约束网络及 DRC 检查，未改全局设计间距。
  当下 GD1/GD2 和 VCC12 原生 unconnected 均为 0；尚未通过 EMC、厂家工艺和主板整体制造闸门。
- **真实主桥门极及自举局部走线**：`tools/g2_v17_local_primary_gate_routes.py` 只承认真实位号/引脚、
  且短于 8 mm 的五条 F.Cu 低/中电流支路：`U2.10→R5.1[GL_DRV]`（4.80 mm）、
  `R4.2→QH.4[GH]`（4.76 mm）、`R5.2→QL.4[GL]`（4.63 mm）、
  `R5.2→R19.1[GL]`（5.40 mm）和 `C5.1→D_BT.1[HB]`（6.87 mm）。
  门极铜宽 0.35 mm，GL_DRV 细引脚出口 0.20 mm；所有线按 PAD、已布铜、过孔和 0.20 mm
  名义间距预筛后写入原生板，再经 KiCad 原生 DRC。**GH_DRV** 高侧驱动 U2→R4，
  以及 `U2.3→C5.1[HB]` 仍然阻塞；不能称高侧驱动完成。
  本轮未因减少老鼠线而让 SW/VIN_P 高电流走线改为细线，也未计算门极回路寄生电感。
- **复现顺序（不能拿规划 JSON 当签核）**：
  `D:\\anaconda3\\python.exe tools/g2_v17_pgnd_power_route_screen.py --write` →
  `D:\\anaconda3\\python.exe tools/g2_v17_route_conservative_signal.py` →
  `D:\\anaconda3\\python.exe tools/g2_v17_bcu_short_control_bridges.py` →
  `D:\\anaconda3\\python.exe tools/g2_v17_u2_fine_escape.py` →
  `D:\\anaconda3\\python.exe tools/g2_v17_local_primary_gate_routes.py` →
  KiCad 10 自带 `python.exe tools/g2_v17_generate_kicad.py` →
  KiCad 10 的 `kicad-cli pcb drc --format json -o hardware/dcx_main/g2/g2_v17_KICAD_NATIVE_DRC_NOT_FOR_FAB.json hardware/dcx_main/g2/dcx_main_board_g2_V17_KICAD_PGND_VOUT_WIP_NOT_FOR_FAB.kicad_pcb` →
  `python -m pytest tools/test_g2_v17_signal_and_bcu.py tools/test_g2_v17_u2_fine_escape.py tools/test_g2_v17_local_primary_gate.py tools/test_g2_v17_native_kicad_drc.py -q`。
  生成器强制验证冻结源、摆放与信号规划 SHA，过孔所在的真实 KiCad 焊盘编号和 XY 必须对应。
- **制造闸门**：T1–T4/CT 的 3:1:1 物理绕组与真实 DOT、100 A 双极铜排与
  多触点输出、12 层磁件制程、过孔填盖、原理图↔PCB parity、全网 DRC
  与 EMC/热测量都未签核。剩余 24 条主要是 SW 7、SECx A/B 8、VIN_P 2、
  GH/R18、GH_DRV、HB/U2、OC 长距离故障链与 3 条 VD_B 感测；
  不应为减少计数而拉长高 dv/dt 或 Kelvin 回路，更不能将这 24 条未连接误写为 0 或导出放行 Gerber。

