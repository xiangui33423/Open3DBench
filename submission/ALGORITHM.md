# 第三版：大规模 HBT 优化与原生网表导出

本版保留官方四参数入口：CTS 后 DEF/SDC → HBT 与共享网协同优化 → 逐 die 硬层约束 GRT → `5_1_grt.odb`。在第二版的 HBT 坐标下降、192 条共享网和动态需求基础上，解除大设计中提前截断的 HBT 移动次数上限，改用原生 OpenDB 几何导出、流式 guide 校验与完整网分类复用，降低全量网表处理成本。几何目标用于选择方案，实际收益必须通过固定 DRT/DRC/STA 评估；实测记录见 `submission/VALIDATION.md`。

## 1. 既有 HBT 重定位

`hbt_optimizer.py` 根据每颗 HBT 的相连线网建立局部目标：相连线网 HPWL 之和。移除待优化 HBT 的 pin 后，每张 pin 包围盒给出 x、y 方向的两个端点。对所有端点排序，中间两个端点之间形成该轴的凸最优区间，两轴组合为最优矩形。

在当前点、当前点投影到最优矩形的位置、矩形中心与角点附近搜索合法 lattice 空位。每次只接受相连线网总 HPWL 严格下降且至少节省 0.1 μm 的移动，更新占用表和该 HBT 在全部相连线网中的 pin 坐标后再处理下一颗。默认做 2 轮坐标下降、搜索半径 2 个 pitch、最多接受 65,536 次移动。第二版的 4,096 次上限会让大设计在第一轮就停止；新上限不增加 HBT 数量，也不放宽任何布局约束。比较落点时先选 HPWL 最小，再选移动距离最短，最后按坐标排序，结果确定。

保护任何接触 CLOCK、非 SIGNAL、special 或封装引脚网的 HBT。HBT master 和连接保持不变，不改变非 HBT 元件、封装引脚或其连接。公开输入中的既有 HBT 为 COVER，应用移动时先改为 PLACED，再设置新位置，最后设为 FIRM；这些状态变化仅作用于允许修改的 HBT。

HBT pin 的位置随移动同步更新，多个 HBT 相连的网使用前一步更新后的坐标。最终几何节省按受影响线网集合计算一次，不重复计算共享线网。这一目标并非 RC 时延模型，也不保证每条相连子网单独变短。

## 2. 共享线网选择与动态需求

将 die 区域划分为默认 32×32 的网格。每条同 die 线网按 pin 包围盒分配 HPWL，建立类似 RUDY 的需求图。该图不包含详细布线阻塞和精确金属容量。

候选必须是非 special 的 SIGNAL 网，pin 数为 2–16，只有一个 OUTPUT driver，其他 pin 均为 INPUT，且所有 pin 属于同一 die。不处理 HBT/封装引脚网、既有 `_BOT`/`_TOP` 子网或已有 MLS 家族。原网 HPWL 至少 40 μm。

对 x、y 两轴分别在最大的 pin 间隙处切分，含 driver 的组为源端组。两个组内 HPWL 之和不得超过原网的 35%。初步评分为：

```text
score = (source_demand - target_demand) / (1 + source_demand)
        × trunk_length_um - local_group_hpwl_um - hbt_cost_um
```

默认 `hbt_cost_um=12.8` 是两次垂直连接的几何惩罚，不能作为 3 Ω/0.6 fF 的时延计算。

候选按初始评分降序、原网名升序处理。在准备放置时重新评估当前需求；每次成功共享后，从源 die 减去原网需求，加回两端局部子网，并在另一 die 加入新增主干需求。矩形更新后按需重建前缀和，使后续候选看到已承担的负载；不会一直使用共享前的静态需求图。

已有逐网 slack 可通过 `MLS_TIMING_CSV` 提供，表头为 `net,slack_ns`，名称与原 DEF 一致。默认禁止已标注且 slack 小于 0 ns 的网进行共享。未知 slack 的网仍参与几何评分，报告明确记录 `timing_source`。本版尚未自动提取 OpenSTA 逐网 slack，也没有布线后的时序反馈优化。

## 3. 两颗新 HBT 联合放置

保留输入 HBT 中心的 6.4 μm lattice 余数，所有新旧 HBT 均满足制造网格、die 边界和保守方形间距：任意两点必须满足 `|dx| >= pitch` 或 `|dy| >= pitch`。

