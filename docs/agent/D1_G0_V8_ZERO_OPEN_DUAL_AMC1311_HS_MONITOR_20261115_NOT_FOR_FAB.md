# D1 G0 V8 — V7 24路闭合与双隔离高侧监测实体CAD交付（2026-11-15）

**当前状态：G0 BLOCKED / G1 PENDING / NOT_FOR_FAB；不是安全认证与制造许可。**

推荐完整原生可编辑 KiCad10 工程压缩包：
hardware/dcx_main/g2/d1_g0_V8_MONITORED_INTERLOCK_NOT_FOR_FAB/G0_V8_58PART_GH_HB_MONITORED_INTERLOCK_NATIVE_KICAD_NOT_FOR_FAB.zip

ZIP包含6层PCB、SCH、PRO、本地符号库、独立设计来源的原生网表、BOM、原生ERC与DRC及带SHA256的逐脚核对证据。V5主功率板、V6双域偏置板和V7初期联锁板均原样保留。

## 真实工程成果

1. **旧V7 24项未连接全部实际布通。** 使用KiCad10 pcbnew进行F.Cu SMD引出、In2.Cu以及第二条内部信号层绕线；保持48V外部机械常闭急停接点A的串接断能网络，不在PCB内短接两个NC端子。24/24路线已完成、原生KiCad DRC0、未连接0。原先Freerouting在本机出错及超时，因此仅保留独立可复现的原生KiCad实际路线，不混入失效外部布线文件。
2. **新增31个真实高侧检测电路封装，合计58个本地PCB真实器件。** 带保险丝设计候选的Traco THN30 48→12V隔离模块提供可预充的浮动HS_VB/HS_SW电源，另一颗onsemi MC7805CTG以及原边相同器件分别提供浮动HS5V和原边PRI5V。两颗TI AMC1311BDWVR分别对来自J_HS_SENSE的GH_RAW和HB_RAW进行100k/10k源极参考分压、以HS_SW为GND1测量、跨隔离器件输出OUTP/OUTN至原边，可从J_HS_DIFF端子取得差分模拟信号。高侧与原边回流、稳压铜区物理分域，未将HS_SW与PGND共地。
3. **增加真实LM393BIDR双比较器的两路诊断**：HB_VALID与GH_GATE_OFF，输出均上拉至PRI5V而不是原边12V；比较器和模拟放大器所需的实际电容、分压、电源与端子均完成KiCad布线。GH_GATE_OFF只能用于静止/预启动检查，不能在正常PWM高侧导通时作为连续许可判断。HB_VALID只有单端OUTP比较、不包含鲁棒的OUTP−OUTN阈值判断；**不是签核后的UVLO或快速门极保护**。
4. **本机原生KiCad严格检查完成：58封装、171组来自独立电路定义的Ref/Pin/Net、一一对应原生PCB与导出SCH；KiCad ERC0、PCB DRC0、未连接0。** 保持6层完整电气连接，但PCB板尺寸约255×160mm，是独立的安全控制/观测子板试验候选，**不是**极致薄型1砖功率主板设计。
5. **真实默认禁止许可**：R_HS_RELEASE 0R焊位虽然允许HB_VALID与旧版HS_OK_IN两端各自铜网布通，但设置了KiCad原生DNP属性（非仅在Value文字中写DNP），物理不装焊。旧V7 HS_OK_IN仍有硬件100k下拉，未经认可的5V诊断量不会误作为12V高电平许可。R8主功率板RUN也保持DNP。

### 关键厂商资料与局限

- TI AMC1311B datasheet：https://www.ti.com/lit/ds/symlink/amc1311.pdf，DWV 8针：1 VDD1、2 IN、3 SHTDN（运行时绑定浮地低电平）、4 GND1=HS_SW、5 GND2=PGND、6 OUTN、7 OUTP、8 VDD2=PRI5V。器件为增强隔离放大器，但**板级隔离/爬电、瞬态、电源丢失和温升没有经过实测认证**。
- onsemi MC7805：https://www.onsemi.com/download/data-sheet/pdf/mc7800-d.pdf；TI LM393B：https://www.ti.com/lit/ds/symlink/lm393b.pdf；Traco THN30：https://www.tracopower.com/products/thn30.pdf。
- 由AMC1311B OUTP单端判别产生的HB有效参考采用PRI5V下16k/10k分压约1.923V、GH静态OFF参考22k/10k约1.563V。若仅采用典型AMC输出共模1.44V、名义增益1与输入分压100k/10k，HB−SW标称判定点约10.63V。然而厂家OUT共模1.39–1.49V的变化将使同一个单端门槛偏至约9.53–11.73V；还未加入真实偏置5V与温度/电阻公差，因此**禁止把这一路比较器当成最终高侧UVLO**。AMC1311B带宽约数百kHz，不满足几十纳秒级高侧门极安全关断实测要求。
- 独立的GH-SW运行期命令期望比较、失压自检、强制硬件gate-off、接触器主触点焊死检测、两路机械NC硬件安装、测试时序及SOA、最坏条件退磁和实际母线下降仍未完成。高侧浮动Traco输出VB/SW尚未真正接入原主板V5的UCC27282，必须在预充、电源反灌、自举冲突风险评估后接线，不能仅凭此原生CAD上电。
- 原始磁件T1–T4/CT仍缺真实24端子/DOT/绝缘和Lm/Llk/磁芯与制造认证；V5功率级100A铜截面及EMC/冷板/DFM未通过物理验收。
- **九项G0实物见证依然0/9，六故障×十路VGS原始示波器证据0/60。** 所有物理验收仍需设备、板卡序列号、厂家绝缘与真实测量、独立工程师签核。

## 重现检查

在仓库根目录以KiCad10内置Python运行下列脚本的 --check：
- tools/d1_g0_v8_route_interlock.py
- tools/d1_g0_v8_highside_monitor.py
- tools/d1_g0_v8_route_highside_monitor.py
- tools/d1_g0_package_v8_full_highside.py

标准Python运行 pytest tools/d1_g0_test_v8_monitored_interlock.py -q；再运行 python tools/d1_lane_c_g0_acceptance.py --check 及 python tools/d1_g0_physical_readiness.py --check。**以上均只能证明CAD与文件一致，不是实体安全许可。**
