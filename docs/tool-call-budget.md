# 受控工具调用预算

更新：2026 年 11 月 16 日，Asia/Shanghai。

本次改动和实际验证记录见 [143 受控工具调用预算](changes/2026-11-16-143-controlled-tool-call-budget.md)。

`budget.maxToolCalls` 限制单次用例执行中 Python 状态化环境接纳的新工具请求数。它覆盖已启用的 `eval_read`、`eval_list`、`eval_write`、`eval_delete`、`eval_edit` 和 `eval_rename`，所有工具共用一个计数。工具行为与延迟 / 超时策略见[状态化工具](stateful-tools.md)。

## 配置与停止边界

在已有 `caseFormatVersion: 2` 且声明 `environment.stateful` 的用例中，可添加：

```json
"budget": {
  "timeoutSeconds": 120,
  "maxToolCalls": 3
}
```

`maxToolCalls` 必须是 0～9007199254740991 的整数，布尔值、浮点数、负数和超出范围的整数均拒绝。版本 1 或未声明 stateful 的用例不能配置此字段。省略时保持原来的无限次受控工具请求策略，不为旧用例补写字段；`timeoutSeconds` 等既有期限仍生效。

上限为 N 时，前 N 个合法新请求可以进入环境。恰好接纳第 N 个请求不会停止任务；第 N+1 个合法新请求被拒绝时，才标记预算耗尽并启动任务停止。N=0 时首个合法新请求被拒绝；如果任务没有发起受控工具请求，不会仅因上限为零而停止。每次用例执行重新计数，不跨样本、重复试验或续跑样本共享余额。

## 计数发生在 Python 接纳入口

处理顺序为：

```text
Host 工具体发出桥接请求
  → Python 校验协议、执行 / 会话身份、操作及参数结构
  → 检查相同 requestId 的缓存或 pending
  → 为合法新请求检查并消耗一个名额
  → 进入 pending，按工具延迟与期限执行，或返回超限错误
```

Python 在新请求进入 pending 前扣减名额，直接调用环境的 `handle()` 也经过同一预算入口。`poll()` 只执行已接纳项，不重复扣减。已有 pending 请求不能通过直接调用 `handle()` 绕过延迟或期限。

| 情形 | 是否消耗一个新名额 |
| --- | --- |
| 合法新 requestId，预算仍有余额 | 是，在排队或执行前消耗 |
| 已接纳请求返回普通工具错误、超时或被取消 | 已消耗，不返还 |
| 相同 requestId、相同完整请求重送 | 否，继续等待原 pending 或返回缓存 |
| 相同 requestId、不同请求内容 | 否，报协议冲突 |
| 桥接协议、身份、操作或参数结构校验失败 | 否，请求未获接纳 |
| 结构正确，但文件缺失、路径非法或编辑匹配失败 | 是，属于接纳后的工具执行错误 |
| 超过上限的合法新请求 | 不增加 admitted；增加 rejected，并触发预算停止 |

超限请求不执行文件操作，不推进该工具的延迟序列，不消耗 `transientReadFailures`。同一个被拒绝的 requestId 重送会返回缓存，不重复增加 rejected。故障重试使用新的 requestId，因此成功重试前的失败调用也计入上限。

这里的 admitted 与录制的 `tool/call` 数量具有不同边界。Host 可能先记录调用，再在执行工具体之前拒绝参数；这样的调用没有到达 Python，不占用此预算。录制调用数量、受控请求接纳数量以及成功工具结果数量不能相互替代。离线评测也不要求 admitted 等于录制 `tool/call` 数量；按录制事件检查行为次数时，仍使用既有 `tool_call_count` 断言。

## 超限错误、取消与结果分类

首个超限请求得到缓存的桥接响应，关键字段为：

```json
{
  "isError": true,
  "text": "TOOL_CALL_LIMIT_EXCEEDED: <path>",
  "errorCode": "TOOL_CALL_LIMIT_EXCEEDED"
}
```

完整响应仍携带既有的协议版本和执行 / 会话 / 请求身份字段。环境立即取消尚未提交的 pending 操作；随后轮询、迟到响应或重送不能使这些操作重新生效。此前已完成的文件修改保留，不进行事务回滚。环境层后续收到的合法新请求同样拒绝；supervisor 启动停止后会忽略已经排队到达的后续工具请求，不再恢复执行或继续接纳。

supervisor 先排入超限响应，再发出 `tool_budget` 控制消息。Node case-host 保存该干预原因；已有会话时，沿现有 cancel 通道通知子进程，完成收尾，超过清理期限才进入强停处理。预算停止与任务墙钟超时、用户取消分别分类；已经先发生的停止原因保留。

