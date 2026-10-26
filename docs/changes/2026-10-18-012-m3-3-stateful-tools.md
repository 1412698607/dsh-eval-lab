# 修改记录 012 M3.3 状态化工具与实时桥接

日期：2026 年 10 月 18 日，Asia/Shanghai。类型：功能 / 测试 / 文档。插件版本：0.1.2。相关 Git 提交：本批尚未提交；已核实上一批 M3.2 为 `31a24fa`，修正当前版本状态的过时说明。

## 问题与目标

M3.2 只能使用初始实际文件，无法按路径制造暂时工具故障，也不能让运行中的 Harness 取得 Python 环境结果。本批实现虚拟文件与按路径故障计数、真实跨语言请求响应，验收旧路径失败后发现有效文件与暂时读取失败后恢复两个模型任务。

## 文件修改

| 文件 | 修改前 | 修改后 | 原因 |
| --- | --- | --- | --- |
| dsh_eval/environment.py | 不存在 | 虚拟文件状态、read/list、请求校验和内存去重 | 确定性状态核心 |
| dsh_eval/formats.py、__main__.py | 版本 1 用例 | 兼容版本 2 stateful；CLI 帮助更新 | 显式格式扩展 |
| dsh_eval/runner.py | 只处理生命周期事件 | 在监督循环内绑定会话并即时返回环境结果；虚拟文件不落盘 | 运行期间桥接 |
| scripts/case-host.js、fixtures/case-control.js、lib/tool-bridge.js | 只有真实运行控制 | 实际工具注册、JSONL / IPC 转发、取消和响应期限 | 使用宿主接口 |
| scripts/smoke-bridge.js、smoke_bridge.py | 不存在 | 无模型的真实注册与跨进程检查 | 单独证明桥接层 |
| fixtures/evaluation/stale-path.case.json、retry-read.case.json | 不存在 | 两个版本 2 受控用例 | 真实任务验收 |
| test/test_environment.py、tool-bridge.test.js、test_evaluation.py | 无状态测试；拒绝版本 2 | 新增 7 项 Python、3 项 Node 测试，未知版本反例改为 3 | 兼容性与错误语义 |
| README、CHANGELOG、docs | M3.3 待开发 | 当前协议、命令、验证与 M3.4 入口 | 同步范围 |

## 实现与技术取舍

Python 持有 files 和每路径 transientReadFailures。版本 2 的 stateful 为可选扩展，版本 1 仍拒绝该字段；证据 / 结果仍为 2。虚拟文件保存在内存，工作区为空，避免原生文件读取绕过受控故障。宿主保留现有工具，本功能不是任意宿主文件的安全隔离层。

核对本机安装的 CLI/session 0.2.0-rc.2 Tools defineTool、output、execute(args, exec)、exec.agent.session.id 和 exec.signal 后实现注册。共享工具定义由真实 Cordis Tools 服务注册；错误交由其正常管线变成 isError。没有另写 Agent 循环、修改 src、main.py 或录制格式。

复用原控制流：Python 与 Node 适配器 JSONL，适配器与专用 CLI IPC。相较另建 HTTP 服务，现有进程通道不需要端口和额外服务生命周期。请求显式携带版本 / requestId / caseRunId / sessionId / 操作和参数；已绑定会话、唯一执行目录共同限制关联。重复同请求只返回缓存，不重复消耗故障；缓存非持久化。工具错误和基础设施错误分别处理，五秒响应期限后关闭宿主；取消移除 waiter，迟到回复忽略，Python 已完成的操作不回滚。详见 [协议](../stateful-tools.md)。

## 验证

Windows，Node v24.14.0、Python 3.12.0、CLI / session 0.2.0-rc.2、Cordis 4.0.4；真实模型路由从 request/header 采集并由离线重新核对，为 deepseek-official / deepseek-flash。

| 命令或操作 | 结果 | 证明的范围 |
| --- | --- | --- |
| npm.cmd run check / npm.cmd test | 28 个文件 / 42 项通过 | JavaScript 语法和含错误身份、期限、断线、取消的桥接单测 |
| npm.cmd run test:python | 获准环境 51 项通过 | 原 44 + 新 7，状态与去重、文件不落盘、格式兼容、真实子进程往返 |
| python -m scripts.smoke_bridge | passed，四次请求，modelCalled=false | 实际 Cordis / Tools 注册与 Python 状态、fork IPC；直接调用注册工具体，不是完整 Agent 循环 |
| python -m dsh_eval --case fixtures/evaluation/stale-path.case.json --run | passed / completed / complete；43 条、54879 字节 | 旧引用读取、缺失错误、发现新路径、读取与最终答案全部关联通过 |
| python -m dsh_eval --case fixtures/evaluation/retry-read.case.json --run | passed / completed / complete；37 条、50862 字节 | 同一路径真实工具失败后继续、获得文件与最终答案通过 |
| retry-read 同入口加 --cancel-after-stream | cancelled / complete / unevaluable，断言 not_run | 真实首流后取消；不保证此时已执行工具 |
| 查询三个专用 Harness PID | 均退出；childClosed=true、forceStopped=false | 本次受控进程清理 |
| npm.cmd run smoke:host / npm.cmd run check:output | 六条组件事件及 normal / write-error / abrupt-exit 通过 | 原有真实组件与真实子进程回归 |
| Python compileall | 通过 | Python 语法 |

第一次状态化运行沙箱 fork EPERM，caseRunId 7aa2f0b8-11bb-4844-b0eb-b89a63d8a245 为 runtime_error / unverified / unevaluable，未作为成功。首次 Python 测试发现旧版本反例仍把 2 当未知，已更新为 3；强停检查沙箱权限失败，在获准环境重跑 51 项通过。未用 mock 替代真实输出或模型检查。

本机忽略目录中最终路径过时 caseRunId f3b4f16d-16d1-4e08-9cdd-685939584126、runId 5a334b37-cda1-4aa3-98e7-1451fe07c621；暂时失败恢复 44c9da1a-5db4-4e9d-a053-900cc8f956fd、runId 25dfb702-dc01-436c-92c9-3c9fa83d316a；取消 dd06e80f-4844-4389-9ceb-f4e023fe9524。这些编号只用于核对，不作为公开文件依赖。结果均保留，不覆盖历史。

## 风险与后续

内存去重不支持重启恢复；读取操作提交后取消不回滚。只实现同步虚拟 read/list，没有并发批次、状态写工具、任意外部异步操作取消或持久化环境。断言继续使用至少一组匹配证据，不额外证明跨断言顺序或精确调用次数。两个真实任务各一次，不能报告成功率、成本或性能提升。验证限定当前 Windows 与组件。

下一批 M3.4：Python 顺序批次调度、每次隔离重置、版本化批次结果清单及明确的继续 / 停止策略。剩 M3.4、M4、M5 三个主要阶段，M4 拆两批，共四批。

## 文档同步

已更新 README、CHANGELOG、progress、architecture、评测格式、单用例入口、M3 路线、公开用例说明。公开文档不依赖私人材料或原始日志。25 份公开 Markdown 的 103 个本地链接有效，目标无忽略依赖；三个实际任务均使用各自 case 快照重新离线检查，保持原分类。git diff --check 通过，仅行尾转换提示。runs / private-notes 无跟踪文件且忽略有效。
