# 从 KiCad 官方库 vendored 的封装

本目录只存放 `tools/main_board_mechanical.py` 需要、而本仓库自己**不生成**的官方封装。
理由见 Issue #11：生成器原先写死 `C:\Users\<user>\AppData\Local\Programs\KiCad\10.0\share\kicad`，
一旦换机器或换用户名（GitHub Actions 的 Windows Runner 就是），
`test_the_committed_board_is_what_the_table_produces` 会失败——**再生成**不可移植，
而不是板子本身有问题。

| 字段 | 值 |
|------|-----|
| 封装 | `Package_SON:Infineon_PG-TDSON-8_6.15x5.15mm` |
| 来源 | KiCad 10.0.6 官方库 `share/kicad/footprints/Package_SON.pretty/` |
| 修改 | 仅行尾统一为 LF（CRLF → LF），几何与文本未改 |
| 字节数 | 6672 |
| sha256（LF 文本） | `7ca4fe5be0d2737af7dd600a5a6fb16ca5ef3c6f460981b98ba0a4093075bcbb` |
| 许可 | KiCad Libraries，CC-BY-SA 4.0 + 设计使用例外（用库做板子不算衍生作品）。此处未改内容，无新增义务。 |

## 别把它当成 BSC010N04LS6 的 land pattern

这只封装的 `descr` 字段指向 **BSC520N15NS3**（150 V 器件），而 BOM 里是
**BSC010N04LS6**（40 V）。板上用它只是为了拿到 PG-TDSON-8 **6.15 × 5.15 mm 外壳**的
真实外形与 courtyard，从而让摆放与高度检查有依据；`placement_report.json` 里
SR1A–SR4B 的证据等级因此是 `kicad-library`（外形来自官方库），
而 `land_pattern_provisional` 明确写着**焊盘仍不是可投产的 land pattern**。
换器件或换封装前，这两句话都要重新核。

## 校验

`tools/test_main_board_mechanical.py::test_the_vendored_footprint_matches_the_installed_library`
在本机装了 KiCad 时逐字节比对 vendored 副本与官方库（行尾归一后）；没装则 skip，
并在 skip 理由里写明"没有做这项比对"，而不是当作通过。
