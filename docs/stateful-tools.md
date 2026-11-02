# M3.3 状态化工具与实时桥接

更新：2026 年 11 月 2 日，Asia/Shanghai。插件保持 0.1.2；caseFormatVersion 兼容 1 / 2；evidence / evaluation 保持 2，录制协议不变。094 新增可选虚拟写入、工具期限与最终状态证据，历史读取验收保留。

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
| eval_write（显式启用） | path、content：相对文件路径及完整文本 | 创建或覆盖虚拟文件；空文本有效，目录 / 文件冲突返回 PATH_COLLISION；成功返回 WROTE: 路径 |

拒绝绝对路径、盘符、反斜杠、空分量、上级和非根点分量，返回 INVALID_PATH。没有真实文件系统读写、重命名或删除操作。状态只取决于路径、操作和该环境当前计数，不按全局调用次数播放答案。每次执行重新创建状态。

## 请求、响应与生命周期

```text
Harness 注册工具体 → fork IPC → Node case-host stdout JSONL
  → Python supervise → StatefulEnvironment.submit / poll → handle
  → Node stdin JSONL → fork IPC → 原工具 Promise → Harness 正常记录工具结果
```

请求字段：type=tool-request、bridgeVersion=1、唯一 requestId、caseRunId、sessionId、operation=read/list/write，读取 / 列举 arguments={path}，写入 arguments={path,content}。响应字段：type=tool-response、bridgeVersion=1、同一组三个身份字段、isError 布尔值、text 字符串。sessionId 先由真实 agent/created selection 消息绑定；Node 和 Python 都校验关联，不能把其他会话请求混入当前环境。取消帧为 tool-cancel，保留版本及三个身份字段，无 operation / arguments。

Python 校验后调度一次操作，就绪后同步提交内存状态；延迟不会 sleep 或阻塞监督循环。同 requestId、同完整请求等待原操作或返回缓存响应，不再次消耗故障 / 延迟次数；同 ID 不同内容拒绝。缓存仅在本次内存环境存活，不提供进程重启恢复或持久化去重。模型重试会产生新 requestId，因而进行下一次操作。

NOT_FOUND / TEMPORARY_READ_FAILURE / INVALID_PATH / PATH_COLLISION / TOOL_TIMEOUT 是普通工具失败；JavaScript 抛出带错误文本的 Error，由真实 Tools 管线生成 isError 结果，模型可以恢复。协议格式、身份错误、桥接断线、发送失败或桥接看门狗到期属于基础设施故障，触发 bridge-error / shutdown，运行归 runtime_error，普通断言不运行。生产入口的桥接看门狗为该工具期限加 1000 ms；未传预算的独立桥接 API 保留原 5000 ms 默认值。它与工具期限、任务墙钟预算分开，不提供任务内 token 或步骤预算。

工具 AbortSignal 触发时移除本地 waiter 并发送 tool-cancel；Python 接收后移除尚未提交的操作，重复或迟到响应不能重新激活调用。任务停止 / 子进程收尾清空待执行操作。已提交的内存写入不会因随后取消回滚；不提供任意外部工具取消保证。卸载拒绝待处理请求并移除监听器；任务停止仍沿用 Agent cancel / idle / flush / 专用进程退出，超清理期限才尝试强停。

## 写入、工具超时与最终状态（094）

版本 2 的 stateful 可选 tools 数组指定 eval_read / eval_list / eval_write，省略时保持原 read / list。可选 toolDelaysMs 是“启用的工具名 → 非负整数毫秒数组”；按该工具的新请求到达次序消费，数组耗尽后延迟为零，重复 requestId 不推进序列。延迟值范围 0～3600000 ms；只延迟执行，不伪造返回正文。每次用例重新初始化文件、延迟与故障计数。

budget 可选 toolTimeoutMs（默认 5000）及 toolTimeoutsMs（按启用工具覆盖），均为 1～3600000 的整数毫秒，只用于 stateful 工具。期限从 Python 收到并调度请求开始；到达期限即返回 TOOL_TIMEOUT，尚未提交的写入不会生效。相等边界按超时处理。监督循环使用单调时钟，等待不超过 100 ms，按最近工具就绪 / 期限及任务剩余时间缩短，并在事件处理中推进；这是受控虚拟操作期限，不是操作系统实时保证，也不覆盖原生 read、shell、HTTP 或其他外部工具。任务墙钟到期优先停止，工具期限不能延长任务预算。

