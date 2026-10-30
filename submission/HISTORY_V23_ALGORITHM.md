# v23：上层 HBT 信号网选层

在 v22 默认单进程双 die 路由中，对上 die 的非时钟 SIGNAL 网络，若其没有封装 BTerm、连接实际 HBT_BOTIN/HBT_TOPIN master，且不含 CLOCK/POWER/GROUND master pin，将原有路由下界与 metal12 取较大值。仍保留原生 metal11 pin access；既有更严格下界、上界和 die 层归属继续生效。若原上界低于 metal12，则不应用新规则。

时钟集合来自当前 STA 时钟查询，HBT 判断来自实际 master。规则不读取用例名、评测分数或历史关键路径。排除网的路由范围受保护，但全局重新布线可能改变其具体走线，因此不能把范围保护等同于几何或时序不变。

高扇出共享网最多使用两个接收端分组；新增 HBT 上限仍为 min(384, floor(0.30 × 规划网格容量) − 已有 HBT 数)，负值取零，最多选择 192 个共享网。HBT 规划、6.4 μm 网格、几何路径保护、候选顺序和合法性判断继承 v22。八例完整 MLS 计划相同，五个计分例的底 die guide 也逐网相同；上层负载变化仍可能影响底层驱动单元时序。

底 die 使用 metal2–metal10，上 die 使用 metal11–metal20。普通高扇出网的既有选层规则不变；容量折减仍为 metal2=0.75、metal3=0.65，其余 0.50。v22 独立规划 CLI 的 GC 调度和紧凑 JSON 写出继续保留。

新策略只增加默认单进程路径的一段 Tcl 逻辑及诊断计数；显式隔离进程调试路径沿用旧策略。原生 C++、输入、SDC、评测器和详细布线迭代设置均未修改。原有 GRT-0228/GRT-0254 新进程重试、guide 层归属与连通性检查、ODB 重开和成功后发布机制保留。历史策略见 HISTORY_V22_ALGORITHM.md；实测取舍见 VALIDATION.md。
