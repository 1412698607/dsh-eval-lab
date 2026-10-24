# 用例、证据与评测结果格式

更新：2026 年 10 月 24 日，Asia/Shanghai。M3.1 已实现 Python 标准库离线评测；M3.2 新增真实单用例运行及版本 2 证据 / 结果。M3.3 增加兼容版本 1 的版本 2 状态化用例；M6.2 修复增加可选 recorder 配置；M6.3 审查修复增加工具结果的可选 after / textEquals 约束，两个用例版本均可使用。插件仍为 `0.1.2`，格式编号及既有录制格式不变。在仓库根目录运行；实测 Python 3.12.0 / Node.js v24.14.0。

## 运行入口

```powershell
npm.cmd run test:python
npm.cmd run demo:eval
python -m dsh_eval --case 'fixtures/evaluation/read-project.case.json' --evidence 'runs/eval-demo/<demo-id>/<runId>/evidence.json' --output 'runs/eval-demo/<demo-id>/<runId>/evaluation.json'
```

demo 输出两组明确的 casePath / evidencePath，第二组为 missing-file；分别评测。`--output` 可省略，JSON 始终写到 stdout。指定输出时父目录必须存在，且目标文件必须不存在，避免复验覆盖历史结果。命令不选择“最新运行”，不调用模型、不启动 Harness，也不执行用例环境或预算。

退出码：`0` 为任务 passed，`1` 为普通断言 failed，`2` 为 unevaluable、输入格式错误或结果文件写入错误。参数用法错误也返回 `2`。格式无效时输出带 error 的简短 JSON，不能据此建立可信的用例关联。

## 用例：caseFormatVersion 1

参考 [读取用例](../fixtures/evaluation/read-project.case.json) 与 [缺失文件用例](../fixtures/evaluation/missing-file.case.json)。下表除 recorder 外均必需；未知字段、未知版本 / 断言、重复断言 ID、重复 JSON 键和非有限数字会被拒绝。

| 字段 | 约定 |
| --- | --- |
| caseFormatVersion / caseId | 整数 1 / 非空用例标识；标识不是文件路径 |
| input | 非空任务文本，与 user/message 的文本块拼接结果精确相等 |
| environment.files | 相对 POSIX 文件路径到文本内容的映射，允许空对象；拒绝绝对路径、冒号、反斜杠、空 / 点 / 上级分量和文件目录冲突；离线仅保留声明，M3.2 实际写入独立 workspace 并补查 Windows 名称 / 大小写冲突 |
| configRef | provider / model / profile / pluginVersion 四个非空字符串；不得内嵌凭据 |
| recorder | 可选对象，仅允许 maxEventBytes / maxPendingBytes 两个独立正安全整数，范围 1～9007199254740991；不属于模型路由配置，详见下节 |
| budget.timeoutSeconds | 正整数，声明预算；离线评测不会实施它，不支持 token / 步骤上限 |
| assertions | 非空数组，每条有唯一 id 和已支持的 type；所有断言均为必需 |

三种断言：

| type | 必需参数与行为 |
| --- | --- |
| final_text | equals；最后一个非空 assistant/message 的文本块拼接后 strip，再精确比较 equals |
| tool_result | tool、arguments、result；工具名精确匹配，arguments 为非空对象，按顶层键比较所声明参数（允许额外实际参数）；嵌套值完整比较且区分布尔和数字。result.isError 必须是布尔值，可择一添加非空 textContains 或字符串 textEquals；可选 after 引用前面的工具结果断言 |
| turn_end | reason 对象，含非空 kind；与实际结束原因完整比较 |

tool_result 表达“至少存在一组匹配证据”：同一任务内的调用按 callId 与 toolCallId 关联，调用先于结果，结果先于最终答案，答案先于结束。工具名称、参数键和值由用例声明，不硬编码 read_file，也不做路径 basename 或斜杠归一化。多个匹配调用中有一个结果满足即可；声明 after 时还必须满足下节的先后关系。没有调用次数或负向行为断言。

匹配调用及实际结果存在但值不符为 failed；无匹配参数、缺结果、结果晚于答案等不能证明所需事实时为 insufficient_evidence。最终文本不符为 failed。任一必需断言证据不足时总体无法评测，即使另一条已经失败，也保留各条结果。

