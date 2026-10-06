# 3D-IC 全局绕线第七版提交

本版主要缩短程序运行时长 Runtime，保留上一版布线结果。全八例同配置完整入口合计 **1087.582 → 1012.285 秒，减少 6.92%**，各例均更快，全部满足 1.7 倍耗时约束。提交 ODB、canonical ODB/DEF/guide、MLS 计划与 HBT 记录均与 v6 相同；本轮未重新执行全量 DRT/STA，WNS 未取得新改善。

正式成绩仍为 **18.404208740850777 分**。30 分尚未验证；服务器三例 `Input DEF file not found` 的根因也尚未证实。具体范围和证据见 [VALIDATION.md](VALIDATION.md)。

第七版把保护扫描和普通实例快照的读取合并为原生只读操作，保留原检查；高扇出引脚去重使用精确集合，网络排序避免重复创建字符串。已重新完整编译并通过八例官方合法性、精确产物审计、真实数据库差分验证及 **165 项生产回归**。本地 Runtime 为预编译后的完整入口墙时，32 线程、单任务、每版每例一次，不保证其他机器具有同幅收益。

## 构建与运行

在官方镜像内运行：

```bash
bash build.sh 32
bash run.sh <input_dir> <output_dir> <platform_dir> [threads=32]
```

输入目录需含 `4_1_cts.def`、`4_cts.sdc`，线程数为 1–32。源码来自镜像 `/opt/contest/openroad-base`，提交包携带九份 GRT 源码覆盖层和全部运行脚本。编译缓存默认位于 `/tmp/open3dbench-grt-build-<uid>`，`SUBMISSION_BUILD_DIR` 可指定缓存目录。原生源码已改变，需要构建本版二进制；也可用 `OPENROAD_EXE` 指定兼容程序。

入口先合法重定位既有 HBT，再执行带接收端路径保护的多分支 MLS 和剩余预算中的双 HBT 共享，然后分别进行两层全局绕线。完整 guide 检查和 ODB 独立重开验证后才发布 `5_1_grt.odb`、`route.guide`、`submission.def`、分层网络名单、计划与运行记录；失败返回非零。

本地项目使用 `python3 submission/package.py` 同步生产脚本/原生源码并生成根目录 `submission.zip`。批量运行可使用：

```bash
python3 submission/run_public_cases.py <input_root> <output_root> --threads 32 --mode both
```

## 参数与回退

所有用例使用同一套规则和参数，不按 case 名称分支。M2 容量削减 70%、M3 削减 60%，其他当前 die 路由层削减 50%，拥塞迭代一次；最多共享 192 条网、增加 384 颗 HBT。多分支接收端路径保护保持启用。物理 TRACKS、技术库、RCX 和固定评估流程保持原样。

`GRT_LAYER_ADJUSTMENTS='metal2=0.7,metal3=0.6'` 为默认值，空字符串恢复统一容量；0.70 表示削减 70%，不是保留 70%。`MLS_ENABLE=0` 关闭 MLS 对照，`MLS_CONFIG` 指定规划参数。

新增 `MLS_PREPARE_SCAN=auto|native|tcl`：默认 auto 使用本版批量查询，旧二进制无此接口时回退 v6 Tcl；native 要求接口存在，tcl 强制旧实现。接口自身报错仍传播，不静默跳过检查。

沿用的对照选项包括 `MLS_MANIFEST_EXPORTER=tcl`、`GRT_METADATA_SNAPSHOT=all`、`GRT_LAYER_DISPATCH=legacy`、`GRT_PASS_RESET=legacy`、`GRT_PROCESS_MODE=isolated`、`GRT_INPUT_MODE=odb`、`GRT_CHECK_MODE=serial` 和 `GRT_SAVE_CHECKPOINTS=1`。这些对照不属于上表默认配置的实测收益。

高扇出选层/电阻研究策略仍默认关闭（`GRT_HIGH_FANOUT_LAYERS=0`）；既有 M4/M3 候选均因质量退化拒绝。算法与历史策略见 [ALGORITHM.md](ALGORITHM.md)，验证工具见 [support/README.md](support/README.md)。

运行记录的 `stage_seconds`、`detail_seconds` 用于定位耗时，子阶段不可再与所属父阶段相加；并行 guide 检查取父墙时。正式 Runtime 比较使用外部完整 `run.sh` 墙时，不能用内部 manifest 计时或 DRT/STA 时间替代。
