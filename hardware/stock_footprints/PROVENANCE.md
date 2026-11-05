# 从 KiCad 官方库 vendored 的封装

本目录存放生成器需要、而本仓库自己**不生成**的官方封装。理由见 Issue #11：
生成器原先把 `C:\Users\<user>\AppData\Local\Programs\KiCad\10.0\share\kicad` 写死，
一旦换机器或换用户名（GitHub Actions 的 Windows Runner 就是），
`test_the_committed_board_is_what_the_table_produces` 会失败——**再生成**不可移植，
而不是板子本身有问题。

## 谁在用

| 消费方 | 用到的库 |
|--------|----------|
| `tools/main_board_mechanical.py`（A5 1:1 摆放） | `Package_SON` |
| `tools/make_sr_fault_board_pcb.py`（单对 SR 验证板布局 pass 1） | 全部 |
| `tools/make_fast_oc_pcb.py`（TLV3501 快速过流 ECO 模块 PCB） | `Package_TO_SOT_SMD`、`Diode_SMD`、`Connector_PinHeader_2.54mm`、`Resistor_SMD`、`Capacitor_SMD`、`TestPoint` |

## 清单

来源都是 **KiCad 10.0.6 官方库** `share/kicad/footprints/<库>.pretty/`；
修改只有一项：行尾统一为 LF（CRLF → LF），几何与文本未改；
`sha256` 是对 LF 文本算的（与文件里实际字节一致）。

| 封装 | 字节数 | sha256（LF 文本） |
|------|--------|-------------------|
| `TestPoint:TestPoint_Pad_D1.0mm` | 1748 | `6d602c576b4ab0de29fa4cc096f419a62e828ba45ceee30c1263d86b420b2b12` |
| `Resistor_SMD:R_0603_1608Metric` | 1943 | `7190ac4a00125b807e54129ef0d87d87f2a658eeb74d025a7028203419b09f23` |
| `Resistor_SMD:R_0805_2012Metric` | 1945 | `f050b6a50cc7e6f86291fb7aa8f87b0d02255e21cfbddf291cdccc87e5889794` |
| `Resistor_SMD:R_1206_3216Metric` | 1943 | `c7320668dc81bbb954cb4f15e4e7a766c120059343d43551468c8f7ccc8fde37` |
| `Resistor_SMD:R_2512_6332Metric` | 1941 | `abab4bf8eeb3ed03061d8eeb56b542cdac074ce8a0ace0f9b06e933c0b48f297` |
| `Capacitor_SMD:C_0603_1608Metric` | 1928 | `fe0dbfefbb181a0466f93a8de52d84ba7b00fcd9acdbb69575f4128a0af4e405` |
| `Capacitor_SMD:C_0805_2012Metric` | 2030 | `62775a51fe74ba7f1b572de327bdbd3fc92582721b2abcaa47787865590d89cb` |
| `Capacitor_SMD:C_1206_3216Metric` | 1938 | `b2e4a08e3aaf40bc587090190c0e3969e962d7ae962c172cce0581ae8327651c` |
| `Capacitor_SMD:C_1210_3225Metric` | 1936 | `e1dae516e079b70c4736d001fb81bfb4ef5f9c2a37c8175223a44f83a04ff75f` |
| `Package_TO_SOT_SMD:SOT-23` | 4485 | `0d88c86c1b6d8c1aae4aa8c09386264c089d4451a128b6ccd63ed253f4300b15` |
| `Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical` | 2809 | `5301303268f72ba9cc94b7fdbac355951933e6854272ce8d300b679b86b5d45d` |
| `Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical` | 2937 | `e5f24b6fea852f86171042806da48490229c9c8025b6d266b8cad6485b26e79f` |
| `TerminalBlock:TerminalBlock_MaiXu_MX126-5.0-02P_1x02_P5.00mm` | 5159 | `2d23d7c92fe098ad4e511f5eefdd34dc0d4ced8cad15fcea606fbee42512c4cf` |
| `TerminalBlock:TerminalBlock_MaiXu_MX126-5.0-04P_1x04_P5.00mm` | 6869 | `44a22e99c0ea1d599680bdfdc9f4a5c0e4bc852eeedea277b37d2ac051c1ffd8` |
| `Package_SON:Infineon_PG-TDSON-8_6.15x5.15mm` | 6672 | `7ca4fe5be0d2737af7dd600a5a6fb16ca5ef3c6f460981b98ba0a4093075bcbb` |
| `Fuse:Fuse_1206_3216Metric` | 1879 | `8f4307d8c771db71526ed8ccf7c762824636660adec3635905932cc5e1d02280` |
| `Diode_SMD:D_SMB` | 4551 | `e25e9f4acef5b55585afebc48c685e151fd0d2f33a5c3c61f9fdf0389e19ae67` |
| `Diode_SMD:D_SMA` | 4551 | `f7cba3b52ed8b34dce89170722de58324eac04e9e61a095e0eab37b9ca93cb7f` |
| `Package_SO:SOIC-8_3.9x4.9mm_P1.27mm` | 4582 | `074ecb2092b24fa4b4b9cdd7c926fc587b0d7d6d21e7341e57935fd42d36894f` |
| `Package_TO_SOT_SMD:SOT-23-6` | 4280 | `f341c73aac9dcb553456f68bf3fee3d26eb14acf6d8a1cae82b50418fe1d71ca` |
| `Diode_SMD:D_SOD-123` | 4584 | `fd16785935b01254e1076f490e12f0f096da73cf087adefce51225585c62557a` |
| `Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical` | 3051 | `571d2d16b49795f8f9a91f96cc83fd2adf49890cd66c377189c44204ebd03c29` |

许可：KiCad Libraries，CC-BY-SA 4.0 + 设计使用例外（用库做板子不算衍生作品）。
此处未改内容，无新增义务。

## 别把 TDSON-8 当成 BSC010N04LS6 的 land pattern

这只封装的 `descr` 字段指向 **BSC520N15NS3**（150 V 器件），而 BOM 里是
**BSC010N04LS6**（40 V）。板上用它是为了拿到 PG-TDSON-8 **6.15 × 5.15 mm 外壳**的
真实外形、焊盘几何与 courtyard；`land_pattern_provisional` 仍写着**焊盘不是为该器件
核准过的 land pattern**。换器件或换封装前，这句话要重新核。

## 校验

`tools/test_main_board_mechanical.py::test_the_vendored_footprint_matches_the_installed_library`
与 `tools/test_make_sr_fault_board_pcb.py::test_the_vendored_footprints_match_the_installed_library`
在本机装了 KiCad 时逐字节比对 vendored 副本与官方库（行尾归一后）；没装则 skip，
并在 skip 理由里写明"没有做这项比对"，而不是当作通过。
