# 修改记录 058 实验收尾协调与离线报告版本兼容

日期：2026 年 10 月 27 日，Asia/Shanghai。类型：修复 / 测试 / 文档。插件版本：`0.1.2`。相关 Git 提交：尚未提交；已核实起始提交为 `33e95e6`，在 055–057 的本地实现上修复。

## 问题与目标

原 run_batch 在返回前释放内核锁，而 run_experiment 随后仍会关联样本、计算分组并写入最终 experiment-result.json。若批次在正常完成一个任务后于调度边界中断，尚有明确未开始项，则原实验收尾期间续跑预检可能放行。续跑完成后，原实验再写最终 checkpoint，会改变已纳入续跑摘要的源文件，导致离线报告以 Continuation frozen source changed 拒绝生成。

另一问题是离线续跑报告复用了含 validate_live_case 的归档加载器。本地 package.json 版本升级后，归档 pluginVersion 与当前安装版本不同，即使归档内部完全一致，也会被误判为无法报告。普通版本 1 报告没有这一执行环境依赖。

本批将原实验最终 checkpoint 纳入同一批次锁，并分开归档静态校验与执行环境校验。命令、持久化版本及原证据均不变。

## 文件修改

| 文件 | 修改前 | 修改后 | 原因 |
| --- | --- | --- | --- |
| dsh_eval/batch.py | run_batch 在返回前自行释放锁 | 默认自行管理；实验可通过内部 _lock_stack 保留同一锁 | 避免批次结束与实验收尾之间出现空窗 |
| dsh_eval/experiment.py | 批次返回后无锁完成样本、分组和最终写入 | 用 ExitStack 覆盖批次执行至实验最终 checkpoint | 让两个续跑入口都受原实验收尾约束 |
| dsh_eval/experiment_resume.py | _load_inputs 同时校验当前安装版本 | 只检查归档结构、身份、矩阵和冻结输入；预检仍调用批次 live 校验 | 离线报告不依赖当前安装版本，执行限制保留 |
| test/test_experiment_resume_report.py | 未覆盖收尾空窗、收尾写入失败和本地升级 | 新增三项回归 | 覆盖锁边界、异常解锁及归档报告兼容 |
| test/test_experiment_resume.py | 未独立锁定升级后的执行拒绝 | 新增一项无副作用拒绝回归 | 防止报告修复同时放宽续跑执行条件 |
| 进度、架构、批次 / 续跑 / 报告说明及 CHANGELOG | 未说明上述边界 | 同步锁生命周期、校验分工和验证范围 | 文档与实现一致 |

## 实现与技术取舍

run_experiment 创建 ExitStack，并通过内部 _lock_stack 传给 run_batch。批次仍在首次 checkpoint 前取得原 `.batch-execution.lock`，只是将该锁上下文登记到实验调用方；同一锁覆盖执行、批次终态、实验关联 / 汇总和实验最终 checkpoint。普通独立批次省略参数时仍在本地 ExitStack 中管理锁。

没有新增第二把锁或先释放再重新加锁，因此批次与实验续跑入口均在原实验收尾期间拒绝。异常沿原调用栈传播，ExitStack 释放锁；最终写入失败时保留磁盘上的 running 结果，不补写终态。既有不完整 / 未知执行仍按原证据规则阻断，不因解锁而视为成功。

_load_inputs 删除重复的 validate_live_case，保留 validate_case、计划快照 / 指纹、矩阵身份和冻结输入比较。实验续跑的 _load_plan 仍调用批次预检，后者对每个冻结用例执行 validate_live_case，因此 headless 和当前安装插件版本要求继续适用于预检 / 执行。离线报告继续核对归档中的请求 / 实际配置、录制插件版本、实际请求路由及逐项证据；并非忽略版本一致性。

选择由现有 ExitStack 延长同一锁的生命周期，避免为实验引入另一套锁协议；选择移除静态加载器中的重复 live 校验，避免增加报告专用的跳过校验开关。未更改 resumeSupportVersion、输入指纹算法、结果 / 报告格式或公开命令。

## 验证

