# DCX 主功率板 —— 原生原理图（A1）

> **最新状态：NOT_FOR_FAB / A1-WIP。** 本目录已移入当前开发分支，保留嘉立创原生 `.eprj2` 和真实焊盘比对。**`netlist_compare.json:readiness=PARTIAL_PASS` 不是完整原理图或投板验收。**
> 17 个 BOM 真实外围（R7–R10、C13、C101–C112）已画进原生原理图并逐焊盘核对，但它们仍是**值/MPN 占位件**；
> 缺少 T1–T4/CT 原生符号、物理端子号/极性验收、GUI ERC 与带网 PCB。详见 [磁件符号逻辑合同](magnetics_symbol_contract.json)、[直接整改路线](../../docs/D1_电气优先_增输出与设计整改_2026-11-01.md)。


这是 `design/v3/pcb/board_netlist.csv`（由 v3 deck 派生的**金网表**）在嘉立创 EDA Pro 里的
原生可编辑原理图，不是一份新的设计。器件、网络、位号全部来自金网表；本目录只解决一件事：
把 SPICE 的 `G/S/D` 引脚名落到真实封装的**具体焊盘**上，并证明落对了。

项目文件：`dcx_main_board.eprj2`（嘉立创 EDA Pro 4.1.60，`.eprj2` 是 SQLite）。
打开方式：复制到 `C:\Users\27792\Documents\LCEDA-Pro\projects\`，在客户端里打开即可编辑。
**本仓库只有原理图，没有 PCB**——headless 下 PCB 相关 API 不可用，见下。

## 已验证的结论

| 结论 | 证据 |
|------|------|
| **78 个位号**已放置：金网表 61 只 + BOM 真实外围 17 只，**261 个焊盘**全部有归属 | `pin_footprint_review.csv` |
| 按 A1 任务卡的**六个功能块**绘制，每块有标题文字，块内按功能排列 | `gen/slice_00.js` 的 `labels` |
| 金网表的 193 个引脚展开成 **221 个焊盘**，逐焊盘比对**无一错接、无一漏接** | `netlist_compare.json:pads_checked` |
| 17 个外围的 **34 个焊盘**按 `pin_connections.csv` 连接并单独计数，不混进金网表的 221 | `peripheral_pads_checked` |
| U2（UCC27282）裸露焊盘按设计接 PGND，单独计数，**不算进**金网表的 221 | `pads_bonded_by_design` |
| T1–T4、CT 未放置，原因是**库里没有可用的符号**，已在 `placement_plan.json` 里逐条写明 | `gaps` / `unresolved` |
| 56 个位号是**占位件**（值未定或封装不对），审表里逐行标注 `PLACEHOLDER` | `pin_footprint_review.csv` 的 `note` 列 |

比对是按**焊盘**做的，不是按位号数量做的。这一步是必要的：金网表把 MOS 的引脚叫 `S`，
而 DFN/TDSON 封装的源极是 1、2、3 三个焊盘——只连其中一个，导出的网表仍然"和金网表一致"，
错误要到出铜箔才暴露。

## 评审用的导出图

`main_board.svg` 是客户端自己导出的（`gen/export_svg.js` 调 `sch_ManufactureData.getSvgFile`），
含全部 78 个位号与 6 个分区标题。它**不能替代工程文件**——只用来评审，
改图后要重新导出：

```bash
/d/lceda-pro/lceda-pro.exe invoke --session <id> --ext-uuid eda --timeout 60000 \
    --code "$(cat hardware/dcx_main/gen/export_svg.js)" > /tmp/svg.json
python -c "import json;open('hardware/dcx_main/main_board.svg','w',encoding='utf-8') \
    .write(json.load(open('/tmp/svg.json',encoding='utf-8'))['value']['svg'])"