## 用例扩展：caseFormatVersion 2

版本 2 保留版本 1 的必需字段和断言，允许 environment 增加 stateful 对象，其唯一必需字段 transientReadFailures 为“已有文件路径 → 非负整数次数”的映射，拒绝布尔值。没有 stateful 时仍使用实际文件环境；声明 stateful 后 files 只保存在 Python 内存，workspace 不写入这些文件。版本 1 不接受 stateful。证据和结果仍为版本 2，录制格式不变。示例见 [路径过时](../fixtures/evaluation/stale-path.case.json)、[失败恢复](../fixtures/evaluation/retry-read.case.json)；协议和取消语义见 [状态化工具](stateful-tools.md)。

版本 2 允许 tool_result 的 `arguments` 为 `{}`，表示不限制调用参数值，仍必须有正确工具名、合法对象形式的实际参数、按 callId 关联的结果、预期 isError / 文本约束和正确的任务顺序。非空对象仍逐键精确匹配；版本 1 继续要求非空对象。路径过时用例的发现断言使用空对象，并要求 eval_list 成功返回包含 docs/current.md 的列表，因此根目录 `.` 和 `docs` 都可通过，旧路径失败、读取新文件及答案断言保持原要求。此兼容扩展不增加新版本编号；旧快照中的非空参数约束仍按原语义检查。修复依据见 [记录 014](changes/2026-10-18-014-m3-3-review-fixes.md)。

## 可选工具结果约束：两个用例版本通用

下面两条断言要求先取得 README 的结果，再发起空文件读取，并检查返回文本确实为空：

```json
[
  {"id":"reference","type":"tool_result","tool":"eval_read","arguments":{"path":"README.md"},"result":{"isError":false,"textContains":"empty.md"}},
  {"id":"empty","type":"tool_result","tool":"eval_read","arguments":{"path":"empty.md"},"result":{"isError":false,"textEquals":""},"after":"reference"}
]
```

`after` 必须是 assertions 数组中前面某条 tool_result 的非空 ID。拒绝未知、自身、向后引用、循环、非字符串和指向其他断言类型的引用；final_text / turn_end 不接受 after。后继调用的 callSeq 必须严格大于先行匹配结果的 resultSeq，同批并发发出后继、稍后才收到先行结果也不能通过。只限制声明的依赖，不要求两条独立路径按同一全序执行。

评测按声明顺序计算，选择满足内容和依赖、且 resultSeq 最早的匹配结果，供后继引用。这样既允许并发调用乱序返回，也允许额外调用之后出现完整合法链。结果 evidence 在声明 after 时增加 afterResultSeq，便于核对。已有匹配结果但顺序错误为 failed；先行断言 failed 时后继 failed，先行证据缺失时后继 insufficient_evidence。缺少上下文的单条 after 检查不能通过。

`result.textEquals` 接受任意字符串，包括 `""`，与工具返回的全部文本块拼接结果精确比较，不做 strip；空白或后续非空文本块均不等于空字符串。textEquals 与 textContains 不可同时声明，textContains 仍必须非空。未声明新字段的用例保留原有存在性匹配语义，输入不会自动补字段。

这是可选字段扩展，格式编号不变；新字段需要升级后的读取器，旧严格读取器会拒绝。历史实验仍按原冻结用例复验；当前更严格的用例属于新的完整输入，不能通过改写旧快照补造历史验收。修复与回归见 [记录 028](changes/2026-10-24-028-m6-3-assertion-constraints.md)。

## 可选录制配置：两个用例版本通用

在 caseFormatVersion 1 / 2 的用例顶层添加以下字段，可由原 `--case --run`、`--batch --run`、`--experiment --run` 入口传入：

```json
"recorder": {
  "maxEventBytes": 4194304,
  "maxPendingBytes": 16777216
}
```

两个值单位为 UTF-8 字节，分别覆盖整行事件上限和全录制器待写 Buffer 上限；各自省略时使用当前内置默认值 1048576 / 16777216。允许省略 recorder、空对象或只设置其中一项。拒绝 null、布尔、字符串、非正数、小数、超安全范围数字和未知键；outputDir 由 runner 固定为该执行目录的 traces，不接受用例覆盖。configRef 仍只允许原四字段，不能放入录制限制。

