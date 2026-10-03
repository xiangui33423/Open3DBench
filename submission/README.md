# 3D-IC 全局绕线第二版提交

入口与官方示例一致，线程数必须为 1–32：

```bash
bash run.sh <input_dir> <output_dir> <platform_dir> [threads=32]
```

输入目录需包含 `4_1_cts.def` 和 `4_cts.sdc`。默认先重定位既有 HBT，并执行动态需求驱动的 MLS 准备步骤，再分别执行底层、上层全局绕线，验证引导文件并重新读取 ODB。成功后生成 `5_1_grt.odb`、`route.guide`、`submission.def`、`die_net_lists`、MLS 计划及运行记录；失败退出非零，不复用已有提交文件。详细日志与中间结果保存在输出目录的 `.grt-work-*` 中。

在官方镜像内先运行 `bash build.sh 32`，完整 OpenROAD 源码来自镜像 `/opt/contest/openroad-base`，本提交携带 GRT 源码覆盖层、MLS 源码和全部运行脚本。默认编译缓存位于 `/tmp/open3dbench-grt-build-<uid>`，也可通过 `SUBMISSION_BUILD_DIR` 指定。也可通过 `OPENROAD_EXE` 指定已编译的兼容程序；入口会检查所需的 `set_net_routing_layers` 扩展，普通 OpenROAD 缺少此扩展时会失败。

本地项目中运行 `python3 submission/package.py` 刷新脚本/源码并生成根目录 `submission.zip`。`MLS_ENABLE=0` 可用于对比相同入口的布线基线。`MLS_CONFIG` 可指定参数 JSON。

批量入口自动发现全部公开 case，也可指定子集；同一算法和参数适用于所有 case：

```bash
python3 submission/run_public_cases.py <input_root> <output_root> --cases bp_fe bp_be --threads 32 --mode both
```

去掉 `--cases` 则运行全部输入。添加 `--evaluate` 可逐次调用官方 `contest evaluate`，结果与日志记录在 `<output_root>/summary.json` 及各 case 目录中。

正式得分应以官方 `contest evaluate` 的合法性、DRC 和时序结果为准。当前原生 OpenROAD 的运行结果不能替代官方评测。

第二版默认共享上限为 192 条网、384 颗新 HBT，既有 HBT 最多做两轮合法重定位。`MLS_CONFIG` 可覆盖默认参数：`relocation_enabled=false` 关闭重定位，`max_new_hbts=0` 只保留重定位；`dynamic_demand` 和 `joint_site_placement` 控制动态需求与联合放置。完整说明见 `ALGORITHM.md`，实测范围和结果见 `VALIDATION.md`。运行记录中的 `stage_seconds` 用于定位入口耗时。默认在同一进程内按硬层约束分别路由两层，全局拥塞迭代为 1 次；`GRT_PROCESS_MODE=isolated` 可切回初版流程。
