# v36：优化长控制网络的时序

基于用户反馈平台得分 27.32 的 v35。对扇出至少 128、HPWL 至少 400 μm 的底层普通信号网络，规划一条借用上层金属的主干。每条网络固定两个 HBT，近端和不满足逐负载路径保护条件的接收端保留底层直连。
规则由每个输入的网络几何与扇出生成，不含用例名或特定网络名单。
保留 v35 的两个 HBT 限制与完整官方库加载。

```bash
bash build.sh 32
bash run.sh <case>/grt_input <output_dir> <platform_dir> 32
```

输入须保留与 grt_input 同级的 flow_design/config.mk。
bp_be 已用新离线镜像的原版评估器完成合法性、DRT、DRC、RCX、STA。
WNS -3.55756 ns；TNS -5919.77 ns；DRC 4280；线长 2311221.54 μm。
本版优先改善时序；相对 v35，DRC 增加 8.80%，
详细线长增加 0.276%。
尚未上传比赛平台；只有 bp_be 做了本轮完整评测。历史数据见 HISTORY_*。
