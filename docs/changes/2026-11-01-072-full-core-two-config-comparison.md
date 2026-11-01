# 修改记录 072 完整十用例双配置重复比较

日期：2026 年 11 月 1 日，Asia/Shanghai。类型：配置 / 真实验收 / 文档。插件版本：`0.1.2`。已核实起始 HEAD：`6304697ae94036165b52cf1af580d3eaf5655c3b`；本批不修改生产代码、测试、公共模板或断言。

## 问题与目标

065 已完成两用例 / 两配置 / 两轮的八任务比较，071 已完成单配置四任务的用量停止与连续续跑验收。本批将两个配置扩展到完整十个公开用例、各两轮，固定四十任务上限，复用已交付的分段执行、fresh 预检和版本 3 报告。

本轮只描述这一固定矩阵的实际结果，保留普通失败和所有分母；不通过归一化答案、修改断言或重跑替换样本改善成绩，不跨实验拼接配对。

## 文件修改

| 文件 | 修改前 | 修改后 | 原因 |
| --- | --- | --- | --- |
| docs/core-evaluation.md、guarded-comparison.md | 当前双配置真实范围仅两用例八任务 | 补充完整十用例比较及保留的历史范围 | 区分单配置历史、小批比较和本轮扩大 |
| README、docs/experiments.md、configuration-reports.md | 未记录完整集双配置重复结果 | 链接本轮任务矩阵、配对与指标边界 | 使用者可核对实际覆盖 |
| docs/progress.md、plans/m6-reliability-validation.md、CHANGELOG、本记录 | 完整十用例双配置扩大待执行 | 同步预检、分段执行与独立复验事实 | 原实现和历史验证不覆写 |

## 输入与技术取舍

- 从 core.experiment.json 的十用例清单构造全新忽略目录，保持每个公开用例的提示、虚拟环境、故障状态、预算和断言。仅在副本添加与 065 相同的 modelProviders 声明，两个配置继续使用 baseline=deepseek-official / deepseek-flash、candidate=bailian / qwen3.7-plus。
- 新实验名 full-core-two-config-20261101，repetitions=2、failurePolicy=continue，原计划上限 40。指纹为 `6fb538e441af510ada8b52fc88fa6167a57aa6466aed1ec61f860ce6def73f55`，顺序 repeat-case-configuration，配置相邻执行；没有随机化。
- 各用例 timeoutSeconds=120，准备 / 清理另计。每段 stopAfter=10、stopAfterTokens=300000；两者只控制本段新增任务的后续调度，允许当前任务超出阈值，不是调用次数或费用硬限额。
- 每轮只将刚完成的明确结果交给 fresh 预检，maxSamples 按全部剩余任务计算，再以对应 expected 指纹执行。普通断言失败继续，未知执行、清理不明、原失败停止策略及重复领取仍阻断，不放宽原规则。
- 业务端点和凭据引用继续保存在本机忽略输入中，不进入公开用例、模板或文档；本地凭据存在性检查不输出密钥，不证明远端权重版本或端点未来可用性。

## 验证

环境为 Windows、Python `3.12.0`、Node.js `v24.14.0`，四十份实际任务 setup 的 CLI 均为 `0.2.0-rc.2`；生产代码与起始 HEAD 保持一致。

| 操作 | 实际结果 | 证明的范围 |
| --- | --- | --- |
| `plan_experiment(..., max_samples=40)` | valid=true、modelCalled=false，10 / 2 / 40；指纹如上；十个原用例删除新增 modelProviders 后与公开输入相同 | 完整矩阵和既有任务 / 断言不变 |
| `node scripts/check-model-providers.js <new direct-read case>` | 本地注册和凭据存在性通过，modelCalled=false / endpointVerified=false | 选定百炼路由 / 目录及凭据引用可用，不是模型任务 |
| 两套配置在新短根下的四层 UUID 离线准备 | CLI `0.2.0-rc.2`，隔离 profile 的实际 provider / model 与所选配置一致，准备进程均退出，未调用模型 | 当前短根和两套本机配置的真实宿主准备 |
| 既有来源 SHA-256 基线 | 314 份公开输入和 065 / 071 选定归档文件已建立摘要基线 | 只检查选定原始文件，不扫描 home / workspace / 安装缓存 |
| 原实验 `run_experiment(..., max_samples=40, stop_after=10, stop_after_tokens=300000, expected_plan_sha256=<fresh SHA>)` | 本轮十项，九通过 / 一失败；观测 208233 token，stopReason=stop_after | 完整四十项计划保留，普通失败没有阻断或替换 |
| 三轮 `plan_experiment_resume` / `resume_experiment`，maxSamples 分别为 30 / 20 / 10 | 每轮仅执行十项，各十通过；观测 token 分别为 237506 / 202050 / 243240 | 逐轮 fresh 复核，历史任务不重复执行，阈值只计算本轮新增 |
| `generate_report` 对末轮结果独立复验 | 版本 3；原计划 verified，四十项 verified / matched / live；planned / attempted / finished 均 40，skipped / errors 均 0；39 passed / 1 failed / 0 unevaluable | 全部矩阵执行，不把 verified 当作任务全部通过 |
| 每用例的配置 / 同轮次 / live 条件配对 | 十个用例各 plannedPairs=2、pairedSamples=2、excludedPairs=0 | 普通失败仍进入配对，不跨用例合并效果量 |
| 原始输入与归档 SHA-256 | 最终 1211 份选定输入 / 来源文件摘要不变，其中既有来源基线 314 份；另 42 份报告 / 复验文件读取前后不变 | 每段复核既有文件，新增领取按协议发生，缓存不在摘要范围 |
| ArtifactBrowser 读取层遍历可访问关联及分页 | 448 个文件，其中四十份轨迹共 1247 行，零预览错误 | 保存文件的读取层，未新增页面点击验收 |
| runtime / 运行清单及操作系统 PID 复核 | 四十项准备进程退出，host childClosed=true / exitCode=0 / forceStopped=false，adapterExitCode=0 / stdinWriterStopped=true；四十份运行清单 state=sealed；验收时相关 CLI 均已退出 | 四十次 CLI 运行涉及 38 个不同 PID，PID 可复用，任务身份不依赖 PID 唯一 |
| 四个结果源再次预检 | 均 eligibleForResume=false；前三者已领取，末轮 newSamples=0 | 无重复领取、补写状态或追加任务 |
| 本轮九份 Markdown 的链接 / 标题锚点、Git 跟踪 / 忽略规则、两个 Python 示例 AST、补丁及代码范围检查 | 414 个本地链接 / 104 个目标、两个示例解析及 git diff --check 通过；生产代码、测试、公共输入和旧 065 / 071 记录无新差异 | 示例没有再次调用模型，原始产物未纳入 Git |