```

`getSvgFile` 返回整个文件，CLI 输出很大，所以必须重定向；`getPngFile` 也在，但 SVG 可读、可比对。

## 图纸怎么分区

A1 任务卡要求按六部分绘图，`tools/main_board_schematic.py` 的 `SECTIONS` 就是这六块，
放置顺序按信号链：输入/半桥 → 谐振腔与 T1–T4 → 四组 SR → 控制（UCC25600/UCC27282）
→ 偏置/OC/启动 → 输出接口。每块画一个标题文字。

`test_every_placed_ref_sits_in_exactly_one_section` 要求**每个位号恰好落在一块里**：
少一块会被发现（否则器件留在原地），多一块也会被发现（否则被放两次）。
测试还把 `SECTIONS` 的全部位号与金网表的 66 个位号做了集合相等——新增/删除位号不会静默掉队。

审表的 `review_status` 只有四种取值：`MAPPED`、`BONDED BY DESIGN`、`OPEN - REASON GIVEN`、
`OPEN - NEEDS DECISION`。最后一个必须是空的——留一格空白和"已审过"看起来一模一样，
所以测试 `test_every_review_row_carries_a_status_and_a_basis` 直接把它当失败条件。

## 引脚映射从哪来

`library_pins.json` 是对运行中的嘉立创 EDA 客户端**实测**导出的（`gen/probe_all_pins.js`，
按精确 MPN 搜索解析器件，不依赖记忆里的 uuid）。模块里没有任何猜出来的引脚号：

- 器件引脚号覆盖不到金网表的引脚名 → `MappingError` 直接抛错，不静默跳过；
- 一个焊盘被两个不同网络认领 → 同样抛错（这是短路）。

`tools/test_main_board_schematic.py` 会**重新**从 `library_pins.json` 推导 MOS 的 G/S/D 焊盘组，
再和代码里的常量比对——库版本更新导致焊盘重新编号时，红的应该是这个测试。

## 与金网表的唯一一处偏离

`U2` 的焊盘 11 是 VSON-10 的**裸露焊盘**，SPICE 模型里没有它，金网表无从表达。
它在实际器件上是散热路径，也是门驱动开关所参考的电位，悬空是错的，因此接 `PGND`。
这一行在审表里写作 `BONDED BY DESIGN`，在 `netlist_compare.json` 里进
`pads_bonded_by_design` 而不是进 `pads_checked`——**不把它混进金网表的数字里**。

`D_CT1..4` 焊盘 2（BAT54 的第二只阳极）和 `U2` 焊盘 2（datasheet 标 NC）留空，
审表里写明了理由；工具会把"留空"和"漏画"分别报告。

## 金网表之外：17 个真实外围

金网表由 SPICE deck 派生，**表达不了** EN/RUN 默认电平、手动 RUN 跳线、EN 滤波和每只控制 IC 的
VDD 去耦。它们由 `main_board_schematic.py:PERIPHERALS` 单独声明，**不塞进金网表**——
否则"deck 完整"就会被误读成"板子完整"，而制造门槛也就失去了区分能力。

| 位号 | 连接 | BOM 冻结值 |
|---|---|---|
| R7 | RUN–PGND | 10 kΩ |
| R8 | VCC12–RUN（手动 RUN 跳线） | 1 kΩ |
| R9 | GD1–PGND（U2 HI 默认关断） | 10 kΩ |
| R10 | GD2–PGND（U2 LI 默认关断） | 10 kΩ |
| C13 | RUN–PGND（U2 EN 滤波） | 1 nF |
| C101/C102 … C111/C112 | 每只 IC 的 VDD–PGND | 1 µF + 100 nF |

网络名取自 `design/v1/pin_connections.csv` 的**引脚位置**：U2.6=EN 在金网表里叫 `RUN`，
U2.7/8=HI/LI 叫 `GD1`/`GD2`；`12V_P` 在金网表里叫 `VCC12`。测试
`test_every_peripheral_net_is_a_net_the_golden_netlist_already_uses` 锁住这一点，
防止把 CSV 的名字直接搬进原理图、造出一个没人共享的网络（那种错误在图上看起来完全正常）。

它们**不是**新设计：BOM 已有这些行、值已冻结；缺的是 MPN/封装与布局。所以审表仍标
`PLACEHOLDER`，制造门槛也仍不会因为"17 只都画了"而变绿。

## ERC：本站这一轮**不能**用 CLI 签核

`eda.sch_Drc.check()` 是这次客户端里唯一可用的电气规则入口（`Object.getOwnPropertyNames`
显示 `sch_Drc` 原型上只有 `constructor` 和 `check`，没有 `getCheckErrorList` 之类能取明细的接口）。
它 `verbose=false` 返回布尔、`verbose=true` 返回 `[{type, count}]` 直方图，**两个都不给明细**。

实测这个直方图**不随图页内容变化**，所以它的数字不能当 ERC 结论引用：

| 页面状态 | `check(true,false,true)` |
|----------|--------------------------|
| 61 个器件、222 根线 | `warn ×5` |
| 额外放一只**完全未连线的**电阻 | `warn ×5`（不变） |
| 删掉该电阻 | `warn ×5`（不变） |
| **清空整页**（0 个器件） | **`warn ×8`**（反而更多） |

清空后反而变多，说明这个计数不是"这张图页的 ERC 结果"。复现脚本：
`gen/drc_ab.js`、`gen/drc_empty_test.js`（后者会清空图页，跑完必须用
`python tools/lceda_place_main_board.py --all` 恢复）。

**所以 ERC 必须在 GUI 里手工跑一次并截图存档**，本目录不提供 ERC 通过的证据。
这一点写在这里，是为了防止后来者把"5 个 warning"当成一个已知的、已被解释掉的数字。

## 重新生成

```bash
python tools/main_board_schematic.py --write      # -> placement_plan.json + pin_footprint_review.csv
python tools/lceda_place_main_board.py --emit     # -> gen/slice_NN.js
python tools/lceda_place_main_board.py --all --session <id>   # 放置并拉线（需客户端在跑）
/d/lceda-pro/lceda-pro.exe invoke --session <id> --ext-uuid eda --timeout 60000 \
    --code "$(cat hardware/dcx_main/gen/export_netlist.js)" > hardware/dcx_main/gen/netlist_export_raw.json
