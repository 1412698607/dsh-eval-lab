# 修改记录 052 批次级安全续跑与无模型验收

日期：2026 年 10 月 26 日，Asia/Shanghai。类型：功能 / 配置 / 测试 / 文档。插件版本：`0.1.2`。相关 Git 提交：尚未提交。

## 问题与目标

旧调度器中断后重新运行冻结 batch.json 会创建新批次，并重新调用已完成任务。首版续跑需要先复核历史执行，只对明确未开始的项创建新任务；执行或清理状态未知时必须拒绝，不能以缺失结果推断未调用模型。

## 文件修改

| 文件 | 修改前 | 修改后 | 原因 |
| --- | --- | --- | --- |
| dsh_eval/batch_lock.py、dsh_eval/batch.py | 没有调度锁或批次输入指纹 | 独占内核锁、resumeSupportVersion=1、inputFingerprint，执行循环提取为内部函数 | 为新批次提供可检查的协作与输入基线 |
| dsh_eval/resume.py | 没有续跑入口 | 预览、fresh inspect / 评测、冻结输入及退出事实检查、摘要保护、排他领取、新批次执行 | 防止重复已完成调用和自动重跑未知项 |
| dsh_eval/__main__.py | 仅新任务 / 实验入口 | --resume-batch 配合 --plan / --run，复用上限、预期摘要及宿主参数 | 明确区分只读复核和可能调用模型的执行 |
| test/test_batch_resume.py | 无续跑回归 | 合成适配器与真实 Python / Node 子进程检查 | 覆盖复用、故障边界、原结果保留和重复执行保护 |
| README、进度、架构、批次 / 实验说明、M6 方案、CHANGELOG | 候选续跑能力 | 明确已实现的批次范围与未实现的实验整合 | 保持验证范围准确 |

## 实现与技术取舍

当前进程持有批次目录的一字节内核锁；新批次在模型启动前保存完整冻结输入指纹和协调版本。续跑只能读取该协议产生的批次，按原条目顺序检查冻结输入及执行身份。已有证据经原 evaluator 和真实 Node inspect 重新核对，正常完成且退出已确认的 passed / failed 任务都可复用；running 条目若完整评测已落盘，也可恢复为已完成事实。缺失 / 损坏证据、未知执行、清理不明、原 stop 失败策略均阻止运行。

预览不分配身份或写文件；执行重新复核同一组输入，核对任务上限和必需的预期摘要后，以排他文件领取一次续跑资格。仅未开始项被复制到新目录，调用原 run_batch；原结果与输入不覆盖。新结果区分历史复用、此次新任务与合并观察汇总。运行期间持有源锁，领取文件跨进程退出保留，以防同一源被再次执行。

采用新批次而非直接改写旧批次终态，保留历史证据和原断言。第一版不自动重新安排正在运行或状态未知的项、不解除领取文件，不实现实验汇总回填或跨实验报告。路径检查适配既有 evidence 的 Windows 原生路径拼写，同时要求录制仍在相应执行目录内。

## 验证

测试使用 synthetic provider / model、既有 batch-adapter.js、真实 Python 状态化环境、录制器与 fresh inspect；安装步骤隔离，不连接模型。测试辅助数据在原 runner 检查后统一 evidence / evaluation / batch 的 source=synthetic。

首轮十三项发现五失败、两错误：原生 evidence 路径与严格 POSIX 检查不兼容，以及测试在持锁时用第二文件句柄读取锁字节，均已修正；修正后十三项 / 6.607 秒通过。随后补充 CLI 正常执行、源进度变化和领取后中断三个边界。

| 场景 | 结果与范围 |
| --- | --- |
| 三项计划完成第一项后模拟调度器崩溃 | 复核并复用第一项，只执行后两项，取得新 batchId / caseRunId；原有文件摘要不变，仅新增领取文件 |
| 完整单项评测已落盘，活动进度仍为 running | 恢复该项完成事实，不重复调用 |
| 未知 running、录制截断、退出未确认 | 阻断整个续跑，未分配身份或创建新输出 |
| 冻结输入改变、陈旧摘要、上限不符、非法路径、旧协议 | 拒绝，不启动任务 |
| 原 continue 策略中的历史 failed | 保留失败，新任务通过后总体仍 failed；原 stop 失败仍阻断 |
| 正在运行的调度器、同一源重复领取、领取后进程中断 | 不启动第二个续跑 |
| 专用 Python 进程持锁后实际强停 | 原进程退出后可重新取得内核锁；没有删除领取文件 |
| CLI --plan / --run | 计划与执行使用相同上限 / 摘要；阻断计划返回 2，计划不生成文件 |

最终回归共新增十七项续跑 / 内核锁检查，连同 051 的一项一致性回归，完整 `npm.cmd run test:python` 在获准环境执行 271 项 / 69.890 秒，全部通过。`npm.cmd test` 的 87 项 Node 回归无失败 / 跳过，`npm.cmd run check` 的 43 份 JavaScript 语法及 `python -m compileall -q dsh_eval test` 通过。

使用 `dsh_eval.report.generate_report` 再次独立复核 050 的原实验，新报告 fe3aa844-5e9a-449c-a089-b4c322774ecb 的 planVerification=verified、四实际样本 verified / matched / live，结论仍三通过、一失败、四 skipped；88 份选定原始文件 SHA-256 无变化。实际 CLI 对该旧批次执行 --resume-batch / --plan 返回 2、valid=false、modelCalled=false，明确拒绝缺少协调锁的旧协议，没有补跑任务。

没有新增真实模型任务、提交 / 推送或新云端 CI；既有真实模型失败不因本轮调度器 / 校验改动而重写。

## 风险与后续

首版仅验证当前 Windows 与本地文件系统；POSIX 分支尚未实测。内核锁是协作协议，不能约束绕开协议的程序；摘要 / 领取没有签名、事务读取或 fsync / 断电保证。预览需要锁文件可读写，但不修改文件内容。

领取后若尚未产生新批次结果即中断，需要人工检查，不自动撤销领取。旧批次没有协议元信息，不能升级声明后自动续跑。原实验与浏览器不自动汇总续跑结果；--resume-experiment、跨批次报告和未知项重试策略仍是后续开发。原 050 三通过 / 一失败 / 四跳过历史保持不变。

## 文档同步

新增 [批次续跑说明](../batch-resume.md)，同步 README、docs/progress.md、docs/architecture.md、docs/batch-runner.md、docs/experiments.md、docs/plans/m6-reliability-validation.md 和 CHANGELOG。

同轮修改 Markdown 的 375 个本地文件链接均有效，git diff --check 通过；检查全部 28 份修改 / 新增文件未发现本机实际凭据值。runs / private-notes / secrets 没有已跟踪文件，检查输出命中忽略规则。
