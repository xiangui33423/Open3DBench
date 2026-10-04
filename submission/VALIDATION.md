# 第四版官方容器验证

验证日期：2026-10-04（Asia/Shanghai）。本版默认采用带接收端路径保护的多分支 MLS：不适合跨层的接收端保留在源端子网直接连接，其他接收端按几何组共享上层主干。仍最多新增 384 颗 HBT，不移动普通元件、不修改固定评估器、RCX 模型或详细布线轮数。

## 真实质量结果

对照为用户 `result/` 中实际服务器运行的第三版。其提交 52 个文件与 Git `6934cb05` 逐字节一致，5 个成功用例的输入 DEF 与本地公开数据一致。第四版使用官方 `20260914` 镜像重新进行完整 DRT/DRC/STA，没有复用历史质量指标。

下表“变化”为指标绝对值的相对变化：负数表示减少。TNS/WNS 以负 slack 的绝对值减少衡量改善；DRC/线长为增加即代价。它们不能直接转换为官方总分。

| 用例 | 指标 | v3 服务器 | v4 官方容器 | 绝对值变化 | 本轮线程 | 实际 DRT 迭代 |
|---|---|---:|---:|---:|---:|---:|
| bp_fe | TNS (ns) | -8253.17 | -6562.16 | -20.49% | 16 | 2 |
| bp_fe | WNS (ns) | -3.33894 | -3.2671 | -2.15% | 16 | 2 |
| bp_fe | DRC | 4059 | 4084 | +0.62% | 16 | 2 |
| bp_fe | 线长 (μm) | 1342836.13 | 1348627.87 | +0.43% | 16 | 2 |
| bp_multi | TNS (ns) | -88268.7 | -82031.1 | -7.07% | 16 | 2 |
| bp_multi | WNS (ns) | -15.0036 | -16.8956 | +12.61% | 16 | 2 |
| bp_multi | DRC | 13454 | 13395 | -0.44% | 16 | 2 |
| bp_multi | 线长 (μm) | 3823039.31 | 3876927.61 | +1.41% | 16 | 2 |

`bp_fe` 的 TNS 绝对值减少 **20.49%**，WNS 改善 **2.15%**；DRC 增加 **0.62%**，线长增加 **0.43%**。这是有取舍的时序优化，不能描述为所有指标同时改善。

`bp_multi`：TNS 绝对值减少 7.07%，WNS 绝对值增加 12.61%，DRC减少 0.44%，线长增加 1.41%。其中 WNS 回退说明几何路径保护仍不足以保证实际最坏时延；本版主要优化 TNS，不能确认其综合得分优于第三版。此结果与 FE 分开报告，不将单例收益推广为所有用例收益。

官方总分尚需服务器重新评测。旧服务器的 `success_rate=0.625`，另外三例 `ariane133`、`ariane136`、`bp_quad` 报 `Input DEF file not found`；现有结果没有 ingestion 标准输出或输入目录清单，尚不能确定失败原因，也没有证据证明本版解决了服务器输入缺失。

## 全部公开用例覆盖

最终同一默认配置已通过全部 8 个公开用例的 GRT、guide 与官方 canonical 合法性检查，errors、warnings、超额 HBT 均为 0。

| 用例 | 完成范围 | 本机入口秒数 | HBT 总数 / 免费额度 | errors / warnings |
|---|---|---:|---:|---:|
| bp_fe | 完整 DRT/STA | 20.586 | 1533 / 1729 | 0 / 0 |
| bp_be | GRT/合法性 | 33.434 | 1488 / 2176 | 0 / 0 |
| ariane133 | GRT/合法性 | 116.006 | 4409 / 7300 | 0 / 0 |
| ariane136 | GRT/合法性 | 116.710 | 4429 / 7300 | 0 / 0 |
| bp | GRT/合法性 | 185.986 | 4231 / 5880 | 0 / 0 |
| bp_multi | 完整 DRT/STA | 68.220 | 3456 / 4687 | 0 / 0 |
| swerv_wrapper | GRT/合法性 | 48.095 | 1662 / 4087 | 0 / 0 |
| bp_quad | GRT/合法性 | 600.122 | 28219 / 45630 | 0 / 0 |

