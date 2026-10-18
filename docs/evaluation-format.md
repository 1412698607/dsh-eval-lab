# 用例、证据与评测结果格式

更新：2026 年 10 月 17 日，Asia/Shanghai。M3.1 已实现 Python 标准库离线评测；M3.2 新增真实单用例运行及版本 2 证据 / 结果。用例仍为版本 1，插件仍为 `0.1.2`，既有录制格式不变。在仓库根目录运行；实测 Python 3.12.0 / Node.js v24.14.0。

## 运行入口

```powershell
npm.cmd run test:python
npm.cmd run demo:eval
python -m dsh_eval --case 'fixtures/evaluation/read-project.case.json' --evidence 'runs/eval-demo/<demo-id>/<runId>/evidence.json' --output 'runs/eval-demo/<demo-id>/<runId>/evaluation.json'
```

demo 输出两组明确的 casePath / evidencePath，第二组为 missing-file；分别评测。`--output` 可省略，JSON 始终写到 stdout。指定输出时父目录必须存在，且目标文件必须不存在，避免复验覆盖历史结果。命令不选择“最新运行”，不调用模型、不启动 Harness，也不执行用例环境或预算。

退出码：`0` 为任务 passed，`1` 为普通断言 failed，`2` 为 unevaluable、输入格式错误或结果文件写入错误。参数用法错误也返回 `2`。格式无效时输出带 error 的简短 JSON，不能据此建立可信的用例关联。

## 用例：caseFormatVersion 1

参考 [读取用例](../fixtures/evaluation/read-project.case.json) 与 [缺失文件用例](../fixtures/evaluation/missing-file.case.json)。字段均必需；未知字段、未知版本 / 断言、重复断言 ID、重复 JSON 键和非有限数字会被拒绝。

| 字段 | 约定 |
| --- | --- |
| caseFormatVersion / caseId | 整数 1 / 非空用例标识；标识不是文件路径 |
| input | 非空任务文本，与 user/message 的文本块拼接结果精确相等 |
| environment.files | 相对 POSIX 文件路径到文本内容的映射，允许空对象；拒绝绝对路径、冒号、反斜杠、空 / 点 / 上级分量和文件目录冲突；离线仅保留声明，M3.2 实际写入独立 workspace 并补查 Windows 名称 / 大小写冲突 |
| configRef | provider / model / profile / pluginVersion 四个非空字符串；不得内嵌凭据 |
| budget.timeoutSeconds | 正整数，声明预算；离线评测不会实施它，不支持 token / 步骤上限 |
| assertions | 非空数组，每条有唯一 id 和已支持的 type；所有断言均为必需 |

三种断言：

| type | 必需参数与行为 |
| --- | --- |
| final_text | equals；最后一个非空 assistant/message 的文本块拼接后 strip，再精确比较 equals |
| tool_result | tool、arguments、result；工具名精确匹配，arguments 为非空对象，按顶层键比较所声明参数（允许额外实际参数）；嵌套值完整比较且区分布尔和数字。result.isError 必须是布尔值，可加非空 textContains |
| turn_end | reason 对象，含非空 kind；与实际结束原因完整比较 |

tool_result 表达“至少存在一组匹配证据”：同一任务内的调用按 callId 与 toolCallId 关联，调用先于结果，结果先于最终答案，答案先于结束。工具名称、参数键和值由用例声明，不硬编码 read_file，也不做路径 basename 或斜杠归一化。多个匹配调用中有一个结果满足即可；本版本没有跨断言顺序、调用次数或负向行为断言。

匹配调用及实际结果存在但值不符为 failed；无匹配参数、缺结果、结果晚于答案等不能证明所需事实时为 insufficient_evidence。最终文本不符为 failed。任一必需断言证据不足时总体无法评测，即使另一条已经失败，也保留各条结果。

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

输出保留 evaluatedAt（UTC）、完整版本化用例快照（含输入、环境、期望配置和预算）、实际配置声明、预算实施标记、source、caseRunId、caseId、可选 batchId，以及关联的 runId / sessionId / 明确路径。文件缺失与检查错误也保留分类；没有采集 token、费用、耗时或调用指标，不填零或推算。

## 当前限制与下一步

M3.1 离线入口中环境只是声明，合成轨迹不是环境执行、真实工具或模型证据；M3.2 的 --run 才会实际准备环境和驱动任务。日志仍是新增事件片段，不是完整会话备份或重放。SHA-256 不提供签名，sealed 没有 fsync 保证。缺少运行级会话清单、日志与摘要同时重写等限制沿用 [架构](architecture.md)。

M3.2 已完成受控单用例真实驱动与异常 / 预算分类；下一批 M3.3 实现状态化工具和实时桥接，再做 M3.4 顺序隔离批次。现有样例不代替路径过时 / 故障恢复的真实桥接验收。验证依据见 [修改记录 010](changes/2026-10-16-010-m3-1-offline-evaluation.md) 和 [修改记录 011](changes/2026-10-17-011-m3-2-single-case-runner.md)。