python tools/check_main_board_netlist.py          # A4 验收：ok 必须为 True
```

`--session` 是客户端 CLI 会话 id；一次 invoke 上限 **60000 ms**（`--help` 里写的 1800000 是错的）。
放置分 3 片跑，`slice_00.js` 会先清空图页，所以**重跑 `--all` 就是完整的重建**。

## 已知缺口（本目录没有假装它们不存在）

1. **T1–T4 没有符号**：需要 5 引脚 3:1:1 变压器（PRI_A/PRI_B/SEC_A/SEC_B/CTAP），
   库里唯一的 5 焊盘变压器 `EE16_65KHZ` 露出 6 个引脚。
2. **CT 没有符号**：需要 4 引脚电流互感器，`ZHT104A` 只有 2 个引脚。
3. **占位件**：Lr、Cr、Cin、Cout、D_BT 以及全部 R/C 的值仍是 `TO ASSIGN`，
   审表逐行标 `PLACEHOLDER`；它们连的是**对**的网络，但**不是**设计选定的料。
4. **没有 PCB**：`pcb_Document.importChanges` 返回 true 但导入 0 个器件，
   `dmt_Pcb.createPcb` 返回 undefined，`pcb_PrimitiveComponent.create` 抛 `[object Object]`。
   导入 PCB 需要在 GUI 里手工完成。
5. **没有网络表同步回路**：本目录的网表比对证明"原理图 = 金网表"，不证明
   "PCB = 原理图"。后者要靠 GUI 的导入和 DRC。

## 目录

```
dcx_main_board.eprj2          原生工程（可编辑）
library_pins.json             实测的器件引脚（11 类，来源 gen/pins_probe.json）
placement_plan.json           每个位号 -> 器件 uuid + 焊盘->网络
pin_footprint_review.csv      A3 审表：227 行，含未接线焊盘的理由
netlist_compare.json          A4 比对结果
gen/probe_all_pins.js         按 MPN 实测引脚
gen/export_netlist.js         导出客户端自己的网表
gen/slice_NN.js               放置脚本（由 --emit 生成）
gen/drc_ab.js                 证明 CLI ERC 直方图不随页面变化的实验
gen/drc_empty_test.js         清空页面再测 ERC（破坏性，跑完要 --all 恢复）
gen/api_probe.js              证明 eda.* 不是"什么都返回函数"的桩
gen/export_svg.js             导出评审用 SVG
main_board.svg                上述导出结果（2048×5273）
```
