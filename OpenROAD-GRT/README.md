# OpenROAD 3D GRT：v16 WNS/TNS 候选

当前提交采用固定两组共享分支、384新增HBT预算和一次有界路由策略回退。原官方成功五例的TNS损失合计降低4.40%、WNS损失合计降低3.53%、DRC降低11.05%；FE WNS和multi TNS有回退。质量范围为四例新完整DRT/RCX/STA加SW严格物理身份复用，八例新合法性已通过。新官方分数尚未验证。

构建和提交入口位于 [submission](../submission/README.md)，该目录的 `flow_scripts` 在打包时由本目录同步。算法见 [ALGORITHM.md](ALGORITHM.md)，测量、运行开销及限制见 [优化记录](../docs/optimization_v16.md)。原生覆盖层保持不变，更新仅涉及提交入口、默认/回退MLS配置和对应行为测试。

原目录结构、构建接口和旧实验说明完整保存于 [HISTORY_V15.md](HISTORY_V15.md)。原24.02分及v15 ZIP保留供复查；本机观察不能确认已达到27分。
