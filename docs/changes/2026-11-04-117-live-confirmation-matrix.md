# 修改记录 117 新规则四任务真实验收

日期为 2026 年 11 月 4 日（Asia/Shanghai）。插件版本 0.1.2。运行实现为 `28490d1` 加工作区 114–116。本批尚未提交。

## 固定输入与执行

使用 [116 实验清单](../../fixtures/evaluation/rename-confirmation.experiment.json)原样执行，两个用例、DeepSeek Flash 单配置、各两轮、failurePolicy=continue，max_samples=4。预检指纹为 `6ff81500dc4bcde6ae2e40dcfa43599145156d52281f79dd1aedbe787d354c05`。预检后 148 份选定代码和输入摘要保持至运行及报告复验结束。

运行命令为 `python -m dsh_eval --experiment fixtures/evaluation/rename-confirmation.experiment.json --run --max-samples 4 --expected-plan-sha256 <上述指纹> --runs-root runs/n4`。experimentId 为 `3d651107-a9fb-433b-b29a-6148e446e75f`。命令退出 0，四项均执行 completed、录制 complete、任务 passed。每任务期限 120 秒，超时用例首次 rename 延迟 1500 ms、工具期限 1000 ms。实际 setup 记录 CLI / SessionStore 0.2.0-rc.2、Cordis 4.0.4。

## 结果

| 用例 / 轮次 | caseRunId | 必需项 | 精确回复诊断 | 实际确认语 |
| --- | --- | --- | --- | --- |
| confirmation / 1 | bb2746a4-68dd-415f-b089-e91e10934b27 | 7 / 7 | passed | `done` |
| timeout-retry / 1 | 723d8331-f0ef-491c-b9ef-5cd05d878706 | 9 / 9 | failed | `**done**` |
| confirmation / 2 | b4fbc365-19ea-484f-a991-b22b0cf584fc | 7 / 7 | passed | `done` |
| timeout-retry / 2 | 92e06c20-1be1-41bf-8499-bcbbcd30bbc5 | 9 / 9 | passed | `done` |

本矩阵共 32 条必需断言通过、4 条诊断中 3 通过 1 失败。第一次 timeout-retry 的 Markdown 加粗由预先声明的确认词规则接受，实际文本继续保留星号。该项精确格式偏差可以从新报告定位。

## 独立工具与快照复核

两个 confirmation 任务的冲突、成功、读回序号均为 call / result 17 / 18、23 / 24、29 / 30；第一轮额外以 35 / 36 读取 guard。两个 timeout-retry 任务的五步链均为 17 / 18 超时、23 / 24 读取源、29 / 30 目标 NOT_FOUND、35 / 36 重试成功、41 / 42 目标读回。

逐项独立读取原 JSONL，按 callId / toolCallId 核对真实参数、精确文本、isError 和先后关系。所有任务各有两次 rename。两个超时任务都在重试前看到源文件原内容和目标缺失。

四个完整快照均精确为 `{"archive/final.txt":"评测\r\n","guard.txt":"keep\n"}`。核对了环境和快照摘要、caseRunId / runId / sessionId、工具预算及 complete=true；宿主 workspace 为空。运行清单 sealed，实际请求头与配置一致。host / supervisor 均无干预、强停或协议错误，stdin writer 已停止；四个 CLI PID 在验收查询时均不存在。

## 独立报告与浏览验证

- 新进程执行 `python -m dsh_eval --report <experiment-result.json> --reports-root runs/n4-reports`，生成 reportId `5664b379-a7b1-4e06-b571-266673dbc83d`。计划 verified，四项 verified / matched / live，changedFields 为空。
- 诊断覆盖 observedSamples=4、missingSamples=0，诊断 passed=3、failed=1、证据不足和未执行均为零；passedSamplesWithFailures=1。该样本的异常 ID 为 answer-exact。
- 80 份选定运行文件、35 份历史 109–112 文件及 148 份代码 / 输入摘要在复验前后保持。四项工具和快照核对也与报告结果一致。
- 浏览器读取层可读取新报告及四份独立评测，按身份定位 56 处工具调用、结果和最终回复事件。前端展示由回归测试验证。
- 独立复核再次读取四份 JSONL，关联全部 17 次调用及结果，并用新进程生成另一份报告。报告汇总、分组、计划核验、样本及独立评测除生成时间和新报告路径外一致；上述代码、归档和历史摘要继续保持。

## 用量与边界

四项合计 21 个已结算模型事件、17 次工具调用、163570 个已报告 totalTokens。inputTokens=31386、outputTokens=1368，保留各字段实际报告值。费用四项缺失，elapsedSeconds 合计约 43.109 秒，包含准备、执行及清理。

本次四项是新冻结规则下的有限验收，不与 109 或其他历史批次合并分母，不推断总体模型稳定性、费用或性能改善。后续不同配置或更多重复应独立计划。同步 README、M6、状态化工具、用例目录及进度。

113–117 的全部 13 份本轮文档有 587 个相对文件链接目标，检查通过；23 份公开用例格式有效，`git diff --check` 通过。
