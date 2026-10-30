# v22：规划进程与计划写出加速

在 v21 上优化垃圾回收和 JSON 写出，保留原算法及连接脚本。五例完整入口均值之和减少 **1.270%**；20 次新运行的原始 ODB/guide 与 v21 完全相同。全部八例通过官方 Python 3.12.3 的完整计划及编辑 Tcl 一致性检查。验证范围和原始计时见 VALIDATION.md。

```bash
bash build.sh 32
bash run.sh <input_dir> <output_dir> <platform_dir> 32
```

当前文件中的 v21 官方成绩为 25.81；v22 尚无官方成绩。三例服务器输入 DEF 缺失问题未解决。本轮未执行新的完整 DRT/RCX/STA，三例未计分用例也未重新运行原生路由。
