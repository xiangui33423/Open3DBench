# 初步方案：金属层共享与 HBT 增量布局

本版本实现赛题要求的端到端接口：读取 CTS 后的 DEF 和 SDC、选择共享线网、切分子网、放置新增 HBT，并调用具有逐网金属层限制的 FastRoute，输出 `5_1_grt.odb`。这是可验证的第一版原型。拥塞与线长均使用几何估计，不能据此宣称 TNS、WNS、DRC 或最终得分已经提升。

## 1. 共享线网选择

将 die 区域划分为默认 32×32 的统计网格。对每个可识别所属 die 的线网，根据 pin 包围盒面积分配 HPWL，构建类似 RUDY 的二维需求图。该图表示相对需求；它没有扣除布线阻塞，也没有计算实际金属层容量。用矩形差分和前缀和建立、查询需求，避免逐网扫描所有网格。

候选必须满足：

- 为非 special 的 SIGNAL 网，且 pin 数为 2–16。
- 所有 pin 位于同一 die，只有一个 OUTPUT driver，其余为 INPUT。
- 不含 HBT 或 package pin，不修改既有 `_BOT`/`_TOP` 子网或已经切分的 MLS 家族。
- HPWL 至少 40 μm，且 pin 可以形成两个较紧凑的空间组。

对 x、y 两个轴分别排序，在该轴最大的 pin 间隙处切分，含 driver 的组作为源端组。两个组内的 HPWL 之和不得超过原网 HPWL 的 35%。两个组的坐标中位数为 HBT 目标位置。

候选评分为：

```text
score = (source_demand - target_demand) / (1 + source_demand)
        × trunk_length_um - local_group_hpwl_um - hbt_cost_um
```

默认 `hbt_cost_um=12.8` 是两个垂直连接的几何惩罚参数，不是 3 Ω/0.6 fF 的时延模型。按评分降序、原网名升序确定处理次序，无随机结果。

## 2. 时序信息的使用与限制

已有逐网 slack 时，可设置 `MLS_TIMING_CSV`，文件表头为 `net,slack_ns`，名称必须与原始 DEF 网名一致。默认禁止对 slack 小于 0 ns 的已标注线网进行共享。未知 slack 的线网仍参与几何评分，报告中的 `timing_source` 会明确说明是否有提供 slack。

当前版本没有自动从 OpenSTA 提取逐网时序裕量，没有基于 HBT RC 预测共享后的时延，也没有执行布线后的时序反馈。这部分是后续提高得分的主要工作。正式 TNS/WNS 必须由固定评估器测量。

## 3. HBT 布局

保留已有 HBT 位置。根据输入 HBT 的中心坐标推导 6.4 μm lattice 的余数；新增 HBT 使用相同的 DEF origin 余数，满足正式评估器的固定 pitch-grid 要求。位置同时对齐制造网格，整个 HBT master 位于 die 内。

在目标位置周围默认 ±8 个 pitch 范围内枚举站点，按曼哈顿距离、x/y 索引排序，选择最近的合法站点。空间哈希检查已有与新增 HBT。任意两个 HBT 必须满足 `|dx| >= pitch` 或 `|dy| >= pitch`，采用保守的方形间距避免只检查欧氏距离而遗漏 cut-spacing 冲突。

新增数量上限为 64，最多选择 32 条线网，并限制总 HBT 数在保守估计容量的 30% 内。保守容量为 `floor(die_width/pitch) × floor(die_height/pitch)`；固定评估器可能按原网格余数算出略大的容量，原型仍保留较严格的预算。若已有 HBT 已超过预算，本版本不增加 HBT。

放置后重新估计两端局部线段与另一 die 的主干 HPWL；若估计总线长超过原网的 130%，或扣除新增绕路后评分低于阈值，则放弃此候选。找不到合法站点时也保留原网。

## 4. 子网连接

以下为底层线网的共享拓扑：

```text
driver group -- S0 BOT -- HBT_BOTIN -- S1 TOP -- HBT_TOPIN -- S2 BOT -- sink group
```

三个子网分别命名为：

```text
<original>__MLS__S0__BOT
<original>__MLS__S1__TOP
<original>__MLS__S2__BOT
```

新增实例命名为唯一的 `LS_HBT_<id>`。源端使用 `HBT_BOTIN`，回到源 die 的连接使用 `HBT_TOPIN`，使 Liberty 的输入输出方向与信号方向一致。对于上层线网，BOT/TOP 和两个 master 的顺序互换。

原网中的每个逻辑 pin 恰好转移到一个子网。原网删除；每个 HBT 的 BOT/TOP pin 分别连接对应 die 的子网。折叠两个 HBT 后应恢复原网的完整 terminal 集合。

## 5. 全局布线

通过现有 `GRT_PREPARE_TCL` 接口在同一个 OpenDB 中应用一次修改。流程保存共享的 `4_grt_input.odb/.def`，让底层、上层和最终合并进程使用同一份网表与布局。

底层限制在 `metal2–metal10`，上层限制在 `metal11–metal20`，并通过 `set_net_routing_layers` 对每条网强制限制。两次布线的 guide 合并后进行 layer ownership、pin 覆盖和连通性检查，再导入最终 ODB。未使用支持这些限制的 OpenROAD 时，提交入口会报错，要求构建提供的 GRT 源码。残余拥塞采用公开流程的 `-allow_congestion` 交给固定详细布线评估器处理。

## 6. 正确性验证

Python 计划验证检查 terminal 集合、HBT 两端连接、家族图连通性、命名、数量预算、die 边界、制造网格与间距。Tcl 应用后检查所有非 HBT 元件的 master、位置、方向和状态，以及 package pin 的几何与连接。提交入口确认最终文件为本次运行新生成的有效 ODB，并再次用 OpenROAD 打开。

最终合法性应另外使用镜像中的 canonical snapshot 和 `validate_submission.py` 检查。完整评测还需固定 DRT/DRC/STA；源码检查、单元测试或 GRT 输出都不能替代这一步。

## 7. 后续工作

- 自动获取逐网 slack 和实际拥塞图，建立共享前后 RC 时延预测。
- 增加多分支的子网切分、HBT 协同重定位和布线反馈。
- 在 8 个公开用例上测量正式指标，搜索参数并保留逐次实验结果。
- 用独立用例检查泛化，避免依赖公开 case 名称。
