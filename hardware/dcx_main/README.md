# DCX 主功率板 —— 原生原理图（A1）

这是 `design/v3/pcb/board_netlist.csv`（由 v3 deck 派生的**金网表**）在嘉立创 EDA Pro 里的
原生可编辑原理图，不是一份新的设计。器件、网络、位号全部来自金网表；本目录只解决一件事：
把 SPICE 的 `G/S/D` 引脚名落到真实封装的**具体焊盘**上，并证明落对了。

项目文件：`dcx_main_board.eprj2`（嘉立创 EDA Pro 4.1.60，`.eprj2` 是 SQLite）。
打开方式：复制到 `C:\Users\27792\Documents\LCEDA-Pro\projects\`，在客户端里打开即可编辑。
**本仓库只有原理图，没有 PCB**——headless 下 PCB 相关 API 不可用，见下。

## 已验证的结论

| 结论 | 证据 |
|------|------|
| 61 个位号已放置，227 个焊盘全部有归属 | `pin_footprint_review.csv` |
| 金网表的 193 个引脚展开成 **221 个焊盘**，逐焊盘比对**无一错接、无一漏接** | `netlist_compare.json` |
| U2（UCC27282）裸露焊盘按设计接 PGND，单独计数，**不算进**金网表的 221 | `pads_bonded_by_design` |
| T1–T4、CT 未放置，原因是**库里没有可用的符号**，已在 `placement_plan.json` 里逐条写明 | `gaps` / `unresolved` |
| 39 个位号是**占位件**（值未定或封装不对），审表里逐行标注 `PLACEHOLDER` | `pin_footprint_review.csv` 的 `note` 列 |

比对是按**焊盘**做的，不是按位号数量做的。这一步是必要的：金网表把 MOS 的引脚叫 `S`，
而 DFN/TDSON 封装的源极是 1、2、3 三个焊盘——只连其中一个，导出的网表仍然"和金网表一致"，
错误要到出铜箔才暴露。

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
```
