# 本机与远端运行环境（LTspice / ssh / schtasks）

> 从 `CLAUDE.md` 拆出（2026-11-06）。**本文件不自动加载**。
> 家的分布与热区见 [`../../CLAUDE.md`](../../CLAUDE.md)，
> 一条一条的硬规则见 [`TRAP_INDEX.md`](TRAP_INDEX.md)。
> 旧引用里的「CLAUDE.md §小节名」按那里的表解析到本文件。

## 本文件目录

- 远端仿真主机（winsrv）

## 远端仿真主机（winsrv）

本机内存/性能不足，**仿真一律在远端 `winsrv` 上跑**（2026-11-04 用户指令）。本地仓库仍是真值，
远端只执行。下面只记会踩到的操作事实。

- **VPN 开着时 `ssh winsrv` 连不上**：Wintun 装的 `0.0.0.0/1` 长前缀压过物理默认路由。
  不要改路由（要管理员），用源地址绑定：`ssh -b <本机 WLAN IP> winsrv`、
  `scp -o BindAddress=<同一 IP>`。IP 是 DHCP，用前现查 `ipconfig`。
  **2026-11-06 实测**：三个历史地址 `10.162.90.166` / `10.162.236.171` / `10.192.122.188`
  对 TCP 22 全部无响应，`ssh -b 10.162.72.38` 也超时（`Find-NetRoute` 显示走
  `本地连接` 的 Wintun）。本机 WLAN 是 `10.162.72.38/16`，有 on-link `10.162.0.0/16`
  路由（前缀 16 长于 VPN 的 `/1`）⇒ **只要 winsrv 还在 `10.162.x` 就能直连**；
  当前地址需要到机器上 `ipconfig` 查，光靠本机猜不出来（不做全网段扫描）。
- **大文件（`.raw`）不住在本机**：`sim/v3/*.raw` 合计约 97 GB，全部由 deck 在 winsrv 重生成；
  Git 忽略它们，`ci_check` 与测试在缺失时跳过（manifest 只在 raw 存在时比 size/mtime）。
  本机磁盘紧张时，**确认远端有副本后**再删本地 raw；要分析就在 winsrv 重跑。
  2026-11-06：D: 仅余 47 GB，迁移因上面的地址漂移暂未完成，本地 raw 暂不删除。
- **LTspice 用 `D:\ADI\LTspice-26.0.2\LTspice.exe`**（与本地同版本、同 sha256）；
  同一台机器上原有的 `D:\ADI\LTspice\LTspice.exe` 是 **26.1.1**，不得用于本项目。
- **跨主机数值不逐位相同**：同为 26.0.2，冻结 100 A deck 在远端是 213 603 点、本地 216 689 点
  （−1.42 %），`Vout`/`Iout` 差约 0.0075 %、纹波差约 **1.0 %**（49.235 对 49.733 mVpp）。
  原因是自动探测的线程数不同（远端 `Maximum thread count: 64`、本地 24），而 LTspice
  **没有线程数开关**（`-threads` 与 `.options` 里都没有）。**同一台主机上重跑是逐位相同的**
  （去掉 `Title:`/`Date:` 头两行后 SHA-256 一致），所以一次比较的两侧必须都在远端产生，
  **不许拿历史本地 raw 配新远端 raw**。
- **暂存用 Python `tarfile` 解包，不要用远端 `tar.exe`**：bsdtar 在 GBK locale 下把 UTF-8
  中文路径写成乱码副本，还剩 22+ 个文档解不出来。`git archive --format=tar HEAD | gzip -6`
  上传后 Python 解包，1936 个文件与 `git -c core.quotepath=false ls-tree` 对齐。
- **deck 的目录深度是承重的**：`.include ../../models/...` 只在 `sim/` 下一层（如 `sim\v3`）
  能解析；放成 `sim\bench_par\lane0` 就报 `File not found` 且不产生 raw。并行 lane 必须是
  `v3` 的**兄弟目录**。
- **并发上限 3 是 sshd 的 Job Object，不是 LTspice**：经 ssh 直接起的 LTspice，第 4 个起
  退出码 0 且什么都不写（1 s / 10 s 错峰都一样，重试 8 次也活不下来）；改成经 `schtasks`
  启动后 **6/6 存活**。所以并行必须由 `schtasks` 起，它还顺带解决会话结束时子进程被整棵杀掉。
- **`schtasks` 的令牌是受限的**：任务对 `D:\work\...` 那条暂存树连 `icacls` 都被拒，
  所以经 `schtasks` 跑的东西要放在 `C:\work\...` 下（连同 `models\` 一起复制）。
  不要为此去放宽暂存树的 ACL。
- **进度不能用 raw 大小看**：正常运行时 ASCII raw 在结束前一直是 **0 字节**（结束后一次性出现，
  308 832 722 字节），`.log` 只在启动时写一次。判活/判死看**进程 CPU 时间是否还在增长**
  （`GetProcessTimes`）；两种已知故障是"退出 0 但什么都没写"和"活着但 CPU 不涨"。
- 结束 LTspice 仍然只按 PID（见上）；supervisor 只能杀自己的子进程。
- **并行入口是 `tools/remote_lanes.py`**（在远端跑，经 `schtasks` 启动）：
  `--root <暂存根> --deck sim\v3\<deck>.cir --jobs N --stagger 3 --reference <参考.raw>`。
  lane 复制到 `sim/lane<HHMMSS>_<i>/`（必须是 `v3` 的兄弟目录），每条自带 CPU 看门狗
  （90 s 不涨且无 raw 就杀重启，最多 5 次），结束时对每条 raw 做 body hash（去掉
  `Title:`/`Date:` 两行头）与参考比对。
  **实测吞吐（同一 100 A deck，每点一次运行）**：1 路 251.5 s；6 路均值 257.2 s、
  6/墙钟 76.3 sim/h、每通道效率 **97.8 %**（等于白拿）；12 路均值 298.8 s、
  持续喂满约 **145 sim/h**、每通道 **84.2 %**。每一档的所有 raw 都与参考**逐位相同**。
  **判据用"单条均值"，不要用 `n/wall`**：9 路那次一条通道 379 s、其余 247–283 s，
  `n/wall` 因此只有 80.4，比 6 路还低——那是 straggler 决定的批次完成时间，不是容量悬崖；
  同样工作在同一主机上墙钟会散 247–380 s。延迟敏感的单件用 6 路，批量用 12 路。