监督器已经观察到适配进程退出或closed后，不再接纳残留工具请求，也不提交已就绪的pending操作；取消未提交工作并记录协议错误，避免退出后仍修改状态。已有预算、超时或取消原因保持；这不提供与外部进程死亡瞬间的原子事务。复查依据见[144](changes/2026-11-16-144-controlled-tool-budget-review.md)。

| 产物字段 | 预算触发停止时的值 |
| --- | --- |
| `runtime.supervisor.intervention` | `tool_budget` |
| `execution.status` | `budget_exceeded` |
| 评测 `outcome` | `unevaluable` |
| `assertions.outcome` 及普通断言结果 | `not_run` |
| `runtime.environmentSnapshot.complete` | `false` |

录制可以正常收尾并被检查为 `complete`，这不改变执行已被预算停止的事实。即使最后保留的文件恰好满足状态期望，也不会据此把预算中断任务判为通过。若缺失 host 收尾报告，Python 已观察到的 `tool_budget` 仍保留为 `budget_exceeded`。

## 证据字段与离线复验

配置预算并建立受控环境后，`evidence.budgetEnforcement.maxToolCalls` 标为 `true`。`runtime.json` 的 `environmentSnapshot.toolCallBudget` 和 `supervisor.toolCallBudget` 保存同一份五字段状态：

```json
{
  "toolCallBudgetFormatVersion": 1,
  "limit": 3,
  "admitted": 3,
  "rejected": 0,
  "exhausted": false
}
```

`limit` 是配置上限，`admitted` 是已接纳的新请求数，`rejected` 是因上限拒绝的新请求数。`exhausted` 表示已经发生超限拒绝，不是“当前接纳数等于上限”。取消未提交请求不会减少 admitted；环境内去重缓存只属于当前进程，不提供重启后恢复。

既有 `environmentSnapshot.toolBudget` 继续保存工具策略，其中包含已配置的 `maxToolCalls`。快照整体参与 `evidence.environmentSnapshotSha256`，同时绑定用例执行 / 会话 / 录制身份、初始环境、工具策略和最终文件。

对声称 `completed` 的任务，离线评测检查 enforcement 标记、快照摘要、身份与策略绑定，以及精确的五字段预算状态。上限须与用例一致，计数须为合法整数，admitted 不超过上限、rejected 为零、exhausted 为 false；supervisor 的预算状态须与快照一致，supervisor / host 不得保留停止干预。还需核对监督器无协议错误且退出0，以及host无错误、已关闭、未强停、退出0且无信号、协议有效且结束原因为completed。缺证或相互矛盾的完成事实无法通过，不会从最终答案或录制调用数补造预算事实。摘要用于一致性检查，不认证一组被同步重写的材料。

没有配置 `maxToolCalls` 时，不新增 `toolCallBudget` 或对应 enforcement 字段，也不补写case默认值。case、evidence、runtime与snapshot版本号保持；新可选字段及budget_exceeded状态需要升级后的读取器，旧严格读取器可能拒绝新产物。既有日志与历史验证结果不回写。

## 批次、报告与续跑

预算属于完整冻结用例，进入既有批次 / 实验输入指纹；改变上限就改变输入，不修改已完成样本的原预算。每个新用例执行独立计数，报告保留budget_exceeded执行状态和unevaluable任务结论；这些样本不能当作成功或补为缺失的零次调用。

批次沿原failurePolicy处理该unevaluable结果：stop时结束后续安排，continue时在清理事实允许的前提下继续下一样本。预算只限制当前用例，不把剩余次数转给下一样本。来源续跑复验要求已执行项正常completed且passed / failed；含budget_exceeded的已开始项会阻断来源续跑，不会自动重试该项、把它当未开始或恢复进程内余额。具体预检与清理约束见[批次续跑](batch-resume.md)。

## 无模型复现与验证范围

在仓库根目录运行：

```powershell
python -m unittest discover -s test -p 'test_tool_budget*.py' -v
```

环境与格式回归检查零预算、上限边界、六种受控工具的拒绝无副作用、失败 / 超时 / 取消扣减、请求去重与冲突，以及旧用例兼容。runner 回归用固定合成步骤通过真实管道执行和录制，检查正常完成、预算停止、最终状态、证据篡改和独立离线复验。

其中 IPC 检查使用生产 `case-host.js`、共享工具注册 / bridge 实现及真实 Node fork 通信，验证拒绝响应先于停止、未提交编辑取消、Promise 收尾、监听器清理和子进程退出。夹具中的 `defineTool` 为直接返回定义的身份函数，事件和任务步骤由脚本提供；未加载 Harness runtime，也未调用模型。这些结果不构成真实 Agent 的规划、重试选择或模型端到端验收。

预算仅覆盖本项目 Python 环境实际接纳的受控桥接请求，不限制 Host 原生文件工具、shell、HTTP、其他插件工具、模型调用次数、token 或费用，也不构成任意外部工具的副作用取消保证。任务墙钟期限与工具期限继续按各自已有规则执行。