新断言 environment_files.equals 精确比较完整最终文件映射，既检查目标内容，也检查新增文件和其他文件误改。runner 在清理后将 environmentSnapshot 保存到 runtime.json，包含独立版本 1、运行 / 用例执行 / 会话身份、初始环境摘要、工具预算、complete 和最终 files；evidence.json 保存规范 JSON 对象的 SHA-256。离线先 fresh inspect，再检查摘要、身份、输入 / 策略及完整标记；缺失、改动、未结束或取消导致的不完整状态均不能通过。快照不是从答案或工具成功文本推算，也不提供签名认证、任意环境恢复或轨迹重放。

旧证据缺快照时不补造最终状态；新增状态断言为 insufficient_evidence。声明工具预算却缺实际执行标记 / 快照时为 unevaluable。旧读取用例不自动增加工具或新断言。报告和续跑继续复用 evaluate，runtime / evidence 参与原冻结归档核验。

公开示例：[write-retry.case.json](../fixtures/evaluation/write-retry.case.json)，首次写入延迟 1500 ms / 期限 1000 ms，超时后重试成功，读回并检查 guard.txt 未改。示例不纳入旧十用例固定集。

```powershell
# 真实工具注册 / IPC，无模型调用
python -m scripts.smoke_bridge --writes
# 合成录制、监督、状态断言、续跑与报告回归，无模型调用
python -m unittest discover -s test -p test_stateful_writes.py -v
# 显式调用配置中的模型；095 记录了一次真实验收
python -m dsh_eval --case fixtures/evaluation/write-retry.case.json --run
```

实际验证与限制见 [修改记录 094](changes/2026-11-02-094-stateful-writes-tool-timeouts.md)。094 未实现删除、重命名、局部文本编辑、事务回滚，也未执行真实模型任务；[095](changes/2026-11-02-095-live-write-timeout-acceptance.md) 另以公开用例完成一个 DeepSeek Flash 真实写入 / 超时任务，七断言与独立复验通过，其他能力边界保持。

## 审查后补充：管道回写与发现断言

2026 年 10 月 18 日修复：Python 监督循环将工具响应和控制帧入队，由单独写线程串行写入 / 关闭 stdin。响应较大或适配进程停止读取时，监督循环仍能记录 timeout / cancel，并在清理期限后尝试强停自有进程树。尚未开始写入的工具响应在干预后丢弃；已经写入一部分的响应不能由控制帧打断。进程回收后等待写线程停止，runtime.json 的 supervisor.stdinWriterStopped 记录这一事实；异常写入仍报告，不能掩盖已经发生的超时。

用例版本 2 的 tool_result.arguments 允许 `{}`，表示不限定参数值。路径过时用例仍要求真实 eval_list 的成功结果包含目标路径，支持根目录 `.` 或 `docs` 的发现方式；错误工具、错误结果、缺失关联和结果时序检查保持。版本 1 继续要求非空参数对象。

本批新增七项 Python 回归，完整 58 项 Python、42 项 Node、28 个 JS 文件语法与无模型真实桥接四次请求通过。阻塞管道的超时 / 取消 / 进程及写线程回收、大 Unicode 结果、写入错误，以及两条完整合成恢复轨迹分别验证；没有新增真实模型任务。详见 [修复记录 014](changes/2026-10-18-014-m3-3-review-fixes.md)。

## M3.3 原验收验证边界

2026 年 10 月 18 日：51 项 Python、42 项 Node 测试通过；28 个 JS 文件语法通过。不调用模型的真实注册 / IPC 检查四次请求通过；stale-path、retry-read 两个真实模型任务各一次 passed / completed / complete；retry-read 首流后取消得到 cancelled / complete / unevaluable。真实宿主组件与输出子进程回归通过。测试分别覆盖状态隔离、重复请求、错误关联、响应期限、断线、取消和释放监听器；不是每种异常均跑真实模型。

tool_result 断言沿用原有“至少一组关联证据”语义，没有增加跨断言顺序或调用次数规则。受控失败计数保证该环境首次读取目标路径失败；工具结果仍通过实际 callId / toolCallId 验证。版本和证据格式见 [评测格式](evaluation-format.md)，完整本批记录见 [修改记录 012](changes/2026-10-18-012-m3-3-stateful-tools.md)。M3.4 已补 [顺序批次与环境重置](batch-runner.md)，重复统计或模型通过率仍未提供。