配置优先级为用例显式字段 > 内置默认值；不继承原用户 profile 的录制配置，没有新增 CLI 覆盖或限制环境变量。单用例、批次和实验均保存原样声明的完整用例，不补默认、不归一化历史输入；实验只完整替换 configRef，保留每个用例的 recorder。准备阶段将解析后的两值写到隔离 profile 的 eval-lab config 及 setup.json.recorder，实际记录器再写入 run.json，可沿输入 / 准备 / 运行三层核对。

省略与显式填写当前默认值具有相同的当前运行限制，但仍是不同的冻结输入；报告继续逐字段比较完整快照和计算非 configRef 任务指纹，不能静默互换。录制限制不进入 evidence.configuration、requestedConfiguration 或 provider/model 实际路由匹配；离线评测不会把 recorder 声明重新应用于历史日志，也没有新增录制配置的自动匹配结论。

这是可选字段的兼容扩展，未改变格式编号；旧用例和证据无需迁移，新用例含 recorder 时需要升级后的读取器，旧严格读取器会拒绝该字段。实现与验证见 [记录 026](changes/2026-10-23-026-m6-2-recorder-config-propagation.md)，大小与失败语义见 [资源边界](recorder-resources.md)。

## 证据清单：evidenceFormatVersion 1

适配器或合成演示为一次用例执行生成 evidence.json。最小示例：

```json
{
  "evidenceFormatVersion": 1,
  "caseRunId": "9f6c809b-04f2-41bf-a62b-6a8b6c153ab2",
  "caseId": "read-project",
  "runId": "recorder-generated-id",
  "sessionId": "actual-main-session",
  "runDir": ".",
  "source": "synthetic",
  "configuration": {"provider": "synthetic", "model": "none", "profile": "offline-demo", "pluginVersion": "0.1.2"},
  "budgetEnforcement": {"timeoutSeconds": false},
  "execution": {"status": "completed", "exitCode": 0, "signal": null}
}
```

caseRunId 必须为 UUID，且与录制器 runId 不同；同一执行复验保留 caseRunId。caseId 必须与用例相同，可选 batchId 为非空字符串，本批不产生实际执行批次。runDir 相对 evidence.json 所在目录解析，也接受绝对路径。必须明确 runId、sessionId；首版仅接受检查目录中恰好一个会话，拒绝恢复、fork、多轮任务和子 Agent 范围，不能忽略额外会话。

版本 1 的 source 为 synthetic / live，是证据生产者的来源声明。configuration 格式同 configRef；正常任务必须与用例期望相等，pluginVersion 还要匹配录制 run.json。版本 1 不独立证明 provider / model / profile 与预算实施；M3.2 版本 2 由适配器实际采集并补查请求头。仅填写 live 本身仍不能证明发生过真实模型调用。

budgetEnforcement.timeoutSeconds 为布尔值，合成演示固定 false。execution.status 为 completed / cancelled / timed_out / runtime_error / unknown，可选 reason、exitCode、signal。结束 / 退出证据与 completed 冲突时归为 unknown；cancelled 要求实际 aborted/user，缺少或冲突时也归 unknown。超时、启动 / 路由 / 桥接错误是适配器提供的进程事实，离线模块不执行或推测干预。

## M3.2 新增：evidenceFormatVersion 2

版本 1 输入继续兼容，严格要求录制身份、路径和配置。版本 2 保持相同字段，但允许 runId / sessionId / runDir / configuration 分别为 null，用于启动失败或尚无实际请求的事实，不能拿期望配置或任意 UUID 补齐实际身份。caseRunId 仍必须存在，不能与非空录制 runId 相同。

版本 2 可选 runtimeReport 指向私有运行报告，相对清单解析。单用例驱动生成 runtimeFormatVersion 1 的 runtime.json 和 adapterFormatVersion 1 的 host-result.json：前者保留阶段、监督器和异常细节，后者保留实际选择、请求路由、流通知、子进程退出与清理观察；不是插件录制协议。

