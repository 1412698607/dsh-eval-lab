# M3.3 状态化工具与实时桥接

更新：2026 年 10 月 18 日，Asia/Shanghai。插件保持 0.1.2；caseFormatVersion 新增 2，兼容 1；evidence / evaluation 保持 2，录制协议不变。

## 运行

在仓库根目录执行：

```powershell
python -m scripts.smoke_bridge
python -m dsh_eval --case fixtures/evaluation/stale-path.case.json --run
python -m dsh_eval --case fixtures/evaluation/retry-read.case.json --run
```

第一条不调用模型，使用实际 Cordis / Tools 注册共享工具定义、fork IPC、Python 状态，直接调用注册后的工具体检查四次请求。后两条实际调用模型，验证 Agent 工具调用、日志关联、错误恢复与最终答案。匹配宿主和凭据引用要求沿用 [单用例入口](single-case-runner.md)；每次生成全新 caseRunId / home / workspace / 会话，原始输出仍被忽略。

## 环境与工具

版本 2 在 environment.files 外允许增加：

```json
"stateful": { "transientReadFailures": { "project.md": 1 } }
```

映射键必须是 files 中已有文件，次数必须为非负整数，拒绝布尔值。版本 1 不接受 stateful；版本 2 不声明 stateful 时仍使用原有实际文件环境。stateful 存在时，files 留在 Python 内存，不落入 workspace，避免原生 read 绕过故障状态。本功能不声称隔离任意宿主文件或禁用所有原生工具。

| 工具 | 参数 | 行为 |
| --- | --- | --- |
| eval_read | path：相对 POSIX 文件路径 | 缺失返回 NOT_FOUND；该路径故障计数大于零时减一并返回 TEMPORARY_READ_FAILURE；否则返回实际声明的文本 |
| eval_list | path：目录路径，根目录为 . | 递归列出该目录下已声明文件路径，排序后用换行连接；无匹配返回 NOT_FOUND，不消耗读取故障 |

拒绝绝对路径、盘符、反斜杠、空分量、上级和非根点分量，返回 INVALID_PATH。没有真实文件系统读写、重命名或删除操作。状态只取决于路径、操作和该环境当前计数，不按全局调用次数播放答案。每次执行重新创建状态。

## 请求、响应与生命周期

```text
Harness 注册工具体 → fork IPC → Node case-host stdout JSONL
  → Python supervise → StatefulEnvironment.handle
  → Node stdin JSONL → fork IPC → 原工具 Promise → Harness 正常记录工具结果
```

请求字段：type=tool-request、bridgeVersion=1、唯一 requestId、caseRunId、sessionId、operation=read/list、arguments={path}。响应字段：type=tool-response、bridgeVersion=1、同一组三个身份字段、isError 布尔值、text 字符串。sessionId 先由真实 agent/created selection 消息绑定；Node 和 Python 都校验关联，不能把其他会话请求混入当前环境。

Python 校验后同步完成一次操作；同 requestId、同完整请求返回缓存响应，不再次消耗故障次数；同 ID 不同内容拒绝。缓存仅在本次内存环境存活，不提供进程重启恢复或持久化去重。模型重试会产生新 requestId，因而进行下一次操作。

NOT_FOUND / TEMPORARY_READ_FAILURE / INVALID_PATH 是普通工具失败；JavaScript 抛出带该错误文本的 Error，由真实 Tools 管线生成 isError 结果，模型可以恢复。协议格式、身份错误、桥接断线、发送失败或响应超过五秒属于基础设施故障，触发 bridge-error / shutdown，运行归 runtime_error，普通断言不运行。五秒是桥接响应等待期限，任务墙钟预算仍由原 runner 实施；不支持 token 或步骤预算。

工具 AbortSignal 触发时移除本地 waiter，取消后和重复响应不会重新激活调用；卸载拒绝全部待处理请求并移除监听器。Python 已完成的状态操作不会因随后取消而回滚；取消先到监督器后不再接受新操作。没有自动重发、跨进程事务或任意异步外部操作取消保证。任务停止仍沿用 Agent cancel / idle / flush / 专用进程退出，超清理期限才尝试强停。

## 审查后补充：管道回写与发现断言

2026 年 10 月 18 日修复：Python 监督循环将工具响应和控制帧入队，由单独写线程串行写入 / 关闭 stdin。响应较大或适配进程停止读取时，监督循环仍能记录 timeout / cancel，并在清理期限后尝试强停自有进程树。尚未开始写入的工具响应在干预后丢弃；已经写入一部分的响应不能由控制帧打断。进程回收后等待写线程停止，runtime.json 的 supervisor.stdinWriterStopped 记录这一事实；异常写入仍报告，不能掩盖已经发生的超时。

用例版本 2 的 tool_result.arguments 允许 `{}`，表示不限定参数值。路径过时用例仍要求真实 eval_list 的成功结果包含目标路径，支持根目录 `.` 或 `docs` 的发现方式；错误工具、错误结果、缺失关联和结果时序检查保持。版本 1 继续要求非空参数对象。

本批新增七项 Python 回归，完整 58 项 Python、42 项 Node、28 个 JS 文件语法与无模型真实桥接四次请求通过。阻塞管道的超时 / 取消 / 进程及写线程回收、大 Unicode 结果、写入错误，以及两条完整合成恢复轨迹分别验证；没有新增真实模型任务。详见 [修复记录 014](changes/2026-10-18-014-m3-3-review-fixes.md)。

## M3.3 原验收验证边界

2026 年 10 月 18 日：51 项 Python、42 项 Node 测试通过；28 个 JS 文件语法通过。不调用模型的真实注册 / IPC 检查四次请求通过；stale-path、retry-read 两个真实模型任务各一次 passed / completed / complete；retry-read 首流后取消得到 cancelled / complete / unevaluable。真实宿主组件与输出子进程回归通过。测试分别覆盖状态隔离、重复请求、错误关联、响应期限、断线、取消和释放监听器；不是每种异常均跑真实模型。

tool_result 断言沿用原有“至少一组关联证据”语义，没有增加跨断言顺序或调用次数规则。受控失败计数保证该环境首次读取目标路径失败；工具结果仍通过实际 callId / toolCallId 验证。版本和证据格式见 [评测格式](evaluation-format.md)，完整本批记录见 [修改记录 012](changes/2026-10-18-012-m3-3-stateful-tools.md)。M3.4 已补 [顺序批次与环境重置](batch-runner.md)，重复统计或模型通过率仍未提供。