原实验标识为 `57e137d6-e81d-4f5c-86b6-ba268572c062`，末轮续跑标识为 `a322449d-4c86-499d-bc7d-e7b361729177`，独立报告标识为 `9d8400a2-cd85-44ff-971e-54a1d3cddc8f`，共四个来源批次。

实际四段均执行十项。前三段在任务数阈值处停止，本段 token 总量均低于 300000；本次没有触发 token 阈值，071 的真实 token 停止证据保持独立。原实验及前两轮续跑保留 stopped / failed，末轮为 completed / failed；历史失败没有因后三段新增任务全部通过而变为 passed。最后报告分开历史复用三十项 / 647789 token 与末轮新增十项 / 243240 token。

四十个 caseRunId、runId、sessionId 分别唯一。所有 changedFields 均仅为 configurationMatch：批次行未保存该字段，报告从实际请求路由解析为 matched，任务结果与用量保持一致。

唯一失败为 sample-000008：Qwen 在 current-over-archive 第一轮返回 `**core-current**`。必要工具结果及顺序、正常结束均通过，精确 final_text 因 Markdown 加粗而失败；第二轮同配置通过。没有移除格式标记、修改断言或用新样本替换该失败。

| 用例 | DeepSeek Flash 通过 | Qwen3.7-Plus 通过 | 有效配对 / 计划 | 排除 |
| --- | ---: | ---: | ---: | ---: |
| direct-read | 2 / 2 | 2 / 2 | 2 / 2 | 0 |
| nested-discovery | 2 / 2 | 2 / 2 | 2 / 2 | 0 |
| reference-chain | 2 / 2 | 2 / 2 | 2 / 2 | 0 |
| current-over-archive | 2 / 2 | 1 / 2 | 2 / 2 | 0 |
| missing-file | 2 / 2 | 2 / 2 | 2 / 2 | 0 |
| empty-file | 2 / 2 | 2 / 2 | 2 / 2 | 0 |
| unicode-path | 2 / 2 | 2 / 2 | 2 / 2 | 0 |
| retry-once | 2 / 2 | 2 / 2 | 2 / 2 | 0 |
| independent-retries | 2 / 2 | 2 / 2 | 2 / 2 | 0 |
| stale-then-retry | 2 / 2 | 2 / 2 | 2 / 2 | 0 |

| 配置 | 通过 / 尝试 | modelCalls | toolCalls | 已报告 totalTokens | elapsedSeconds 合计 |
| --- | ---: | ---: | ---: | ---: | ---: |
| DeepSeek Flash | 20 / 20 | 67 | 53 | 433421 | 181.155 |
| Qwen3.7-Plus | 19 / 20 | 69 | 53 | 457608 | 250.344 |

本矩阵合计 modelCalls=136、toolCalls=106、totalTokens=891029。inputTokens=168226、outputTokens=7155，totalTokens 使用实际报告值，不由 input + output 推造。四十项 elapsedSeconds 合计约 431.499 秒，包含准备 / 执行 / 清理，不是纯模型延迟或整个验收流程耗时；费用四十项均缺失，保持 null，不能由 token 差值推算费用改善。

## 风险与后续

每个用例只有两对计划样本，顺序固定，厂商 usage / 缓存计数口径可能不同；差值只能解释为当前 verified / matched / live 配对子集的观测值，不推断总体配置优胜、显著性、因果或成本 / 性能改善。

历史 050 的失败停止和跳过、065 的八任务失败及 071 的单配置用量停止结果保持原样。本批没有修改录制、评测、浏览或报告算法，没有重跑完整本地代码回归、提交 / 推送或触发新 CI；既有代码提交的 CI 不自动覆盖本批数据与文档，后续文档提交独立核对。

## 文档同步

同步固定集、比较 / 报告说明、README、进度、M6 顺序及 CHANGELOG。公开链接仅指可提交资料，原始轨迹、业务端点、凭据和安装产物不加入 Git。
