# 官方容器与本地评测

真正的官方 Docker 验证使用以下入口，需要当前账号能访问 Docker daemon：

```bash
python3 submission/support/run_official_container.py --pull
```

默认使用 `gaocr/3dbench-contest:20260914`。工具保存提交 ZIP 快照及 SHA256，记录并锁定实际镜像 ID，挂载只读项目与独立可写报告目录，从镜像完整源码全新编译，再运行 `bp_fe`、`bp_be` 的基线和优化版入口及官方合法性检查。随后两种 `bp_fe` 候选分别调用原始 `contest evaluate`，核对完整 DRT 两层日志、最终 STA 和 metrics。GRT/评估各 8 线程，最多同时评估两个候选；`--build-threads` 可设置编译并行度。所有记录保存在 `reports/official_container/host-*/`，失败退出非零，不调用原生替代引擎。

第三版原生导出可在官方容器内独立与 Tcl 实现逐字段比较：

```bash
python3 submission/support/verify_manifest_export.py \
  --openroad /absolute/path/to/built/openroad \
  --odb /absolute/path/to/4_cts.odb \
  --hook submission/flow_scripts/scripts_3D/prepare_mls.tcl \
  --output /absolute/path/to/export-comparison
```

该测试首先验证完整真实网表，再加入缺失 pin 几何、负数中心坐标、控制字符、中文名称、不同 die 和多层封装 pin 的实际 OpenDB 边界数据。比较保留每个网及其全部 pin 的顺序。大用例可用 `--skip-fixtures --reference-json` 与同一输入 ODB 先前捕获的 Tcl 清单作流式对照。

`MLS_MANIFEST_EXPORTER=auto` 默认在公开 GRT 含有原生导出命令时使用它；`tcl` 保留旧实现供消融，`native` 强制要求新命令。运行记录新增 `detail_seconds`，分别记录导出、规划、两次路由和校验耗时。其中 `grt.prepare` 包含 `mls.*` 子阶段，这些细分值不应直接全部相加；入口总耗时仍以 `runtime_seconds` 为准。

如需验证用户自带的官方离线版本，可先执行 `docker load -i Open3DBench-offline-20260904/docker/3dbench-contest_20260724.tar.gz`，再添加 `--image gaocr/3dbench-contest:20260724`。工具核对该版本的固定 image ID；两个镜像版本的结果需分别报告。

这些工具用于输入检查、合法性验证和本地原生 DRT/STA 实验。提交算法仍由 `run.sh` 和公开源码 `build.sh` 执行；本地评测指标不代表官方最终成绩。

无需 Docker daemon，可从赛题自带镜像提取原始固定评测引擎、流程及动态库：

```bash
python3 submission/support/extract_native_smoke.py \
  Open3DBench-offline-20260904/docker/3dbench-contest_20260724.tar.gz \
  /tmp/open3dbench-contest-extracted
```

候选 ODB 先复制到独立实验目录，由固定引擎重新导出 DEF/guide，并通过官方合法性检查；随后执行原始固定 DRT/STA。工具校验镜像提供的引擎 SHA256，每次记录命令、参数、引擎来源、公开 case/SDC/platform 文件摘要和运行时间。多个候选各有独立工作目录；`--threads` 乘 `--jobs` 不得超过 32。

```bash
python3 submission/support/evaluate_candidates.py \
  --case bp_fe --candidate candidate_a=/absolute/path/a/5_1_grt.odb \
  --candidate candidate_b=/absolute/path/b/5_1_grt.odb \
  --threads 8 --jobs 2 --end-iter 2 \
  --output-root reports/local_experiments
```

`--input-root` 可指定包含 `cases/`、`platforms/` 的公开输入根目录，`--runtime-root` 可指定提取目录。`--legality-only` 仅验证合法性。默认 `--end-iter 2` 用于完整比较；0/1 为初筛，工具通过独立 make 参数包装器改动迭代参数，保留固定评测源码，但初筛指标不能与最终迭代 2 混作比较。

已有完整评测可显式复用；仍重新检查候选合法性，且要求 canonical DEF 和 guide 与旧报告逐字节一致：

```bash
python3 submission/support/evaluate_candidates.py \
  --case bp_fe --candidate candidate_a=/absolute/path/a \
  --reuse-report candidate_a=/absolute/path/previous_report --threads 8
```

新版报告还校验固定引擎与公开输入文件摘要相同。早期报告没有完整输入摘要的兼容路径要求调用者确认使用相同公开输入，实验 JSON 会标为 `legacy_trusted_unchanged_public_inputs`。基线 runtime 若也没有历史 ODB 身份记录，会明确标为可信旧 manifest；现代报告的 runtime 覆盖要求 ODB SHA 一致。

比较工具分别记录 DRC、线长、TNS/WNS、HBT 数和 GRT 算法时间，不推算加权总分。TNS/WNS 百分比按负 slack 对应的非负损失计算；评测墙时不作为算法 runtime。

```bash
python3 submission/support/compare_metrics.py \
  --baseline /absolute/path/baseline_report \
  --baseline-run-manifest /absolute/path/baseline/run_manifest.json \
  --candidate candidate_a=/absolute/path/candidate_report \
  --output reports/local_experiments/comparison.json
```

若只优化入口时间，可附加 `--candidate-run-manifest label=/absolute/path/run_manifest.json`；此覆盖要求旁边的 ODB 与该次已评测输入 ODB 的 SHA256 相同。ODB 编码不同但 canonical DEF/guide 相同的情况应先显式 `--reuse-report` 建立新实验记录，再比较该记录中的新 runtime。

`analyze_drt_logs.py --work-root label=/absolute/path/evaluator-work --output stages.json` 分解已有 DRT 日志的 CPU/墙时；`analyze_drc.py --report label=/absolute/path/report --compare baseline:candidate --output drc.json` 汇总最终 DRC 的层和类型。后者可添加 `--selected-plan`、`--placement-def`、`--relocation-reference-plan`，核对共享原网、HBT 位置和消融实验的旧 HBT 移动是否一致。

在本地 `bp_fe`、8 线程、最终迭代 2 下，每候选约 19–20 分钟：bottom 约 11 分钟，upper 约 4.5 分钟，固定 post-hook 约 3 分钟，最终 STA 约 30 秒。具体时间以实验日志为准。


第三版真实官方 20260914 实验使用 `run_official_experiments.py`、`verify_official_experiments.py` 和 `capture_official_build_reference.py`。公开二进制只在九个 overlay 文件 SHA 全部一致时复用；增量构建必须提供已验证完整构建的父报告 SHA 和子构建的真实源码摘要。

官方质量指标复用代码已移除：历史报告缺少评测当时完整平台文件摘要。`--reuse-quality` 和旧复用 plan 都拒绝。最终质量必须来自实际官方 DRT2/STA；本页前面的 `--reuse-report` 仅属于旧版本地原生实验工具，不能作为官方容器验证证据。
