下面按UCC24624真实SR行为给精简状态表、上电方案、验证清单和不依赖仿真器的伪代码。

## 1. 精简状态转移表

| 状态 | 进入条件 | 退出条件 | 输出/行为 |
|---|---|---|---|
| UVLO/关断 | REG<VREGOFF；或REG<2V | REG>VREGON且至少一路VD已>VTHARM | VG1/VG2强下拉或弱下拉；SR禁止 |
| 预武装/等待ARM | REG已过UVLO但此前VD未过VTHARM | 任一VD>1.5V并满足blank/延时 | 不立即开通；必须先记录ARM事件 |
| Run-Idle | 已ARM，当前无导通 | 本路VD<-265mV且offblank已过、互锁允许 | 准备开通本路 |
| Ton-Delay | 满足开通阈值 | 155ns或275ns到期 | 保持关断，等待延时 |
| On-Blank | 本路VG刚置高 | 475ns到期 | 强制保持导通，忽略VD |
| On/Proportional Gate | On-Blank结束且VD仍低于关断阈值 | VD>+10.5mV+VSS偏移，或异常保护 | VG按比例门驱；可反向导通MOS模型 |
| Off-Blank | 本路刚关断且VD曾>1.5V | 650ns到期 | 本路禁止再开通 |
| Interlock | 另一路正在导通/刚导通 | 另一路关断且本路条件满足 | 禁止两路同时导通 |
| Standby | CH1平均频率<9kHz持续7.5ms | 平均频率>15.6kHz持续7.5ms | 停止SR，保留体二极管导通监测；退出后忽略首周期 |

## 2. 上电方案（最少改动）

原边先工作，副边先走二极管整流或SR体二极管建立VD；确认至少一路VD>1.5V后，再使能UCC24624的VDD/REG偏置。不能只靠“随便延迟”：必须以VD>VTHARM作为使能SR偏置的许可条件。REG升过UVLO前VD必须先升过VTHARM，否则可能出现VG不按预期开关。

100A/每组两颗40V MOS：VSS外接偏移电阻按手册330µA计算，目标关断阈值=10.5mV+330µA·Roffset；Roffset<212Ω，建议留裕量。比例门驱必须建模：小电流时VG降低，VDS增大，补偿封装电感造成的提前关断。未建模部分：封装电感精确值、MOS反向恢复、驱动器死区、PCB寄生。

## 3. 验证清单

安全正例：
- 上电顺序：原边先启，VD>1.5V后使能REG；SR正常开通。
- 正常LLC周期：两路交替，On-Blank 475ns、Off-Blank 650ns、互锁有效。
- 轻载/burst：延时从155ns切到275ns；退出standby后忽略首周期。
- VSS偏移电阻改变关断阈值，比例门驱仍按原阈值工作。

必定失败负例：
- REG先于VD>VTHARM上电：应判为时序违规，SR不得正常开通。
- 两路同时请求开通：互锁必须阻断，否则判失败。
- Off-Blank内再次触发开通：必须不开通。
- 把SR MOS当理想二极管/正向开关：负电流或反向导通检查必失败。

## 4. 可执行伪代码

```text
init: reg=0; armed=False; state=UVLO; offblank_t=0; onblank_t=0
loop(dt):
  read VDD,REG,VD1,VD2,VG1,VG2,I_SR1,I_SR2
  if REG < VREGOFF or REG < 2V:
      state=UVLO; force_gate_low(); armed=False; continue

  if REG > VREGON and not armed:
      if VD1 > VTHARM or VD2 > VTHARM:
          armed=True; state=RUN_IDLE
      else:
          state=WAIT_ARM; continue   # 关键：不得跳过

  if in_standby():
      state=STANDBY; sr_disable(); continue

  for ch in [1,2]:
      other = 3-ch
      if VG[other]==HIGH: continue      # interlock
      if offblank_t[ch]>0: offblank_t[ch]-=dt; continue
      if VG[ch]==LOW and VD[ch] < -265mV:
          state=TON_DELAY; delay=155ns or 275ns
      if TON_DELAY expired:
          VG[ch]=HIGH; onblank_t[ch]=475ns; state=ON_BLANK
      if ON_BLANK active:
          onblank_t[ch]-=dt; keep VG high; continue
      if VG[ch]==HIGH:
          VG[ch]=proportional_drive(I_SR[ch])
          if VD[ch] > 10.5mV + 330uA*Roffset:
              VG[ch]=LOW; offblank_t[ch]=650ns; state=OFF_BLANK
```

核心断言：`REG>UVLO`之前必须已有`armed=True`；`armed`只能由`VD>1.5V`置位；两路VG不得同时为高；On-Blank内不得关断；Off-Blank内不得开通。