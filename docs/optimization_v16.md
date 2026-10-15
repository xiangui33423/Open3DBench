# v16：以WNS/TNS为主的固定两组优化

本次以实际官方 **24.01565788837513（24.02）** 的原成功五例为评分对照，同时与v15做固定引擎对照。选择固定两组共享分支和有界新进程回退作为当前主方案；固定高扇出分组改变了连接族及预算分配，逐接收端几何代理约束仍执行。具体算法见包内 `ALGORITHM.md`，冻结源位于 `reports/optimization_v16/fixed2_safe`。

| 用例 | 官方 TNS / ns | v16 TNS / ns | 官方 WNS / ns | v16 WNS / ns | 官方 DRC | v16 DRC | 质量证据 |
|---|---:|---:|---:|---:|---:|---:|---|
| bp_fe | -6544.23 | -6258.36 | -3.24734 | -3.33495 | 1811 | 1183 | 新DRT2/RCX/STA |
| bp_be | -6624.01 | -6205.77 | -3.80213 | -3.52743 | 4701 | 4093 | 新DRT2/RCX/STA |
| bp | -159108.00 | -144948.00 | -22.53800 | -21.55960 | 13448 | 11581 | 新DRT2/RCX/STA |
| swerv_wrapper | -1843.43 | -1849.42 | -1.55263 | -1.55310 | 14232 | 14343 | 复用v15完整评测 |
| bp_multi | -83525.90 | -87036.50 | -16.65100 | -16.13070 | 4887 | 3562 | 新DRT2/RCX/STA |


同五例TNS损失合计 **257645.57 → 246298.05 ns（减少4.4043%）**，WNS损失合计 **47.79110 → 46.10578 ns（减少3.5264%）**，DRC总数 **39079 → 34762（减少11.0469%）**。平均TNS为 **-49259.61 ns**，平均WNS为 **-9.221156 ns**，平均详细线长为 **3810103.058 μm**。相对v15，TNS/WNS损失减少4.6749%/3.1617%，DRC减少0.2496%。各指标独立对比，不将原始TNS和WNS相加组成评分代理；新官方分数和27分目标仍未验证。

FE WNS从-3.24734降至-3.33495 ns，损失增加2.6979%；multi TNS从-83525.90降至-87036.50 ns，损失增加4.2030%。SW相对原官方也略退。BP的TNS/WNS明显改善，是五例聚合收益的主要来源；不能把整体改善表述为每例或每接收端都改善。

完整质量证据为四例新固定DRT2/RCX/STA加SW的严格v15复用，另外八例均有新GRT及canonical合法性。SW的提交原ODB、原始GRT guide与已完整评估源匹配，并核验保留档案和原始SHA；复用证据在 `fixed2_safe_swerv_reuse_validation.json` 及 `quality_source_pairs/capacity75/swerv_wrapper/`。本轮没有为另外三例补充完整STA，也没有验证服务器三例缺输入DEF的原因已修复。

| 用例 | v15 均值 / s | fixed2_safe 均值 / s | 耗时变化 |
|---|---:|---:|---:|
| bp_fe | 17.060 | 14.655 | -14.10% |
| bp | 110.768 | 117.507 | +6.08% |
| swerv_wrapper | 38.843 | 38.772 | -0.18% |

该表来自 `reports/optimization_v16/paired_entry_runtime/fixed2_safe/20261014T131339Z-6c970a69/record.json` 的12条完整入口记录，8线程、每例每版本两次、正反顺序。SW视为基本持平，BP约慢6.08%需作为明确代价。共享宿主和RAM工作区观测不等于服务器Runtime，不含固定DRT耗时；没有由此计算官方分数。

quad 2线程覆盖触发原生GRT-0228后，以新进程、同原CTS和原v15配置回退完成，耗时1090.320秒；另一个guarded覆盖观测为547.222秒且无重试。两次不是公平成对计时，但显示重试的实际耗时风险。quad原始ODB/GUIDE匹配v15历史原始SHA并通过新canonical合法性；这不是新增quad完整时序。

本轮也完成了保留原分组顺序、再按被动RC代理筛选2/4组的 `guarded_reduction_lazy` 对照：同五例TNS损失合计254146.41 ns，WNS损失合计46.62085 ns，DRC 34916；相对原官方TNS/WNS损失减少1.3581%/2.4487%。该方案的五例质量来自已完成原guarded评测和SW，lazy自身有八例新GRT/合法性及原ODB/GUIDE双字节等价证明，未将复用标作新的DRT。其自身v15配对入口FE约慢10.37%、BP约慢16.99%、SW基本持平。固定两组方案在本次五例TNS/WNS汇总及FE/BP入口开销方面更合适，因此作为当前提交候选；这不意味着每例都有相同排序。两个候选共24条完整入口运行均已核对原始产物身份，完整记录为 `reports/optimization_v16/paired_entry_runtime_queue/20261014T131329Z-f2e3ff84/record.json`。

执行指纹为 `01a5028791cae37320e3de954152cd02f68dfa030af95a888477d28c661951df`（41文件）。最终主目录238项生产和7项支持回归均通过，合计245项；日志为 `reports/optimization_v16/FINAL_PRODUCTION_TESTS.log` 和 `FINAL_SUPPORT_TESTS.log`。ZIP成员、入口权限、逐执行文件SHA及发布ZIP SHA见 `docs/optimization_v16_metrics.json` 的发布身份记录。`SUMMARY.json` 中fixed2_safe条目是本方案证据，其他中断或未完成实验不纳入本方案聚合。

原v15六份文档的精确备份已存于 `docs/history/v15_before_v16/`，各原路径及SHA列于 `archive.json`。继续保留 `docs/optimization_v15.md`、`docs/optimization_v15_metrics.json` 和旧v14/v15 ZIP；包内历史算法使用 `HISTORY_V15_ALGORITHM.md` 保存，当前README/VALIDATION只描述本次版本。

选定源码在宿主3.10.12与官方镜像3.12.3下对BP/multi完整规划一致：选网顺序、HBT位置、子网、重定位和apply Tcl相同，并与实际保留的新GRT计划一致。仅部分诊断浮点值有极小差异；该兼容性检查不是新增物理或时序评估，范围及源输入证明见 `reports/optimization_v16/selected_python_compatibility/SUMMARY.json`。

2026-10-15 发布复核：当前提交包为 [`submission_v16_fixed2_safe_revalidated_20261015.zip`](../submission_v16_fixed2_safe_revalidated_20261015.zip)，SHA256 `ea15d6120ba84ba70b558b48862215eba39211722e7f5c5334b0d7a38056d604`，328261字节、73成员，CRC通过。该包与原发布包字节相同，41个执行文件、入口及评估辅助程序再次核验一致；重命名复核不表示新物理评测或新官方得分。历史包名和审计保留在结构化发布记录中。
