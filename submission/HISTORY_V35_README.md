# v35：修复 HBT 超限与官方库集合不一致

本包基于 v34。默认及回退配置均关闭多分支 MLS；每条原始 2D MLS 网络必须恰好使用两个 HBT、三个子网。
入口按输入中的 flow_design/config.mk 和平台 config.mk 加载完整官方 LEF/Liberty 集合，保留未实例化宏。
使用新离线镜像 20261025-mls-map 的原版评估入口完成 bp_be 的合法性、DRT、DRC、RCX、STA，退出码为 0。

```bash
bash build.sh 32
bash run.sh <case>/grt_input <output_dir> <platform_dir> 32
```

输入须保留与 grt_input 同级的 flow_design/config.mk；这是完整官方输入包的一部分。
本地结果：WNS -4.2267 ns，TNS -6659.82 ns，DRC 3934，详细线长 2304859.29 μm。
合法性通过不表示 DRC 为零或时序收敛。尚未上传平台，也没有新平台分数。
仅 bp_be 完成本轮完整评测。历史版本数据见 HISTORY_*，不作为本包的评测结果。
