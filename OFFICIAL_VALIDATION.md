# 第二版官方容器验证

本文件保留第二版的原始官方对照结果；第三版的验证和比较见 `submission/VALIDATION.md`。

日期：2026-10-03。官方镜像 `gaocr/3dbench-contest:20260914` 中，第二版提交已完成全量源码编译、全部 8 个公开用例的全局布线与官方 canonical 合法性验证，以及 `bp_fe` 的完整固定 DRT/DRC/STA。

## 提交和镜像身份

- 算法源码 checkpoint：`26d2bc2a91924d4e09ea655d5dd4a06c2b461c24`。
- 被验证的 `submission.zip` SHA256：`6d34f7f45a56318f05039584ac251f7eb581b2576f6f790a788f2a3b141fc25a`，44 个文件，ZIP CRC 检查通过。
- 实际 Docker image ID：`sha256:eb877c5e1f4d94881992b55d474ab189ab3308dac3f38208c5c8b0dd7544bd98`；运行使用不可变 ID。
- 镜像 evaluator version：`20260914`；完整 OpenROAD base commit：`305d3ba2ddfd00591924cc586ad408179f566afe`。
- 提交从 ZIP 独立解压，使用镜像 `/opt/contest/openroad-base` 与公开 GRT overlay，全新目录编译 `openroad` 目标。32 线程构建成功，耗时 481.850 秒。
- 本次公开编译产物 SHA256：`5d5afd5dac9cc73bcbfa0891fb0f314bfee0af8029ee96aa2345b90bf96d8a5b`；GRT 明确调用此产物。
- 固定 `evaluate`、`openroad_eval`、`openroad_eval.real` 均通过镜像 checksum；评估器和 `/opt/contest` 未被替换或修改。

## bp_fe 同轮完整比较

baseline 为同一个第二版入口设置 `MLS_ENABLE=0`；优化版为默认配置。两者使用同镜像、同公开输入、同公开编译产物、8 线程 GRT、相同 GRT 参数。详细评估直接调用官方 `contest evaluate`，每候选 8 线程，各自隔离工作目录，两个实际 DRT pass 都确认 `-droute_end_iter 2`。底层范围 `metal1–metal10`，上层 `metal11–metal20`，跨 die/unrestricted 路由网均为 0。

| 指标 | 同入口关闭优化 | 默认优化版 | 变化 |
|---|---:|---:|---|
| DRC | 4,096 | 4,059 | 减少 37，0.903% |
| DRT 线长 (μm) | 1,370,616.44 | 1,342,836.13 | 减少 27,780.31，2.027% |
| TNS (ns) | -8,347.85 | -8,253.17 | 负时序损失减少 1.134% |
| WNS (ns) | -3.50876 | -3.33894 | 负时序损失减少 4.840% |
| HBT 总数 | 1,149 | 1,533 | 增加 384，仍未超额度 |
| 超额 HBT | 0 | 0 | 均为 0 |
| GRT 入口时间 (s) | 18.565 | 26.254 | 增加 7.689，41.417% |

四项质量指标改善，同时有额外的算法运行开销。入口时间不包含源码编译与固定详细评估；固定评估自身耗时约 19–20 分钟。这里没有计算官方总分，也未把旧版本原生结果作为本次官方基线。

## 验证范围和复现

全部 8 个公开用例的默认优化版均完成真实官方容器 GRT，并通过固定引擎 snapshot 后的 canonical 合法性检查，errors/warnings 和超额 HBT 数均为 0。`bp_fe` 和 `bp_be` 关闭优化的基线也均合法。只有 `bp_fe` 完成本轮两种模式的完整 DRT/DRC/STA。

| 用例 | 默认入口时间 (s) | Canonical 合法性 | HBT 数 / 免费额度 | 超额 HBT |
|---|---:|---|---:|---:|
| bp_fe | 26.254 | 合法 | 1533 / 1729 | 0 |
| bp_be | 40.840 | 合法 | 1489 / 2176 | 0 |
| ariane133 | 128.546 | 合法 | 4409 / 7300 | 0 |
| ariane136 | 137.356 | 合法 | 4430 / 7300 | 0 |
| bp | 194.823 | 合法 | 4231 / 5880 | 0 |
| bp_multi | 85.020 | 合法 | 3456 / 4687 | 0 |
| swerv_wrapper | 69.112 | 合法 | 1662 / 4087 | 0 |
| bp_quad | 861.474 | 合法 | 28219 / 45630 | 0 |

上述时间来自各次新入口的 `run_manifest.json`，不含源码编译或官方 snapshot/合法性检查；各次运行的系统并发负载不同。

```bash
python3 submission/support/run_official_container.py --build-threads 32
```

宿主入口锁定提交 ZIP 快照和镜像 ID，挂载只读项目和独立可写报告目录，执行全新编译、入口及官方检查。失败返回非零；必须有新 metrics、最终 STA 和完整两层日志才记录评估完成。

本次原始报告位于 `reports/official_container/host-20261003T143206Z-e2e31e68/`：`host_verification.json`、`verification.json`、`comparison.json` 和各 case 日志/ODB/合法性/metrics。全 8 项汇总为 `public_cases_summary.json/.md`；补充用例证据在同目录 `additional_cases/`，原顺序 worker 的中断记录与最后两项独立并行 worker 均保留。版本及实际层范围审计在 `reports/official_container/`。

`submission/HISTORY_V2.md` 中的历史实验使用官方离线旧版 `20260724`，其数值应保留为历史实验。新版 `20260914` 固定引擎及 RC/STA 输入流程有实质更新，本文件的时序指标来自新版真实官方容器。
