# 48V→2V/100A DCX 初版控制与功率方案

## A 功率连接（唯一文字连接）

**原边**：VIN+ → 半桥高侧MOS Q1漏极；Q1源极＝开关节点SW。SW → Cr（隔直，平均偏置Vin/2，无需两分压电容）→ Lr → P1原边同名端。P1原边异名端→P2同名端；P2异名端→P3同名端；P3异名端→P4同名端；P4异名端→PGND（半桥低侧Q2漏极亦接SW经Q2至PGND）。四磁芯原边串联，各磁芯3:1:1（Np:Ns1:Ns2），总n=12，Vo≈Vin/(2n)=Vin/24≈2V@48V。

**副边**：每颗CT的两个次级绕组端点分别接该组低侧SR的漏极，公共端接VOUT+。即P1的S1a端点→SR1漏极、S1b端点→SR2漏极；四组共8个SR，源极全部接VOUT-（PGND副边）。四组整流后于VOUT+/VOUT-并联。SR为低侧同步整流，体二极管方向由VOUT-指向漏极。

## B UCC25600D 引脚连接（D/8-SOIC，1~8）

| 脚 | 名称 | 连接 |
|---|---|---|
|1|DT|RDT=5.4kΩ到GND（按式td=20ns+RDT×24ns/kΩ，取td≈150ns；手册最小120ns兜底）|
|2|RT|RRT=2.5V/IRT。目标fsw≈200kHz：由式(18) fsw=1/(2×(150ns+6ns/IRT))，解得IRT≈1.60mA，RRT≈1.56kΩ到GND（固定频率，无光耦，不开burst；fsw<350kHz故burst不触发）|
|3|OC|接电流检测网络输出（见C），1V门限；并联1μF Cp到GND|
|4|SS|CSS=10nF到GND；另经100kΩ上拉至12V_S作手动EN，或由外部EN信号拉低<1V关断|
|5|GD2|经隔直电容100nF接栅极驱动变压器原边一端|
|6|GND|控制地，单点接PGND|
|7|VCC|12V_S外供，1μF+100nF X7R到GND|
|8|GD1|接栅变原边另一端|

**起始频率/软启动核算**：手册FSW(start)典型142.5kHz（122~162kHz），即软启动起点高于200kHz目标——软启动期间频率从~142.5kHz升到200kHz，属**增益下降方向**，本方案软启动可用（不产生过冲增益），但需注意起点低于稳态频率意味着启动瞬间增益略高，配合10nF CSS（tss=2.8V/5μA×10nF≈5.6ms）足够缓升。SS delay=1.2V/175μA×10nF≈69μs。

**UCC27282 选 DRC（10-VSON，带EN）**：1 VDD→12V_S；2 NC；3 HB→0.1μF到HS；4 HO→Q1栅（经2Ω）；5 HS→SW；6 EN→10kΩ上拉12V_S+1nF到VSS，可外部拉低关断；7 HI→GD1（经栅变副边+整形）；8 LI→GD2；9 VSS→PGND；10 LO→Q2栅（经2Ω）。**DRC封装脚号与D封装不同，此处全按DRC**。

**UCC24624D ×4（每磁芯一颗，SOIC-8）**：1 VG1→SR_a栅（2Ω）；2 PGND→SR源（VOUT-）；3 REG→2.2μF到PGND；4 VD1→SR_a漏极（串1kΩ）；5 VSS→SR源节点（经Roffset，见下）；6 VD2→SR_b漏极（串1kΩ）；7 VDD→12V_S外供（2V输出无法自供电，必须外供，满足"外供偏置"）；8 VG2→SR_b栅（2Ω）。**REG/VS电阻**：VSS脚经Roffset到SR源，按式(2) Roffset=(VTHOFF−10.5mV)/330μA，取VTHOFF≈35mV→Roffset≈74Ω（<212Ω上限）。**1.7V最坏再武装**：VTHARM max=1.7V，本应用VD摆幅仅约2V，启动时输出从0升到2V，VD需>1.7V才再武装——启动初期可能延迟几个周期才正常SR，属可接受；475ns on-time blanking对应fsw≤625kHz，200kHz远低于上限，**blanking不影响2V应用**，但需注意2V下VDS传感裕度小，建议先验证再武装。

## C 最小过流路径

**原边串联分流+放大**：在P4异名端与PGND之间串Rshunt=1mΩ（4线开尔文），经INA180A2（增益50）放大→RC滤波（1kΩ+100nF，fc≈1.6kHz）→UCC25600 OC脚。阈值：OC 1V对应Ipri=1V/(50×1mΩ)=20A峰值原边电流，对应输出约20A×12≈240W（略高于200W，留裕度）；OC 2V锁存对应40A原边。**候选硬件限流停机**：OC脚加1kΩ+100nF到GND，OC>1V时UCC25600主动拉低GD，属芯片内建可验证电路；硬件限流停机（如比较器+锁存切EN）为**保护候选**，本版不装。

## D 候选BOM（未核实型号标"候选"）

- **原边MOS ×2**：100V N-MOS，候选如CSD19535KTT（待核实Rds_on/Qg与10mm高度）
- **SR MOS ×8**：30V N-MOS，候选如CSD17578Q5A（待核实）
- **UCC25600D ×1、UCC27282DRCR ×1、UCC24624DR ×4**
- **阻容**：RDT 5.4kΩ、RRT 1.56kΩ、CSS 10nF、Cp 1μF、Rshunt 1mΩ、INA180A2×1、RC 1kΩ/100nF、栅变隔直100nF、VCC 1μF+100nF、HB 0.1μF、REG 2.2μF×4、VD串1kΩ×8、Roffset 74Ω×8、栅极2Ω×10、EN上拉10kΩ+1nF
- **输入电容**：2×10μF/100V X7R + 1×100μF/100V电解（候选）
- **输出电容**：4×100μF/4V X5R + 2×10μF/4V（候选）
- **谐振电容Cr**：按fr≈200kHz、Lr候选10μH→Cr≈63nF，用2×33nF/100V C0G并联（候选值待Lr定）
- **磁件**：Lr 10μH（候选）、4×CT 3:1:1（候选，需核实饱和与高度）

## 需下一步确认的最多5个关键点

1. 4×CT磁芯高度≤10mm与3:1:1绕制可行性（含绝缘）
2. SR MOS在2V/100A下的Rds_on与VDS传感裕度（UCC24624 −265mV门限 vs 2V输出）
3. 原边100V MOS的Qg与UCC27282驱动能力匹配、10mm高度内散热
4. Cr/Lr具体值使fr≈200kHz且增益≈1（Vin 46~50V→Vo 1.92~2.08V）
5. INA180A2共模范围与1mΩ分流在开关噪声下的精度