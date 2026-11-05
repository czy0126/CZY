# 直接实施快OC/D0接口ECO，请审核最小实现

现有模块TLV OUT高故障→Q1拉低J1.4；现有D0 FAST_TRIP高故障。禁止直连。
为保持已经布好模块PCB几何，拟将模块输出明确命名FAST_EXT_N（低有效），D0新增独立连接器，U11现有闲置第6反相器pin13输入FAST_EXT_N/pin12输出FAST_EXT_H；新增CD4071 U19第1门将旧FAST_TRIP和FAST_EXT_H作OR到FAST_COMBINED，U6 pin12改接FAST_COMBINED。U19余门输入接PGND输出NC、供电去耦。EXT_N接收端100k下拉：模块10k上拉正常约4.55V；输出线断开默认低→故障。模块仅从D0同域V5供电，整域掉电由已有V5监督/驱动UVLO，模块单独供电线断开/OCD通过D2回灌需作为未闭环硬件试验，不宣称已fail-safe。
hardware_step新增默认fast_ext_n=True参数兼容旧测试；f=fast_trip or not fast_ext_n。新增按实际原生网络执行的四状态和断线测试。
请给出具体脚号/电平/掉电风险复核，最多800中文字。不要提出必须重建整个保护板。明确此ECO解决极性，不解决所有模拟供电风险；禁止将低成本默认态称全失效保证。
