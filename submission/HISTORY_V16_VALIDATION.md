# v16 fixed2_safe 验证范围

冻结执行身份为 `01a5028791cae37320e3de954152cd02f68dfa030af95a888477d28c661951df`，共41个执行文件；原生13份覆盖层与已验证v15相同。原始公共输入、平台、GRT二进制和20260914固定评估器均有身份记录。发布复制后的执行文件与冻结源逐项对应，具体发布ZIP及最终主目录测试由发布审计记录。

八个公开用例均完成新的GRT、独立ODB重开和固定官方canonical合法性。完整时序覆盖仅按原官方成功的五例计算：FE、BE、BP、multi为本轮8线程完整固定DRT2/RCX/STA；SW复用v15的完整评测。SW复用前重新验证本版原始ODB及原始GRT guide逐字节身份，并完成新的canonical合法性，两个原文件的保留压缩档及解压SHA均有证明；canonical重排guide不作为原始guide替代。取消的重复SW评测不计为新完整时序。ariane133、ariane136、quad仅有本轮新合法性，不计入新增STA或五例聚合。

相对官方24.02的同五例，TNS损失减少4.4043%，WNS损失减少3.5264%，DRC减少11.0469%；相对v15分别减少4.6749%、3.1617%、0.2496%。损失按各例 `max(0, -slack)` 求和，等价于固定五例的同分母均值对比。原评分归一化未知，不能把这些百分比或名义权重换算成新分数。FE WNS、multi TNS及SW小幅回退均保留在逐例表中。

最终主目录 **238项生产回归及7项支持工具回归，共245项通过**；其中12项新增行为检查覆盖成功不重试、两类原生错误、用户配置/无关错误不重试、二次失败传播、失败日志、不同子进程及相同原CTS输入、精确v15回退配置SHA。测试直接导入本包实际入口，子进程fixture不替代真实GRT；quad的真实原生重试证据另列。日志为 `reports/optimization_v16/FINAL_PRODUCTION_TESTS.log`、`FINAL_SUPPORT_TESTS.log`。发布执行文件再次逐项核对冻结41文件；ZIP的CRC、入口权限及执行身份由最终发布审计记录。

quad实测首次出现 `GRT-0228`，重试进程与初次进程不同，重新读取相同原始CTS，采用SHA为 `60bfc59a0064f58869050fb6b0f1cedc10cc44accec140ad4a74f192429259d3` 的原配置，最终GRT及canonical合法。总入口1090.320秒，包含首次失败与重试；guarded另一次2线程覆盖为547.222秒且无重试。两者是不同时间的覆盖观测，**不是公平成对计时**。native检查没有关闭，其他错误与第二次失败仍传播。证据为 `safe2_recovery_review.json`、`coverage_fixed2_safe.json` 和 `verify_safe2_quad_evidence.py`。

本版FE/BP/SW的12条8线程配对入口记录均完成，原始ODB/GUIDE身份匹配：

| 用例 | v15 均值 / s | fixed2_safe 均值 / s | 耗时变化 |
|---|---:|---:|---:|
| bp_fe | 17.060 | 14.655 | -14.10% |
| bp | 110.768 | 117.507 | +6.08% |
| swerv_wrapper | 38.843 | 38.772 | -0.18% |

原记录为 `reports/optimization_v16/paired_entry_runtime/fixed2_safe/20261014T131339Z-6c970a69/record.json`。计时覆盖完整 `run.sh`，排除随后哈希、压缩归档和固定DRT评估；共享宿主、RAM文件系统、每例每版本两次，SW的约0.18%差异视为基本持平。BP入口变慢是实际代价；这些本机记录不能推断官方Runtime。`SUMMARY.json` 应读取 `candidates.fixed2_safe` 的完整五例/八合法标志；全局状态还包含未完成的其他实验记录。

选定固定两组源码在宿主Python3.10.12与官方镜像Python3.12.3下完成BP/multi完整规划对照：选网顺序、全部HBT位置、子网成员、重定位记录及生成的apply Tcl一致，且两解释器均与本轮实际新GRT保留计划相符。诊断浮点值允许有约1e-10差别；此项仅验证两例规划兼容性，不计为新增GRT或STA。证明为 `reports/optimization_v16/selected_python_compatibility/SUMMARY.json`。
