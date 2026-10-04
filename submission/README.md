# 3D-IC 全局绕线第四版提交

入口与官方示例一致，线程数必须为 1–32：

```bash
bash run.sh <input_dir> <output_dir> <platform_dir> [threads=32]
```

输入目录需包含 `4_1_cts.def` 和 `4_cts.sdc`。默认先合法重定位既有 HBT，再执行带接收端路径保护的多分支 MLS，并用剩余预算进行原有双 HBT 共享，随后分别执行底层、上层全局绕线。验证引导文件并独立重开 ODB 后，生成 `5_1_grt.odb`、`route.guide`、`submission.def`、`die_net_lists`、MLS 计划及运行记录；失败退出非零，不复用已有提交文件。详细日志与中间结果保存在输出目录的 `.grt-work-*` 中。

在官方镜像内先运行 `bash build.sh 32`，完整 OpenROAD 源码来自镜像 `/opt/contest/openroad-base`，本提交携带 GRT 源码覆盖层、MLS 源码和全部运行脚本。默认编译缓存位于 `/tmp/open3dbench-grt-build-<uid>`，也可通过 `SUBMISSION_BUILD_DIR` 指定。也可通过 `OPENROAD_EXE` 指定已编译的兼容程序；入口会检查所需的 `set_net_routing_layers` 扩展，普通 OpenROAD 缺少此扩展时会失败。

本地项目中运行 `python3 submission/package.py` 刷新脚本/源码并生成根目录 `submission.zip`。`MLS_ENABLE=0` 可用于对比相同入口的布线基线。`MLS_CONFIG` 可指定参数 JSON。

批量入口自动发现全部公开 case，也可指定子集；同一算法和参数适用于所有 case：

```bash
python3 submission/run_public_cases.py <input_root> <output_root> --cases bp_fe bp_be --threads 32 --mode both
```

去掉 `--cases` 则运行全部输入。添加 `--evaluate` 可逐次调用官方 `contest evaluate`，结果与日志记录在 `<output_root>/summary.json` 及各 case 目录中。

正式得分应以官方 `contest evaluate` 的合法性、DRC 和时序结果为准。本项目使用官方 `20260914` 容器验证，具体覆盖范围及实测值见 `VALIDATION.md`。

默认共享上限为 192 条网、384 颗新 HBT，既有 HBT 做两轮合法重定位，移动次数上限由第二版的 4,096 提高为 65,536，避免大设计在第一轮提前停止。`MLS_CONFIG` 可覆盖默认参数：`relocation_enabled=false` 关闭重定位，`max_new_hbts=0` 只保留重定位；`dynamic_demand` 和 `joint_site_placement` 控制动态需求与联合放置。完整说明见 `ALGORITHM.md`。

第四版默认对底层 fanout 至少 128、HPWL 至少 400 μm 的普通信号网尝试最多 8 个远端组。跨层接收端的完整几何路径不得超过原直接路径的 1.05 倍加 6.4 μm；不满足条件的接收端保留在源端 S0 直接连接。全部新 HBT 仍共用上述预算。`multi_branch_enabled=false` 关闭新增分支策略；`multi_branch_sink_guard=false` 仅用于未保护方案的消融，本轮该方案曾明显恶化 WNS，不建议用于提交。加权几何评分是筛选代理，不是 RC 或时序指标。

第三版直接从 OpenDB 导出规划器清单，流式检查 guide，并复用经过输入与内容 SHA 校验的完整网分类。两次非空 die 路由之间使用原生队列清理，保留每网硬层约束和最终完整 guide 导入。`MLS_MANIFEST_EXPORTER=tcl`、`GRT_PASS_RESET=legacy` 可分别恢复旧实现供对照；旧兼容二进制会自动回退，空 die 保持原有保护流程。

运行记录中的 `stage_seconds`、`detail_seconds` 用于定位耗时，`grt_pass_reset` 记录实际使用的交接实现。`grt.prepare` 包含 `mls.*` 子项；并行检查时 `grt.check_guide_layers` 与 `grt.check_guide_connectivity` 相互重叠，整体墙时为 `grt.check_guides`，不能将细项全部相加。`grt_check_mode`、`grt_input_mode` 记录实际检查与输入方式，`grt_layer_hint_counts`、`grt_resistance_hint_counts` 分别记录各 die 应用的固定选层和电阻代价网数。默认同一进程按硬层约束分别路由两层，全局拥塞迭代为 1 次；`GRT_PROCESS_MODE=isolated` 可切回初版流程。

单进程默认直接读取 DEF，省去初始 ODB 写入和重读；准备后的 ODB 中间检查点也默认省略，最终 ODB 仍完整写入并独立重开验证。`GRT_INPUT_MODE=odb` 可恢复初始转换，`GRT_SAVE_CHECKPOINTS=1` 保留准备后的 ODB。独立进程模式自动使用 ODB 输入。两项只读 guide 检查默认并行，`GRT_CHECK_MODE=serial` 可串行；请求单线程时自动串行，任一检查失败仍阻止发布。

单进程可通过 `GRT_HIGH_FANOUT_LAYERS=1 GRT_HIGH_FANOUT_POLICY=resistance` 对长、高扇出的普通信号网使用选择性 wire/via 电阻代价。选网统一依据 fanout、长度、信号类型和连接特征，排除时钟、HBT 和封装引脚网，仍保留原 die 硬层窗口；需要本版配套二进制。`GRT_HIGH_FANOUT_POLICY=layers` 为固定主干层区间的独立对照。两项都默认关闭（`GRT_HIGH_FANOUT_LAYERS=0`），本轮完整评测未支持将它们设为默认。实际 RCX 电阻与 LEF 层电阻不同，不能据 LEF 降阻比例推断最终收益。独立进程回退不应用这两项策略。

原生实现同时修复了两次 die 路由之间的技术层缓存重建，并为每次路由清除显式 RA 集合，避免跨 die 混用电阻参数或遗留标记。另有针对既有 HBT 重定位和旧双 HBT 共享的可选完整路径保护，默认关闭；它与默认启用的多分支接收端保护分别配置，详情见 `ALGORITHM.md`。
