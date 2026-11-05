# 紧急集成审核：给出具体ECO，禁止泛化路线

最新：fast_oc和sr_fault_validation已有Gerber/钻孔各13文件；SR板Q41仍TO_SELECT，REG门限已修3.63V。D0176实体件、无PCB。主板61占位。
独立发现P0：D0 U3B LM393 pin5(+)=OC_FILT, pin6(-)=REF_1V8,pin7=FAST_TRIP,10k上拉；过流输出高。FAST_TRIP与FAST_ARMED_IN经AND成FAST_ARMED，之后OR入FLT，CD4013 SET=FLT。因此D0 FAST_TRIP高有效。
快OC板TLV3501 OUT高表示过流，驱动2N7002 Q1把同名FAST_TRIP拉低；文档让J1.4直接接D0 FAST_TRIP，声称开漏线或。实际是极性反，且拉低可压制原比较器高故障。健康态旧LM393拉低使问题隐蔽。需要立即阻止原接口接线。
任务：用≤1200中文字提出可落地ECO：保留两路高有效故障，用独立FAST_EXT_H与旧FAST_TRIP经OR汇入故障逻辑，不能把推挽TLV直接接旧开集电极网络；注明新OR需评估供电丢失/默认态。给四状态真值表、断电额外场景和导出文件失效清单。
同时：快板D1/D2标BAT54但footprint D_SOD-123，未固定厂商后缀；给官方料号/封装核对任务，不编脚号。Q41可评AO3400A，官方30V SOT23、Rds最大48mΩ@2.5V/25°C，不能因此自动宣称所有温度SOA合格。4.7Ω+0.048Ω、2.3uF、V0=11、Vth=3.63算理想放电与峰值，补R44瞬态功率（MOS降低Rds会提升R44峰值）。
要求输出一个24h工单：先P0接口，再具体Q41/R44/D1/D2 BOM，再重新制造导出，最后主板标准件ECO。不许加新综合审核工具，不假装本地已改代码。不得给未经核对的固定先关SR规则。
