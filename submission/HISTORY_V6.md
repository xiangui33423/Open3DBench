# 第六版验证记录

记录日期：2026-10-05（Asia/Shanghai）。选定的 metadata_protected_cache 全部八例精确产物与 Runtime 审计已 PASS；第一轮 runtime_fast 记录作为已完成的阶段对照保留。该方案已推广到生产，源码绑定的标准回归 155/155 通过；最终包身份以包外审计为准。M4 WNS 候选已正式拒绝，M3 仅为未纳入本版的包外研究。本版不声称已经达到 30 分。

## 官方服务器基线与新目标

已取得的第五版官方服务器成绩为 **18.404208740850777 分**，成功 **5/8**。成功用例为 bp_fe、bp_be、bp、bp_multi、swerv_wrapper；这五个服务器提交 ODB 的 SHA 均与本地第五版受测提交一致。此身份核验不代表重新执行了服务器最终 DRT/STA。

ariane133、ariane136、bp_quad 的服务器记录为 `Input DEF file not found`。实际 ingestion 命令、尝试的输入路径及服务器目录证据仍缺失，根因未证实，问题未证明解决。本地八例合法或下载文件完整，不能证明服务器输入发现流程已修复。

第六版优先优化完整算法入口 Runtime 和 WNS，保持 TNS 负损失、最终 DRC、详细布线线长、HBT 总数与超额数量不退步。当前采用逐例保守质量门槛，并保留逐例完整入口不超过 v5 同配置重跑结果 1.7 倍的上限。低于上限与实际加速分别判断。

尚未取得精确服务器评分归一化函数及完整缺失用例政策，不从权重、局部百分比或成功率外推总分。30 分仍是目标。尚未取得第六版新的官方服务器分数；三例失败根因仍未证实，也没有证明已解决。

## 第一轮 Runtime：全部八例已通过独立审计

基线为冻结 v5，候选为 runtime_fast。两次运行均为同官方 20260914 镜像、相同输入与完整平台、32 线程、单任务。时间取外部 **grt.wall_seconds**，包括启动、collateral 选择、输入准备、MLS、GRT、提交侧完整检查、ODB 重开和发布；不含预先编译、后续官方 snapshot/合法性检查和固定 DRT/STA。内部 manifest 不覆盖全部入口，不能用于替代下表。

| 用例 | v5 完整入口 / s | runtime_fast 完整入口 / s | 倍率 | 耗时减少 |
|---|---:|---:|---:|---:|
| bp_fe | 22.077 | 20.890 | 0.9462× | 5.38% |
| bp_be | 35.737 | 32.330 | 0.9047× | 9.53% |
| ariane133 | 120.576 | 87.319 | 0.7242× | 27.58% |
| ariane136 | 121.535 | 89.193 | 0.7339× | 26.61% |
| bp | 207.725 | 153.839 | 0.7406× | 25.94% |
| bp_multi | 76.224 | 64.522 | 0.8465× | 15.35% |
| swerv_wrapper | 50.327 | 49.574 | 0.9850× | 1.50% |
| bp_quad | 643.745 | 646.907 | 1.0049× | -0.49% |

八例合计 **1277.946 → 1144.574 s，减少 10.44%**。最大逐例倍率 **1.0049×（bp_quad）**，全部低于 1.7×。bp_quad 完整入口增加 3.162 s（0.49%）；规划/检查子阶段更快没有保证这一例整体加速。共享宿主背景负载可能变化，上表是同配置完整入口观测，不是服务器时间保证。

独立报告 RUNTIME_PARITY_AUDIT.json 为 PASS，绑定两次冻结源码、实际二进制、输入 DEF/SDC、完整平台 SHA、线程和任务数；八例提交 ODB、canonical ODB/DEF/guide、MLS 计划以及 HBT 指标全部一致，并通过官方合法性检查。每例检查 1.7 倍上限，不用合计值掩盖逐例超限。

## 选定 Runtime 方案：metadata_protected_cache 全八例 PASS