环境：Windows、Python `3.12.0`、Node.js `v24.14.0`。全部为无模型验证：使用 synthetic 配置、确定性适配器、真实 Python / Node 子进程、录制器与 Node inspect。并发回归用线程事件精确暂停原实验的最终 checkpoint，使用实际内核锁检查竞争入口，不使用等待固定时长来猜测时序。本地升级通过替换 package.json 的读取结果模拟，未修改实际包版本。

| 命令或操作 | 结果 | 证明的范围 |
| --- | --- | --- |
| 修复前，Python unittest.TestSuite 运行收尾竞争 / 升级报告两项新增测试 | 2 项 / 2.971 秒，1 failure、1 error | 原实验收尾未拒绝预检；离线报告抛出不同 recorder version |
| 修复后，同一 runner 指定四项新增回归 | 4 项 / 9.849 秒，OK | 收尾锁、异常解锁、升级后离线报告及执行拒绝 |
| `npm.cmd run test:python`，受限进程环境 | 303 项 / 166.179 秒，5 errors，不计完整通过 | 四项进程树回收失败；Web 生命周期初始化 spawn EPERM，该类十九项未执行 |
| 同一 `npm.cmd run test:python`，允许真实子进程创建 / 回收的环境 | 完整 322 项 / 168.341 秒，OK、无失败 / 跳过 | 新增四项及原批次、实验、普通 / 续跑报告、浏览和生命周期兼容回归 |
| `python -m compileall -q dsh_eval scripts test` | 退出 0 | Python 语法检查 |

新增测试位于 test/test_experiment_resume_report.py 的 test_original_finalization_blocks_continuations_until_its_last_checkpoint、test_failed_experiment_final_checkpoint_releases_the_batch_lock、test_local_plugin_upgrade_does_not_block_offline_continuation_reports，以及 test/test_experiment_resume.py 的 test_local_plugin_upgrade_still_blocks_continuation_preflight_and_execution。可用 unittest discovery 运行对应模块，或将 test 加入 sys.path 后用 unittest.TestSuite 指定这些方法。

关键断言：

- 原批次已 interrupted，但原实验尚在最终写入前：两个入口的预检 / 执行共四种操作均因实际锁占用拒绝，不创建领取或续跑目录。原实验收尾完成后，允许复用一项并执行七项，八项报告全部 verified，原实验文件不被续跑或报告改写。
- 原实验最终 checkpoint 模拟 OSError 后，锁可重新取得，running 实验的八个已完成项可重新核对；无剩余项，不自动执行。
- 模拟本地插件版本变化后，续跑离线报告八项仍 verified / matched，原文件摘要不变且未调度任务；同样的版本变化会让预检 / 执行在输出和领取前明确拒绝。

本批未修改 JavaScript，不重复运行 Node / JS 全套检查，也不将 057 的历史数量当作本批验证。Python 完整套件中的实际 Node 子进程、inspect 及 Web 生命周期检查已执行。

## 风险与后续

新锁范围只由更新后的原实验调度器提供；已启动的旧代码不能自动获得延长的锁生命周期，应等待其退出且目录稳定后再续跑。异常写入仍可能留下 running / 临时文件，不承诺多文件事务、fsync 或断电恢复。

本地版本不同时允许的是离线报告，不能据此宣称旧配置能在当前宿主继续执行。真实模型续跑、目录搬迁、连续续跑及跨实验合并仍未覆盖。没有新增模型样本、提交 / 推送或新云端 CI。

## 文档同步

已同步 CHANGELOG、docs/progress.md、docs/architecture.md、docs/experiment-resume.md、docs/configuration-reports.md、docs/batch-resume.md、docs/batch-runner.md 和 docs/plans/m6-reliability-validation.md；修正当前架构 / 批次续跑说明中仍称浏览器未接入版本 2 的旧状态。055–057 的历史修改记录及验证结果保持原样。命令不变，README 的运行方式无需调整。

当前工作区十五份修改 / 新增 Markdown 的 392 个本地链接均存在且未被忽略；git diff --check 通过。runs / private-notes / secrets 无已跟踪文件，合成运行输出不加入公开仓库。
