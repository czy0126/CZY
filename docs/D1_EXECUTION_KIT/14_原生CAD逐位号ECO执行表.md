# 主板原生 CAD 的 61 位号工程修改包（ECO，不是EDA已更改）

本文件与 [61行原生ECO清单](templates/vendor_native_cad_eco_61.csv) 自动生成工具 `tools/vendor_native_cad_eco.py` 共同使用。数据来源是 **当前原生编辑器已有的网表 `hardware/dcx_main/gen/netlist_export_raw.json`、实际器件符号及临时封装 `placement_plan.json`、原始61条物料需求、逐位号候选数据库**。

本次不凭空替换任何 `.eprj2` 中的库 UUID，避免未核物理Pad尺寸/封装就把工程误称已修复；这是能直接给EDA操作者逐项操作、并在完成后逐位号复核的执行清单。**全61条 `ecad_status=NOT_APPLIED_NOT_ERC_VERIFIED`。**

## 工程更新顺序

- **P0：R3** 实际原生符号是 `R0603_10k` 且焊盘`R0603`，CT负载节点为 `OCD↔OCM`。新候选 10Ω Vishay `CRCW251210R0FKEHHP` 必须把阻值 10k→10Ω，且 **R0603→R2512**，重新检查焊盘、丝印、铜走线、过流脉冲与间隙。不能仅把 BOM CSV 中的 2512 料号改掉。
- **P0：R1/R2** 原生 `R1=DT→PGND`、`R2=RT→PGND`；正确值为 R1 5.36kΩ、R2 976Ω。此前 BOM 参考文档把两者误配，已纠正；再导入原生系统时必须以 **网表引脚功能/目标电阻**而非原旧标签确认。
- **P1：C101等奇数号（6只）** 原生 `C0603_100n` 占位，但要求1µF；C102等偶数号保留100nF标称，但每个IC的就近去耦回路与真实额定DC bias依然需要验证。
- **P1：C7–C10** 原生 100nF，占位要求 **2.2µF**，需要原生器件改值、改具体料号并验证REG寄生电感/偏置容量。
- **P1：C5** 原生100nF/0603，目标220nF/0805，要求**同时改封装和容量**并根据实际自举偏置重算 `C_eff`。
- **P0余项：CT、Lr、Cr、Cin、Cout、T1–T4以及D_BT**，仍需要定制物理结构、真实功率用封装或明确的整合布局；对应ECO为明确OPEN，不应拿临时封装直出PCB。

## 可复现检查

```bash
python tools/vendor_native_cad_eco.py --check
python -m pytest tools/test_vendor_native_cad_eco.py -q
python tools/d1_fabrication_gate.py --require-release
```

**放行口径：** 工程修改完必须原生导出全网、真实 ERC/DRC、更新候选实际库封装和实物型号及证据签名。继续保持 NOT_FOR_FAB。