本轮 GRT 和固定评估均使用每任务 16 线程，调度器限制并发总量为 32。入口时间包含加载、MLS、GRT、提交侧检查与最终 ODB 重开，不包含编译、官方 snapshot/合法性检查或 DRT/STA。服务器 v3 的提交请求为 32 线程，本地系统负载也不同，因此不能用两处墙时直接声明服务器加速比例。

最终质量覆盖限于表中完成完整 DRT/STA 的用例，其余用例仅验证 GRT 和合法性。公开数据上的结论不等于隐藏用例或正式总分提升。

## 为什么需要接收端保护

未保护的多分支候选在 `bp_fe` 得到 TNS -8074.66 ns、WNS -4.14959 ns：平均指标稍好，却使 WNS 比 v3 恶化 24.28%。对 `net1194` 的最终 SPEF 追踪发现，原关键接收端改善了，但 `_2290_/A` 的路径电阻由约 965 Ω 增到 1682 Ω，形成新的瓶颈。

最终方案将该网 214 个接收端保留在 S0，489 个接收端使用跨层分支。`_2290_/A` 恢复至约 981 Ω，原关键 `_3465_/A2` 仍约 1704 Ω，比 v3 低约 28%。全 703 个接收端共同前缀从未保护方案的约 1030 Ω 降至约 17 Ω，负载不再全部先通过同一长主干。该网互连电容仍由 v3 的约 396.7 fF 增至约 525.0 fF，不能把收益解释为电容减少。新最坏路径已经换到其他网络。

规划器的逐接收端完整 Manhattan 路径上限为原直接路径的 1.05 倍加 6.4 μm；不满足条件的接收端留在 S0。校验器从原终端与 HBT 坐标独立重建路径，同时检查终端次数、方向、树连通性、单驱动、边界、间距和实际预算。候选排序的加权距离不是 STA 或真实电阻模型。

## 参考文献与实际评估模型

本轮参考赛题的 MLS、Open3DBench、H3D、CUGR 和 FastRoute 文献，文献链接及实现边界见 `ALGORITHM.md`。没有训练 GNN、复现论文全部优化器或将论文百分比作为本提交收益。

实际官方 `6_report.log` 加载的是输入平台 `nangate45_3D.rules`，并非同目录的 `rcx_patterns.rules`。前者的默认宽度电阻表在奇数/偶数层分别使用相同系数，与 LEF 的理想层电阻比例不同。例如最终 384 μm metal15 线段按该 RCX 规则提取得到 974.068 Ω；其他层的最终 DEF/SPEF 数值也完成交叉核对。因此，LEF 中 metal15 与 metal11 的 40 倍单位电阻差异不能预测本轮最终 STA。没有修改这些规则或固定 evaluator。

扩大容量、固定 M4 下界、自动/选择性电阻代价、局部 guide patch、统一 via 代价尺度及未保护的多分支等候选，都以完整固定评估筛选。它们的完整指标留在 `reports/optimization_v4/quality_comparison.md`；退化候选未启用为默认。普通网选层/RA 开关默认关闭；针对旧 HBT 重定位和双 HBT 共享的另一项路径保护也保持关闭，避免混合未共同验证的策略。

## 运行实现与回归

单进程默认直接加载 DEF，省去初始 ODB 写入和重读，准备后的 ODB 检查点默认省略；最终 ODB 仍完整写出并独立重开。完整分类缓存以固定批次生成 JSON/摘要，两项只读 guide 检查并行，任一失败仍阻止发布。

纯性能消融曾在全部 8 例保持 canonical DEF/guide 一致，合计入口从 1051.176 s 到 1041.397 s，减少约 0.93%。因此本轮主要收益是上面的真实时序改善，不将检查局部加速包装成整个流程的大幅加速。

FastRoute 每次重建技术层缓存，避免 bottom→upper 路由时保留上一层域的前缀。原生选择性 RA 接口保留为默认关闭的实验选项；最终多分支算法复用同一已验证二进制，不需要修改固定详细路由器。