对两个 pin 组，分别在坐标中位数和朝向另一组的包围盒投影位置周围搜索合法点。组合两端候选，直接最小化以下完整链路的 HPWL：

```text
HPWL(source group + HBT0) + Manhattan(HBT0, HBT1)
    + HPWL(sink group + HBT1)
```

这利用了 pin 包围盒内部的平坦最优区间，减少两端各自选最近站点产生的回头绕路。找不到两个相互合法的站点时放弃候选，不输出残缺家族。配置搜索半径为 0 时只检查原目标的最近网格点。

默认最多新增 384 颗 HBT、共享 192 条网，为初版共享规模的 6 倍；总 HBT 数仍限制在保守几何容量的 30% 以内。容量为 `floor(die_width/pitch) × floor(die_height/pitch)`。固定检查器按输入 lattice 计算，可能给出稍大容量；本版保留更严格预算，不消耗超额 HBT。

放置后若估计总线长超过原网的 130%，或扣除绕路后的评分低于阈值，就保留原网。报告记录原始 HPWL、共享链路估计、两 die 当前需求及 optional slack。

## 4. 子网与信号方向

底层网使用以下有向拓扑：

```text
driver group -- S0 BOT -- HBT_BOTIN -- S1 TOP -- HBT_TOPIN -- S2 BOT -- sink group
```

三个子网依次命名为 `<original>__MLS__S0__BOT`、`<original>__MLS__S1__TOP`、`<original>__MLS__S2__BOT`；新增实例名为唯一的 `LS_HBT_<id>`。上层网交换 BOT/TOP 和两种 HBT master 的顺序，使 Liberty 方向与信号方向一致。

原网中每个逻辑 pin 恰好转移到一个子网，原网删除。每颗新 HBT 的 BOT/TOP pin 分别接到对应 die 的子网。折叠 HBT 后应恢复原网的完整 terminal 集合和连通性。

## 5. 布线与运行开销

准备步骤先应用全部既有 HBT 重定位，再切分共享网和创建新 HBT。底层路由始终限制在 `metal2–metal10`，上层限制在 `metal11–metal20`，并对每条网应用 `set_net_routing_layers` 硬约束。两次路由使用同一份准备后网表与布局，合并 guide 后执行层归属、pin 覆盖和连通性检查。默认 FastRoute 拥塞迭代为 1 次（初版为 2 次）；固定评估器的详细布线仍为 `-droute_end_iter 2`，没有减少评测迭代。通过 `GLOBAL_ROUTE_ARGS` 可切回 2 次全局迭代。该迭代参数沿用第二版；本轮各候选均使用同一 GRT/DRT 迭代数，实际质量比较见 `VALIDATION.md`。

默认使用同一 OpenROAD 进程执行两次 die 局部路由。两 die 队列均非空时，`grt::reset_die_routing_pass` 只清空待路由队列，并逐网调用 OpenDB `clearGuides()` 清理暂存 guide，保留硬层约束。下一次 `global_route` 本身会清理并重建路由模型、资源网格和 GCELL，因此无须在两次路由之间重新解析整份底层 guide。此调用不会修改普通网属性、非 HBT 元件或 STA 状态。

任一 die 队列为空或使用旧二进制时，保留原 `read_guides` 交接流程及 `try/finally` 恢复的临时 special 标记；`GRT_PASS_RESET=legacy` 可强制运行该对照路径。`GRT_PROCESS_MODE=isolated` 可切回初版独立进程流程。最终仍恢复路由前记录的 TRACKS 与每条网的 signal type，完整读入合并 guide，再恢复层容量调整字段并发布 ODB。交接优化可能改变内部 guide IDs，但必须保持实际网表、布局、层范围和 guide 几何相同。

提交入口将层约束能力检查合并到 DEF 读取进程，并记录进程与内部阶段耗时。准备阶段默认在命令可用时使用 `grt::export_mls_manifest` 原生流式导出，旧二进制回退到 Tcl；`MLS_MANIFEST_EXPORTER=tcl` 可显式选择对照实现。两条路径保留同一 JSON schema、DBU 坐标、OpenDB 实例/网/pin 遍历顺序及全部普通 pin、HBT pin、封装引脚记录。名称中的引号、反斜杠、Unicode 和控制字符完整转义；中心和 BPin 平均坐标按 Tcl 整数除法向下取整，负半整数也一致，避免 C++ 默认向零截断造成坐标差异。HBT 优化只为实际包含 HBT 的网复制 pin 数据，其他网保持只读，避免大用例全量深拷贝。

