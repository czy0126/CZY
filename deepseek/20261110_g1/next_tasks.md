# DeepSeek下一执行任务：G1原生驱动布局与G2磁件接口

先读 `hardware/dcx_main/g1/driver_eco_review.md`。当前分支feat/d1-fab-package，基线d89f838；不要把其他分支旧偏置文件当作当前已有交付。

1. 原生候选：`hardware/dcx_main/g1/dcx_main_board_g1_driver_eco.eprj2`。API已移动7件并save=true，但关闭重开后接口读取超时，未验收。先在独立会话打开候选，分步读取项目/PCB/7器件坐标/全量焊盘；读取完成再运行`audit_driver_eco.py`。`--preview`只预测几何，绝不是验收。不要绕过断言或把reopened_readback改true。
2. 真实下一CAD交付：核对U2供电电容C103/C104的实际值、封装与VCC12/PGND归属；围绕U2/QH/QL/R4/R5完成短门极去回路、自举C5/D_BT与局部回流。保持开关节点SW与敏感检测隔离。发布实际走线和原生DRC原始项；不能用端点直线距离宣称回路电感合格。
3. 磁件临时端子：24个概念PAD仅供G1，必须用自研Maxwell几何与绕组出口工艺解决包络偏差和DOT；Lr当前9mm原生端距与概念40mm端距冲突。先冻结一套设计自有实体端子候选及机械剖面，别为了清零而移动概念点冒充厂家实脚。

审核修复：`make_g1_report.py`已真实逐脚检查错网、未知脚、缺脚、重复脚异网，原count=0常量已删除；同封装不同网络包围盒重叠单列。新测试用错误网和漏脚注入验证，不能删掉这些检查。

回复要求：对源代码/具体节点给出可执行修正，区分已运行与建议。没有EDA执行能力时只交建议，不声称修改CAD。制造保持NOT_FOR_FAB。禁止扩大为另一套报告框架。