metadata_protected_cache 在 runtime_fast 基础上组合时钟 signal type 快照、原生层 setter 分派和只读 MTerm 保护判定缓存，仅修改两份 Tcl。该候选自身的 METADATA_PARITY_AUDIT.json 于 2026-10-05 03:20:59 UTC 完成 PASS；冻结实验为 metadata_cached_runtime/20261005T020515Z-6d7d4a9e，source.zip SHA256 为 f84e92cc604de40d069090a72a438d9b1a57962cb6fe5ff768bc470283174483。旧 metadata_fast 预备计划已替代且未执行，未拿它的证据替代当前候选。

| 用例 | v5 完整入口 / s | metadata_protected_cache 完整入口 / s | 倍率 | 耗时减少 |
|---|---:|---:|---:|---:|
| bp_fe | 22.077 | 20.191 | 0.9146× | 8.54% |
| bp_be | 35.737 | 32.055 | 0.8970× | 10.30% |
| ariane133 | 120.576 | 85.127 | 0.7060× | 29.40% |
| ariane136 | 121.535 | 86.289 | 0.7100× | 29.00% |
| bp | 207.725 | 148.331 | 0.7141× | 28.59% |
| bp_multi | 76.224 | 63.546 | 0.8337× | 16.63% |
| swerv_wrapper | 50.327 | 48.457 | 0.9628× | 3.72% |
| bp_quad | 643.745 | 603.586 | 0.9376× | 6.24% |

八例合计 **1277.946 → 1087.582 s，减少 14.90%**。本次八例分别更快，最大逐例倍率 **0.9628×（swerv_wrapper）**，全部低于 1.7×。这是每版每例一次的同镜像、同输入、32 线程单任务对照，未建立重复采样统计或背景负载恒定条件，不承诺其他机器或服务器同幅加速。

完整审计核实八例提交 ODB、canonical ODB/DEF/guide、MLS 计划和 HBT 指标与 v5 对照一致，完整平台及输入 SHA、线程数、任务数和源码构建链均绑定。基于该完整结果，选定 metadata_protected_cache 作为 v6 的纯 Runtime 方案；两份 Tcl 已推广到生产，实际标准回归已通过；封包身份仍需实际包外审计确认。

## 精确产物审计与实际详细布线质量

纯 Runtime 批次为 GRT-only。提交 ODB 和 canonical ODB/DEF/guide 的逐字节一致、相同输入/平台/固定引擎，证明优化保持评估器输入不变；**该审计不是新执行的 DRT/RCX/STA，也不产生新的最终质量标量**。必须保留已有质量结果的原始来源和覆盖。

v5 的本地完整固定 DRT2/RCX/STA 覆盖 bp_fe、bp_multi，历史运行是 16 线程；对应质量标量与服务器 32 线程报告相同。历史 16 线程时间不用于本轮 Runtime 倍率，本轮时间另有 32 线程单任务基线。v5 对 v4 曾接受的取舍保留在 HISTORY_V5.md：FE DRC 大幅减少、TNS/WNS 略好但线长增加；multi DRC 大幅减少、时序和线长轻微退化。新目标不改变这些历史事实。

## WNS 正式筛选：M4 因 DRC 回退拒绝

runtime_trunk512 在 bp_multi 完成真实固定官方 DRT2、RCX、最终 STA 和合法性检查。结果来自该 frozen 候选，质量比较绑定实际提交 ODB、输入、完整平台和固定引擎。

| 指标 | 已验证 v5 bp_multi | M4 候选 | 变化 |
|---|---:|---:|---:|
| WNS / ns | -16.9927 | -16.6510 | +0.3417 |
| TNS / ns | -83567.5 | -83525.9 | +41.6 |
| 最终 DRC | 4800 | 4887 | +87 |
| 详细布线线长 / μm | 3892767.95 | 3892501.57 | -266.38 |
| HBT 总数 | 3456 | 3456 | 0 |
| 超额 HBT | 0 | 0 | 0 |