完整生产回归 **112/112 通过**，含 18 项多分支/接收端保护回归：终端丢失、树拓扑与信号方向、超预算、单远端组、危险路径和特殊字符 Tcl 执行等。另有直接调用未修改官方 validator 的正负例；这些集成材料保留在本地报告中。

## 身份、构建与证据边界

- 官方 image ID：`sha256:eb877c5e1f4d94881992b55d474ab189ab3308dac3f38208c5c8b0dd7544bd98`。
- OpenROAD base commit：`305d3ba2ddfd00591924cc586ad408179f566afe`；固定 evaluator SHA256：`43b4b9a524ed6004a16259d3802519e9de5190f8ae0195f4345aac2806e940d3`。镜像固定文件 checksum 通过。
- 最终公开 GRT binary SHA256：`4ab6dee5479eca55b8e43af0b253c6126324afaeaa49b2344862a939a637c765`。它在已验证完整官方构建的独立副本中增量编译，16 线程、435.809 s；不是全新构建。9 个实际 overlay 文件与最终源码逐一匹配，旧父构建与旧二进制保持不变。
- 新二进制的原生/Tcl 导出对照覆盖 37,632 个网、114,264 个 pins，以及特殊名称、负半整数坐标和封装引脚等真实 OpenDB 边界样例。
- 平台来自用户输入目录 `platforms/nangate45_3D`。guarded `bp_multi` 运行期间捕获的实际 materialized 平台 213 文件与输入逐一 SHA256 一致；guarded `bp_fe` 的临时平台副本在官方评估结束时已清理，未保存其全部 213 文件的历史逐文件快照。FE 的固定程序身份、冻结运行源码、实际加载路径、两份 DRT 日志、最终 STA 和 metrics 已独立核验；不将其他运行的平台快照冒充为 FE 历史证据。
- 最终 ZIP 仅携带运行源码、9 文件 GRT overlay、配置、文档和验证工具，不携带输入网表、平台、二进制、缓存或评测结果。打包审计须确认运行源码与冻结受测版本逐字节一致；后续文档和支持工具的差异单独列出。

原始证据均在本地 `reports/optimization_v4/`，未放入提交包：

| 证据 | 相对该目录的路径 |
|---|---|
| 服务器原始分析与全部候选质量 | `server_analysis.json`、`quality_comparison.json` |
| 最终 bp_fe 完整评估 | `experiments/20261004T051458Z-94c60a79/experiment.json` |
| 最终 bp_multi 完整评估 | `experiments/20261004T053246Z-0d1425aa/experiment.json` |
| 其余六例 GRT/合法性 | `experiments/20261004T053258Z-d1466919/experiment.json` |
| 全部八例独立审计 | `multi_branch_guarded/FINAL_ALL8_AUDIT.json` |
| FE 独立核验及真实路径机制 | `multi_branch_guarded/BP_FE_COMPLETE_EVALUATION_AUDIT.json`、`multi_branch_guarded/BP_FE_RESET_TREE_DIAGNOSIS.json` |
| multi 完整质量独立审计 | `multi_branch_guarded/BP_MULTI_COMPLETE_EVALUATION_AUDIT.json` |
| RCX 模型核查 | `multi_branch/RCX_RESISTANCE_MODEL_REVIEW.md`、`multi_branch/RCX_SPEF_DEF_MATCHES.json` |
| 运行期间平台快照 | `multi_branch_guarded/PLATFORM_DURING_EVALUATION.json` |
| 构建/导出与生产回归 | `ra_cache_fix/build.json`、`ra_cache_fix/export_parity/`、`multi_branch_guarded_merge/production_regression.log` |
| 最终提交包内容与受测源码对照 | `package_audit.json` |

复现入口见 `support/README.md`。此前版本的验证记录保留在 Git 历史及 `reports/optimization_v3/`；`OFFICIAL_VALIDATION.md` 和 `HISTORY_V2.md` 是历史记录，不代替本轮实际结果。
