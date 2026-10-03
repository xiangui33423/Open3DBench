# 初版验证记录

验证日期：2026-10-03。

## 已完成

- 18 项 Python 测试通过，覆盖 MLS pin 保留、双向链路、HBT 方向、网格与间距、数量预算、候选排除、时序保护、名称冲突、确定性和 Tcl 转义。
- 提交 Python 文件通过语法检查，Shell 入口通过 `bash -n`。
- ZIP 中的入口保留执行权限，包含源码、GRT 覆盖层、配置、构建/运行脚本和算法说明；不包含输入数据、测试输出或固定评估器。
- 八个公开用例的 LEF/Liberty 匹配检查通过。
- 八个公开用例的实际准备阶段全部执行完成，并通过官方检查器的不可变元件/封装引脚、逻辑等价、MLS 家族与 HBT 合法性检查，错误和警告均为空。每例选择 32 条共享网、新增 64 个 HBT。此项不代表全部八例已完成 GRT、DRT 或 STA。

以下两例运行的是完整 GRT 提交接口，并用官方固定检查器从最终 ODB 重新导出 canonical DEF/guide 后验证：

| 用例 | 共享网数 | 新增 HBT | 最终 HBT | 免费 HBT 额度 | ODB 大小 | 本地运行时间 | 合法性 |
|---|---:|---:|---:|---:|---:|---:|---|
| bp_fe | 32 | 64 | 1,213 | 1,729 | 34,193,313 bytes | 40.024 s | legal=true，零错误/警告 |
| bp_be | 32 | 64 | 1,169 | 2,176 | 55,295,125 bytes | 109.908 s | legal=true，零错误/警告 |

本地使用 8 线程。运行时间包含输入读取、MLS 准备、GRT 与结果验证，不包含详细布线评测；这些数字不是统一评测服务器上的成绩。

## bp_fe 本地详细布线与时序对比

使用离线镜像中未修改的固定 DRT/DRC/STA 引擎、报告脚本、指标收集器和检查器完成了本地对比。详细布线参数为 `-droute_end_iter 2`。原生执行时，最终报告脚本使用其支持的 `EVALUATOR_HBT_PARASITICS_TCL` 环境变量定位镜像中提取的同一脚本，没有修改评估逻辑。

| 指标 | 相同入口 baseline | MLS 初版 | 变化 |
|---|---:|---:|---|
| DRC | 4,257 | 4,152 | 减少 105，约 2.47% |
| DRT 线长 (μm) | 1,378,685.12 | 1,383,673.91 | 增加约 0.36% |
| TNS (ns) | -2,697.39 | -2,694.45 | 小幅改善 2.94 ns |
| WNS (ns) | -1.35101 | -1.35174 | 变差 0.00073 ns |
| 提交入口运行时间 (s) | 34.420 | 40.024 | 增加约 16.28% |
| 超出免费额度的 HBT | 0 | 0 | 相同 |

这些结果证明流程可以完成，尚不构成综合得分提升。上述时间使用本地 8 线程执行；评估器自身的 wall time 包含本机路径恢复耗时，不作为算法 runtime 比较。时序值仅与本地同一引擎、同一输入的 baseline 对比，不使用其他版本 README 中的表格作为基准。

## 验证环境与限制

本机无法访问 Docker daemon，因此从用户提供的离线镜像中提取了固定 OpenROAD 引擎及其运行库，以原生方式验证 Tcl/OpenDB 接口。固定引擎和正式检查脚本未被修改。正式提交的算法程序仍由 `build.sh` 构建 GRT 源码覆盖层；这个完整构建尚未在官方容器中执行。

正式运行需在官方镜像中执行构建，并对全部公开用例运行 `contest evaluate`。当前几何需求估计与可选 slack 保护不等于完整的时序反馈优化，不能仅凭合法性通过认定评分提升。

## 本地复现接口检查

无法运行 Docker 时，可使用提供的可选工具进行原生集成检查：

```bash
python3 submission/support/extract_native_smoke.py \
  Open3DBench-offline-20260904/docker/3dbench-contest_20260724.tar.gz \
  /tmp/open3dbench-native

export OPENROAD_EXE=/tmp/open3dbench-native/openroad-eval-native
INPUT=Open3DBench-offline-20260904/Open3DBench/input/open3dbench_8cases_post_hbt_input_20260724
bash submission/run.sh \
  "$INPUT/cases/bp_fe/grt_input" output/bp_fe/mls_initial \
  "$INPUT/platforms/nangate45_3D" 8
```

这条路径用于集成检查。正式提交时应使用源码构建的公共 GRT 程序。