严格 guide 诊断只物化其原本检查的 `_BOT`/`_TOP` 网的矩形与相关 DEF 组件位置，保留这些网的全部普通/HBT pins 和原始矩形顺序。同层和跨层连通分量合并到一次矩形对扫描，pin 覆盖结果复用；原覆盖 margin、同层一 DBU 接触容差、相邻层无容差、连通分析数量限制及全部 strict failure 条件保持不变。逐层合法性检查仍遍历全部 guide，网分类和列表导出使用全量流式 DEF 解析。

逐 die 流程的列表导出同时产生完整分类缓存，逐层检查通过可选 `--classification-cache` 复用。读取前验证整数 schema 版本、完整 DEF 的 SHA-256、保留插入顺序的完整 payload SHA-256，以及每个网名和分类标签的类型；缺失、过期或损坏的缓存回退到完整解析。导出前后核对 DEF 哈希并原子发布缓存，缓存放在结果工作目录，不复制到提交的网列表目录。独立运行检查器时默认不使用缓存。

最终 ODB 必须为当前运行新生成的文件，并由 OpenROAD 重新打开验证。详细布线由固定评估器执行，运行时间比较使用提交入口耗时，不使用评估器包含 DRT 的墙时。内部 `grt.prepare` 包含 `mls.*` 子阶段，各项细分耗时不能直接相加。

## 6. 验证与消融

Python 检查新旧 HBT 的数量、边界、制造网格、lattice 余数与间距，以及原始 terminal 集合、子网图连通性、命名和信号方向。Tcl 应用后检查所有非 HBT 的 master、位置、方向、placement 状态，以及封装引脚几何与连接。

使用固定检查器验证 canonical DEF/guide。全部公开用例的准备阶段检查与完整 GRT/DRT/STA 分开记录；几何检查通过不能替代正式评测。

51 项 Python 回归测试覆盖共享与重定位约束、封装引脚分类、严格检查边界和缓存回退，包括普通 pins 分属不同组件、矩形顺序、层名大小写、过期 DEF、损坏 payload 和错误 schema/类型。另以 1,000 组随机几何对照旧实现，完整诊断字段及 3D 组件 ID 一致。

原生导出在官方 `20260914` 镜像中与 Tcl 对照：bp_fe 实际输入的 37,248 个网、113,496 个 pins，以及转义、负半整数、缺失几何、混合 die BPin 等边界样例均一致；bp_quad 使用相同输入 ODB 对照此前保存的 Tcl manifest，1,363,004 个网、4,158,170 个 pins 的全部记录及顺序一致。微基准中 bp_fe 导出为 Tcl 3.138 秒、原生 0.186 秒；bp_quad 原生单线程导出 9.745 秒，加载与完整对照总墙时 62.898 秒，其中没有重跑 Tcl 导出。

使用既有第二版官方容器的 bp_fe/bp_quad 产物对照严格诊断，完整诊断输出与退出状态一致；全量分类、违规结果、CLI 输出和三份网列表也一致。微基准中严格诊断耗时分别从 2.594/96.234 秒降至 0.940/29.575 秒，bp_quad 峰值 RSS 从约 7.08 GiB 降至 0.50 GiB；复用分类缓存的 bp_quad 逐层检查从流式解析的 59.819 秒降至 24.721 秒。以上是在共享宿主上测量各工具的微基准，不能代替完整入口耗时或固定 DRT/DRC/STA 的质量与评分结果；证据分别保存在 `reports/optimization_v3` 下的 `native_export`、`diagnostics` 和 `classification_cache`。

`relocation_enabled=false` 可关闭既有 HBT 重定位；`max_new_hbts=0` 可运行仅重定位方案。`dynamic_demand` 和 `joint_site_placement` 分别控制需求更新与联合落点选择。`MLS_ENABLE=0` 则关闭所有准备修改，提供相同提交接口的布线基线。这些开关用于消融和同环境比较，不依赖公开 case 名称。
