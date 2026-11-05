**极性复核**：FAST_EXT_N低有效=故障。模块正常10k上拉≈4.55V(1.2k/10k分压？按V5算)，EXT_N=高→U11 pin13高→pin12低(反相)，U19第1门OR(旧FAST_TRIP, FAST_EXT_H)输出低→U6 pin12低=无故障。线路断开→100k下拉使EXT_N低→pin12高→OR输出高→FAST_COMBINED高→触发。极性链一致，方向正确。

**脚号**：CD4071第1门：1=A(FAST_TRIP)、2=B(FAST_EXT_H)、3=Y→U6 pin12。余门输入接PGND：5、6→4(NC)；8、9→10(NC)；12、13→11(NC)。U19 VDD=pin14接V5，VSS=pin7接PGND，pin14/7间加0.1µF。U11第6反相器：pin13入FAST_EXT_N、pin12出FAST_EXT_H，pin14=V5、pin7=PGND。D0连接器新增脚：FAST_EXT_N、PGND、V5(同域)。模块侧10k上拉至V5，EXT_N接收端100k下拉至PGND。

**掉电风险复核(不闭环)**：
1. V5整域掉电：U11/U19失电，输出不定，须依赖既有V5监督/UVLO钳制FAST_COMBINED，属已有机制，本ECO不新增保证。
2. 模块单独V5线断、主域仍带电：模块输出高阻，接收端100k下拉→EXT_N低→报故障，方向安全。
3. 模块OCD经D2回灌：回灌路径可能经U11输入保护二极管向V5注流，导致EXT_N被抬高的伪正常态，**未验证**，仅作硬件试验，不得宣称fail-safe。
4. U19失电时OR门输出低=抑制故障，与"低有效"语义冲突；须确认U19与U6同V5域，且掉电时U6 pin12不被悬空拉低。此点为本ECO残留风险，需在试验中测量。
5. 100k下拉与模块10k上拉分压：正常≈4.55V(高)，OCD时模块拉低，阈值裕度需实测U11 VIH。

**测试**：hardware_step新增`fast_ext_n=True`默认，`f=fast_trip or not fast_ext_n`，旧用例不回归。四状态(正常/FAST_TRIP/EXT_N低/双故障)+断线用例按原生网络名执行。

**结论**：本ECO只解决EXT_N极性映射与OR合并，不解决模拟供电回灌、U19失电默认态等风险；低成本默认态≠全失效保证。不重建保护板。