M4 的完整入口为 **67.169 s**，32 线程 v5 基线 **76.224 s**，倍率 **0.8812×**；没有使用历史 16 线程质量运行时间。WNS、TNS、线长和 HBT 要求通过，唯一失败项是最终 DRC 增加 87 条。因此 wns_strict_comparison.json 的正式结论为 **REJECT，M4 未采用**。非选中网也会受资源竞争影响，不能把总 DRC 差异简单归因为选中网新增的 via。

M3 包外研究 runtime_trunk512_m3 只把同一候选的底层主干下界由 metal4 降到 metal3。该独立 bp_multi 试验未覆盖 bp、bp_quad 等其他受影响用例的最终质量，未纳入本版，也不以本版全八例精确产物审计替代它的质量验证。研究结果保存在包外 `reports/optimization_v6/wns_m3_strict_comparison.json`，不作为本版发布门禁。

## 测试与发布身份

最终生产标准回归 **155/155 PASS**，实际命令为 Python unittest discovery，覆盖与所选 metadata_protected_cache 一致的生产实现。final_test_evidence.json 记录真实执行退出码 0、完整源码与测试文件 SHA、日志 SHA，确认执行前后源码及测试保持一致；日志为 final_production_regression.log。此前阶段测试不再与这 155 项重复相加，单测通过也不替代官方八例合法性和产物审计。

离线八例规划回放已 PASS，每例新旧实现各两轮，同宿主环境下比较完整 plan JSON 与 apply Tcl。该微基准覆盖规划 CLI，不能代替完整入口；宿主与历史容器的 JSON 末位浮点差异单列，官方容器内计划与 ODB 字节门禁另行执行。空间索引保持原判定容差、组件编号和第一个覆盖矩形规则，没有降低检查覆盖。

选定候选：metadata_protected_cache，冻结实验 20261005T020515Z-6d7d4a9e。最终 ZIP 身份与源码、配置、九个 overlay、CRC 和文件清单的审计结果见包外 `reports/optimization_v6/package_audit_final.json`。ZIP 自身 SHA 仅保存在包外记录，避免自引用。

官方镜像 gaocr/3dbench-contest:20260914，image ID sha256:eb877c5e1f4d94881992b55d474ab189ab3308dac3f38208c5c8b0dd7544bd98。当前 Runtime 优化无 C++ 修改，复用已验证 GRT 二进制；不冒充本轮全新编译。固定评估器、物理 TRACKS、平台与 RCX 未被修改。

以下路径相对于本地 reports/optimization_v6，实验数据不进入提交包：

| 证据 | 路径 |
|---|---|
| 官方分数、身份与失败边界 | server_score_analysis.json、server_odb_identity.json、server_ingestion_findings.json |
| v5 32 线程完整基线 | runtime_baseline/20261005T005817Z-e217e5ed/experiment.json |
| 第一轮八例 Runtime | runtime_candidate/20261005T010551Z-082f5919/experiment.json、RUNTIME_PARITY_AUDIT.json |
| 当前 metadata frozen 实验 | metadata_cached_runtime/20261005T020515Z-6d7d4a9e/experiment.json |
| 当前 metadata 整批审计 | METADATA_PARITY_AUDIT.json（PASS） |
| M4 最终质量与拒绝依据 | wns_strict_comparison.json、WNS_M4_DECISION.md |
| M3 包外研究，非发布门禁 | wns_m3_screening/20261005T023030Z-3702b227/prepared_plan.json、wns_m3_strict_comparison.json |
| 规划回放与候选回归 | planner_fast_validation/comparison.json、metadata_fast_validation/summary.json、protected_cache_validation/summary.json、protected_cache_validation/standalone_summary.json |
| 最终包外审计 | package_audit_final.json（状态以实际报告为准） |
| 最终生产测试 | final_test_evidence.json、final_production_regression.log（155/155 PASS） |

复现入口沿用 support/README.md；完整入口口径为 grt.wall_seconds。历史 v5 记录保留为 HISTORY_V5.md。