版本 2 source=live 的正常任务在原有断言前额外核对：至少有一个 request/header，且全部 provider / model 与清单实际配置一致。没有请求时无法证明实际配置，保持 null 和无法评测。用例 configRef 仍是期望配置，真实驱动实际设置独立 profile 的默认选择，再从事件采集实际路由；配置不符不能 passed。

版本 2 清单产生 evaluationFormatVersion 2 结果，原有版本 1 清单继续产生版本 1。结果关联字段和 configuration 同样允许 null，并新增 association.runtimeReport（清单提供时）；其他三维状态和退出码语义保持不变。工具与最终文本断言没有变化。

真实入口为 `python -m dsh_eval --case <case.json> --run`。其会调用实际模型，写环境文件并实施任务墙钟预算；离线入口仍不执行环境或干预。完整生命周期、预算范围与输出见 [单用例运行](single-case-runner.md)。

## 检查与结果：evaluationFormatVersion 1 / 2

1. 严格加载用例和证据清单，再直接调用 `node scripts/inspect.js --run <runDir>`，检查 JSON 报告与退出码一致。不可用、超时或协议异常归为录制 unverified，不读取旧成功报告替代。
2. 没有明确录制路径时为 unverified，不猜测目录；其他情况重新 inspect。录制不为 complete 时跳过断言。为 complete 时复核 runId、单会话 sessionId 和已知插件版本；关联不符降为 unverified，保留原始 inspection。读取停止写入后的日志或稳定副本；未实现在线一致快照。
3. completed 需要唯一 completed 结束事件，且退出码为 0 或缺失、无信号。正常任务要求唯一真实用户输入、唯一结束、最终文本；消息和工具事件不能越过任务边界。任务范围内出现序号缺口、已知事件结构错误、重复调用 / 返回、孤立或倒序返回时报告证据不足。未知事件类型保留并跳过，不猜测含义。
4. 仅执行正常、录制可验证、输入与配置匹配时运行必需断言。

| 维度 | 值与含义 |
| --- | --- |
| execution | 保留 reportedStatus、适配器退出事实及实际 turnEndReason；status 表示对冲突进行保守处理后的执行状态 |
| recording | complete / invalid / unverified，含原因与本次 Node inspection；complete 只说明片段一致性 |
| assertions | passed / failed / insufficient_evidence / not_run；results 逐条保留 id、type、结论、实际值或原因及证据序号 / callId |
| outcome | 只有执行 completed 且录制 complete，全部断言 passed 才 passed；证据充分且有明确不符为 failed；其余 unevaluable |

输出保留 evaluatedAt（UTC）、完整版本化用例快照（含输入、环境、期望配置和预算）、实际配置声明、预算实施标记、source、caseRunId、caseId、可选 batchId，以及关联的 runId / sessionId / 明确路径。文件缺失与检查错误也保留分类；M4.1 开始增加可选 metrics，历史文件缺少指标仍兼容，见文末扩展。

## 当前限制与下一步

M3.1 离线入口中环境只是声明，合成轨迹不是环境执行、真实工具或模型证据；M3.2 的 --run 才会实际准备环境和驱动任务。日志仍是新增事件片段，不是完整会话备份或重放。SHA-256 不提供签名，sealed 没有 fsync 保证。M6.1 新运行已增加 [会话清单](run-manifest.md)，旧格式仍缺少运行级成员覆盖；清单 / 日志 / 摘要同时重写等限制沿用 [架构](architecture.md)。

M3.1 至 M3.4 已完成当前范围，M4 已增加重复试验、指标与离线配置报告；M5 已提供 [本地只读浏览](result-browser.md) 并完成无模型云端 CI 验收。M6.1 为 Node inspect 增加 `recording.inspection.runManifest` 摘要；新运行清单 invalid / unverified 会阻止任务断言，旧日志保留原任务结果并明确覆盖未知，已有评测持久化版本不变。本批 M6.1 云端未运行。浏览不重跑断言或 Node inspect，也不改变任何已保存格式。合成样例不代替真实模型验收，各层验证分别保留。历史离线与单用例依据见 [修改记录 010](changes/2026-10-16-010-m3-1-offline-evaluation.md) 和 [修改记录 011](changes/2026-10-17-011-m3-2-single-case-runner.md)，当前扩展见文末。

