# 带计划约束的小批真实验收

更新：2026 年 10 月 25 日，Asia/Shanghai。本入口复用现有 experiment / batch / runner / report，验收任务数上限、预期计划指纹、原始载荷快照和离线复核的完整链路；没有新增运行格式或调度器。

## 固定范围与运行

[guarded-acceptance.experiment.json](../fixtures/evaluation/core/guarded-acceptance.experiment.json) 引用已有 direct-read / retry-once 两个版本 2 用例，使用 deepseek-official / deepseek-flash、headless、插件 0.1.2。各重复 2 次，共 4 个计划任务，failurePolicy=stop；顺序为第一轮直接读取、失败后恢复，再按同一顺序进行第二轮。每项独立工作区 / home / 会话 / 故障状态，timeoutSeconds=120，准备与清理另有期限，不是费用限制。

先运行无模型回归，再预览：

```powershell
python -m unittest discover -s test -p test_guarded_acceptance.py -v
$plan = python -m dsh_eval --experiment fixtures/evaluation/core/guarded-acceptance.experiment.json --plan --max-samples 4 | ConvertFrom-Json
```

核对 valid=true、counts=2 / 1 / 4、maxSamples=4、failurePolicy=stop 和明确配置。以下命令会调用真实模型，执行前确认本次任务规模；使用短输出根，保留返回的 experimentDirectory：

```powershell
python -m dsh_eval --experiment fixtures/evaluation/core/guarded-acceptance.experiment.json --run --max-samples 4 --expected-plan-sha256 $plan.planFingerprint.sha256 --runs-root runs/g44
```

默认复用已安装的匹配版本宿主，也可显式传 --host-modules。每项只在新 home 离线安装本地插件，并引用既有凭据路径，不复制密钥或修改原 profile。失败即停止后续项并保留 skipped，不自动重跑。任务数不等于模型调用数，计划仍不估算 token / 费用。

执行后对真实保存路径生成报告，这一步不调用模型：

```powershell
python -m dsh_eval --report 'runs/g44/<experimentId>/experiment-result.json'
```

报告应分别核对 planVerification、样本 verification、实际配置、执行 / 录制 / 断言及缺失覆盖；原结果与录制保持不变。计划复核不是任务成功证明，细节见 [实验说明](experiments.md)、[配置报告](configuration-reports.md) 和 [单用例生命周期](single-case-runner.md)。

## 044 实际验收

本批进行真实模型链路验收。无模型新增 3 项 / 0.967 秒、获准完整 241 Python / 50.782 秒及 compileall 通过。测试覆盖固定规模 / 顺序 / 配置 / 停止策略、超限 / 指纹冲突先于执行拒绝，以及四样本真实 Node 合成适配器到离线报告的链路；这些测试没有调用模型。

真实运行使用 Windows、Python 3.12.0、Node v24.14.0、CLI / SessionStore 0.2.0-rc.2、Cordis 4.0.4。先后保留两个独立实验：

| 实验 | 实际结果 | 模型任务与证据 |
| --- | --- | --- |
| 5ffa19f5-3d81-4640-b7cb-fae7df402d42 | stopped / unevaluable；planned=4、attempted=1、finished=1、skipped=3 | 第一项准备失败，尚未启动 Agent / 模型；没有录制 / 实际路由，模型调用指标保持缺失 |
| 16777431-b937-4345-a37a-4a9edb7bb472 | completed / passed；planned=4、attempted=4、finished=4、skipped=0、errors=0 | 4 个实际模型任务均 completed / complete / passed；实际路由均 matched，source=live |

首轮输出目录嵌套过深，当前宿主 plugin add 在 `.plugin-manager/logs/operation-XXXXXX` 的 mkdtemp 报 ENOENT。runtime 明确停在 prepare，adapterProcessStarted=false；原失败和三个 skipped 保留。改用短目录先单独验证离线准备成功，再在 runs/g44 执行上述四个真实任务。该准备复查没有调用模型，也没有重跑已经调用过模型的任务。此处记录本机当前宿主的深目录兼容问题，不推定所有 Windows 版本或文件操作都存在同一限制。

| 顺序 | 用例 / 重复 | 执行 / 录制 / 断言 | 已结算模型事件 | 工具调用 | 已报告 totalTokens |
| --- | --- | --- | ---: | ---: | ---: |
| 1 | direct-read / 1 | completed / complete / passed | 2 | 1 | 14896 |
| 2 | retry-once / 1 | completed / complete / passed | 3 | 2 | 22665 |
| 3 | direct-read / 2 | completed / complete / passed | 2 | 1 | 14895 |
| 4 | retry-once / 2 | completed / complete / passed | 4 | 3 | 30216 |
| 合计 | 4 个真实任务 | 全部通过 | 11 | 7 | 82672 |

真实成功实验的三个比例分子 / 分母均为 4 / 4；这是本批固定任务结果，不是模型总体成功率。报告 58c9abe1-3811-467c-91ef-0249ef974515 的计划复核 verified、四项样本复核 verified / matched / live、changedFields 全空；只有一个配置，comparisons 为空，未执行双配置比较。

inputTokens=29027、outputTokens=397、cacheReadTokens=53248、cacheWriteTokens=0，保留原始 usage 的 totalTokens=82672，不用 input + output 补造 total。四项运行 elapsedSeconds 合计 22.282 秒，包含准备 / 执行 / 清理，不是纯模型延迟或总命令耗时。费用四项均缺失，不补零或推断成本提升。

四个 caseRunId / runId / sessionId 分别唯一；四份 run.json 均 sealed，实际默认录制限制为 1 MiB / 16 MiB。host 均 childClosed=true、exitCode=0、forceStopped=false；准备进程退出、stdinWriterStopped=true；四个专用 CLI PID 复查均不存在，范围不扩张到任意外部进程。

两份实验分别离线复验，首轮失败仍为一项 runtime_error / unverified / unevaluable 和三个 skipped，计划复核也可 verified，不能混为任务通过。首轮 22 份、成功实验 80 份选定输入 / 结果 / runtime / setup / 原始输出 / 录制文件在复验前后 SHA-256 不变。另以 --max-samples 3 和错误指纹检查真实 CLI，均启动前返回 2、未建输出目录，没有追加模型任务。

## 边界与后续

044 新增可复用清单和测试，生产执行代码没有改动；其完成时尚未提交 / 推送或验收新云端。随后 [045](changes/2026-10-25-045-plan-review-fixes.md) 复审补齐报告数量检查与正式测试入口范围，独立进行无模型验证和交付。原 M6 十用例和 Web 历史不变。当前只验证现有单配置的两个用例各两次，未扩大到全部十用例重复或第二配置；没有性能 / 费用改善、显著性或模型优胜结论。

041–045 已提交推送为 dffac4c，其新的 Windows CI 实际 243 Python / 85 Node / 41 JS、compileall 与无模型示例通过，见 [交付验收 046](changes/2026-10-25-046-plan-guard-delivery-ci.md)。这次交付没有追加模型任务，不扩大本节四任务真实范围。

原始日志、模型内容、安装缓存和本机路径保存在忽略的 runs 中，公开文档不链接私人证据。修改范围、环境失败与完整验证见 [记录 044](changes/2026-10-25-044-guarded-live-acceptance.md)。