## M3.4 批次扩展

新增独立 batchFormatVersion=1 输入、batchResultFormatVersion=1 清单，命令为 `python -m dsh_eval --batch ... --run`。既有 evidence / evaluation 的可选 batchId 现由真实 runner 填写，单用例格式和版本保持；同 caseId 多次执行用不同 entryId / caseRunId 关联。runtimeReport 增加 preparation.processStarted / processExited、userInterrupted 等观察，不把计划身份当成实际会话。批次预检、冻结输入、状态、策略和相对路径口径见 [批次运行](batch-runner.md)。

2026 年 10 月 19 日为 runtimeFormatVersion=1 添加可选 adapterProcessStarted：false 表示尚未尝试或 Popen 以 OSError 未能创建适配进程，true 表示成功创建，null 表示创建情况尚未确认。旧文件缺字段按未知处理，不能据此认为已清理；本字段不改变 execution、录制与断言三维结果，也不新增实际会话身份。证据、单项结果和批次格式版本不变。修复依据见 [记录 016](changes/2026-10-19-016-m3-4-launch-failure-policy.md)。

## M4.1 实验与观测指标扩展

新增独立 experimentFormatVersion / experimentResultFormatVersion=1，`--experiment ... --run` 展开为标准顺序批次。以 experimentId / sampleId / caseEntryId / configurationId / repeatIndex 映射原 batchId / entryId / caseRunId，不修改 evidence 格式，也不补造实际会话身份。

evaluationFormatVersion 1 / 2 新增可选 metrics（内部 metricsFormatVersion=1）；batchResultFormatVersion 1 的逐项清单新增可选 source / metrics，runtimeFormatVersion 1 新增可选 elapsedSeconds。新 evaluate 总会输出 metrics 对象；旧结果缺字段继续兼容，旧 runtime 无计时则保持 null。指标错误不改变三维结论。

modelCalls 统计已结算 assistant/message / assistant/attempt，toolCalls 统计 tool/call；先 fresh inspect、身份关联和闭合任务边界检查。token 逐字段读取 assistant/message.data.usage，缺失 / 未结算 / 失败尝试用量不推算。elapsedSeconds 独立来自匹配 caseRunId 的单调时钟运行报告，包含准备 / 执行 / 清理，不含离线评测。费用仍为 null。所有字段、分母、样本路径和汇总覆盖率见 [重复试验](experiments.md)。

同日审查修复明确有限数值范围：无法表示为有限浮点数的指标单值或 token 字段和保持 null。实验每项指标汇总若求和超出范围，保留观测 / 缺失样本数，总和与均值为 null，并增加可选 reason；不产生 Infinity / NaN，不改变任务结论或样本分母。实验与 metrics 格式仍为版本 1，历史结果不覆写。详见 [修复记录 018](changes/2026-10-21-018-m4-1-metric-overflow.md)。

## M6.2 单条超限的门禁

单条事件超过配置上限时，录制器以 EVENT_BYTES_LIMIT 标记会话失败，整体 inspect 为 invalid；即使已写前缀包含完整工具结果和正确答案，Python 仍返回 unevaluable / assertions not_run。该门禁继续复用原 inspect 结果，没有改变任务断言或结果格式。新增真实 Node 录制 / Python 离线集成回归通过，配置与资源边界见 [录制资源说明](recorder-resources.md)。

## M4.2 独立比较报告

新增 `comparisonReportFormatVersion=1`，通过 `--report <experiment-result.json>` 对一个终态实验生成新的报告目录。原 experiment / evidence / evaluation 格式不变，不改写旧结果；新 evaluations 仍使用原 evaluate 格式。报告保存原始分母、样本关联复核、新旧差异、按用例 / 配置 / 来源分组以及匹配配对差值，指标汇总增加观测范围并保留 reason。

报告自身成功退出 0、输入输出错误 2，与单次任务 passed / failed / unevaluable 的退出码语义分开；原入口不变。完整字段、路径、actual configuration 的核对与不确定性边界见 [配置报告](configuration-reports.md)。
