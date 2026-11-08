# 修改记录 099 工具控制组合验证与统一三任务验收

日期：2026 年 11 月 3 日，Asia/Shanghai。类型：测试 / 验收 / 文档。插件版本：0.1.2。相关 Git 提交：本批尚未提交；起始 HEAD 为已核实的 f2759cf，实现基线 ca45099。未修改生产执行、评测逻辑、公开用例或实验清单。

## 问题与目标

此前测试主要验证单个工具的期限、取消和重试，缺少多个请求并存时的隔离与任务总期限组合覆盖。097 的真实通过证据分布在原正常任务及两个补验任务中，尚无修正后同一冻结清单的完整三任务结果。

本批补充组合回归及无模型真实组件入口，并按现有修正清单执行三个新真实任务。沿用原语义，不为通过验收改变工具期限、取消、快照或任务判定规则。

## 文件修改

| 文件 | 修改前 | 修改后 / 原因 |
| --- | --- | --- |
| [test_tool_control.py](../../test/test_tool_control.py) | 无独立组合回归 | 六项测试：多请求期限 / 单独取消、迟到取消与重复请求、提交后取消、真实子进程组合及任务总期限 |
| [tool-bridge.test.js](../../test/tool-bridge.test.js) | 单请求错误 / 取消 / 超时为主 | 新增两个等待者隔离测试，迟到 / 重复响应不完成其他请求或重试 |
| [smoke_bridge.py](../../scripts/smoke_bridge.py)、[smoke-bridge.js](../../scripts/smoke-bridge.js) | 读取、写入、删除 / 编辑组件模式 | 新增互斥 --control 模式，三个请求同时待处理，分别超时 / 成功 / 取消，并实际读回状态 |
| README、stateful-tools、M6 方案、用例目录、progress、CHANGELOG、本记录 | 分批真实验收及原单工具验证范围 | 增加组合验证边界和统一实验结果，保留旧失败与旧清单 |

## 实现与技术取舍

- Python 虚拟时钟测试将三个不同工具同时置于 pending，分别触发超时、单独取消及正常提交，核对其他请求和文件不受影响；重复已超时 requestId 仍返回缓存错误，不推进尝试次数。
- 真实 Python 子进程通过 stdin / stdout 与原 supervise 通信：单独取消写入时编辑与删除继续完成；写入工具先超时而编辑仍成功；任务预算 1 秒、三个工具延迟 5 秒 / 工具期限 10 秒时，任务停止清空全部 pending，随后推进时钟也不能提交。这些是停止与清理行为，不是总退出耗时硬上限。
- Node 两个新测试同时维护多个 Promise，分别处理单独 abort 与正常 TOOL_TIMEOUT 响应，再送入迟到 / 重复响应。使用不同 requestId 的重试只接受自己的响应；已终结请求的迟到帧不会误触发另一请求的身份错误或成功。
- --control 使用实际 Cordis / Tools 注册和真实 fork IPC。读取期限 100 ms / 延迟 600 ms；编辑期限 2000 ms / 延迟 250 ms；删除期限 3000 ms / 延迟 1000 ms，并单独取消删除。之后读回 settings.txt 已更新、obsolete.txt 和 guard.txt 保留，共六请求；工具期限配置由 Python 检查脚本传给专用 Node 子进程，公开用例不修改。
- 单独取消不妨碍其他操作提交，但原环境快照仍会因取消过未提交操作而保守标记 incomplete。测试明确保留该约束，不将其改为整项任务必然 passed。已提交操作不因迟到取消回滚，不能据此推定外部系统恰好一次执行。

## 无模型验证

| 命令或操作 | 实际结果 | 范围 |
| --- | --- | --- |
| `python -m unittest discover -s test -p test_tool_control.py -v` | 六项通过，1.760 秒 | 虚拟时钟状态组合及三个真实 Python 子进程场景 |
| `node --test --test-isolation=none test/tool-bridge.test.js` | 十项通过 | 新增两个多等待者 / 重试隔离反例及原桥接行为 |
| `python -m scripts.smoke_bridge --control` | passed，六请求 | 真实工具注册 / IPC，并存请求的超时、单独取消和实际读回；无模型 |
| `python -m scripts.smoke_bridge --mutations` | passed，15 请求 | 原删除 / 编辑、超时与取消组件入口在新参数传递后仍兼容 |
| `npm.cmd run test:python` | 完整 483 项通过，303.641 秒 | 原评测 / 续跑 / 报告与新增工具控制组合，无模型调用 |
| `npm.cmd test` | 完整 123 项通过，7.152 秒 | 包含新桥接测试与原真实子进程生命周期回归 |
| `npm.cmd run check`；`python -m compileall -q dsh_eval scripts test` | 45 个 JavaScript 文件及 Python 编译通过 | 语法检查 |

完整 `npm.cmd run test:python` 通过 483 项，303.641 秒，零失败 / 错误。定向、全量和组件检查没有发现需要修改生产逻辑的缺陷；本批不改变用例或运行协议。最终文档检查单列于下方文档同步。

## 统一真实实验

使用现有 [stateful-mutations.experiment.json](../../fixtures/evaluation/stateful-mutations.experiment.json)，三个用例、单配置 deepseek-official / deepseek-flash、各一次，明确 max_samples=3。预检与执行使用同一指纹 `c22e1338d1fe2886f2a2fddae0bc43a5675248176e516c2a38321486876ed45b`，与 097 修正后的公开完整清单预览一致；原用例、预算及断言未改动。

实验 ID：`9d306fb3-d9c7-476b-9132-76d3a7dfd82b`；独立报告 ID：`5a46c573-e096-4df0-97d4-32f435c1b6bd`。输出根为通过 Windows 路径预检、已被忽略的 `runs/m`，报告另存于 `runs/m-reports`。

本次实际 setup 为 CLI / SessionStore 0.2.0-rc.2、Cordis 4.0.4；运行环境为 Windows、Python 3.12.0、Node.js v24.14.0。每任务 timeoutSeconds=120，准备和清理另计；任务数和墙钟预算不是费用 / token 硬限额。

| 用例 | 执行 / 录制 / 断言 | 断言数 | 已结算模型调用 | 工具调用 | 已报告 totalTokens |
| --- | --- | ---: | ---: | ---: | ---: |
| edit-delete | completed / complete / passed | 8 | 5 | 4 | 39357 |
| edit-delete-errors | completed / complete / passed | 7 | 3 | 2 | 23132 |
| edit-delete-timeout | completed / complete / passed | 10 | 7 | 6 | 57418 |
| 合计 | 三项均通过 | 25 | 15 | 12 | 119907 |

planned / attempted / finished 均为 3，failed / skipped / errors / unevaluable 均为 0。报告三项 verified / matched / live，plan verified，changedFields 均为空。这是本次同一冻结清单下的三项通过；097 的首轮失败与分批补验不合并、不覆盖，也不推断总体模型成功率。

inputTokens=23573、outputTokens=1486，totalTokens 保留实际报告值，不通过相加补算；cost 三项均缺失。elapsedSeconds 合计约 29.907 秒，含准备 / 执行 / 清理，不代表纯模型延迟或完整验收流程时间，没有性能或费用改善结论。

## 独立验收与原始证据

| 实际操作 | 结果 | 边界 |
| --- | --- | --- |
| `plan_experiment(..., max_samples=3)` 与 Windows 输出预检 | valid、modelCalled=false，3 / 1 / 3，指纹如上 | 固定任务范围，不调用模型 |
| `run_experiment(..., max_samples=3, expected_plan_sha256=<预检指纹>)` | 新实验 completed / passed，三项实际执行，无追加任务 | 普通三个用例的真实模型任务；不等于真实模型主动取消验收 |
| 新进程 `python -m dsh_eval --report <实验结果> --reports-root <独立报告根>` | 三项重新 inspect / evaluate，计划、配置、身份与来源核对通过，结论保持 | 独立只读复验，无模型调用 |
| 报告前后选定源文件 SHA-256 | 本次 64 份、097 历史两批 109 份摘要保持 | 排除 home / workspace / 安装缓存；不修改原报告或日志 |
| 预检时 109 份代码 / 输入摘要 | 真实运行及报告后保持不变 | 文档不计入该集合；执行与评测逻辑及公开输入稳定 |
| runtime / host / setup / run 清单检查 | 三项正常退出、无强停 / 协议错误 / 监督干预，stdinWriterStopped=true，完整状态快照，清单 sealed | 限定本次专用任务 |
| OS 查询 CLI PID 30092 / 30148 / 37088 | 验收时均不存在 | 不推定任意外部进程树 |
| ArtifactBrowser 读取报告、三份 evaluation 及十处工具结果 | 全部可读，按 runId / sessionId / seq 正确定位 | 读取层检查，无新增实际页面点击验收 |

三份录制分别为 43 / 31 / 55 条事件、59631 / 49353 / 72227 字节。状态断言分别验证正常编辑 / 删除结果、预期错误后的完全不变、双工具超时重试后的最终结果。

## 风险与后续

本批控制组合由合成传输和无模型真实组件验证，普通完整清单由三个真实模型任务验证，二者范围分开。没有新增模型驱动的单独取消或多请求并存场景，没有跨会话 / 多 Agent / 多平台验证。每用例仅一个新样本，不据此推断独立性、稳定性或模型总体表现。

原生文件 / HTTP / 数据库工具的取消和副作用、事务回滚、任务内 token / 步骤硬限额仍不在本批范围。原记录器保持片段录制语义，不声称确定性重放或完整会话恢复。

本批未提交 / 推送或新增远端 CI；f2759cf 的历史交付与 CI 不作为本次修改的新 CI。原始运行与凭据引用保持在忽略目录。

## 文档同步

同步 README、CHANGELOG、progress、stateful-tools、M6 方案及用例目录；格式与生产架构未改动。096–098 的历史验证和失败描述保持，新的统一实验结果独立记录。

最终七份文档的 474 个相对文件链接目标检查通过，`git diff --check` 通过。复核本轮 / 历史合计 173 份选定运行文件与 109 份代码 / 输入摘要保持，公开计划指纹未变。原始输出保持在忽略目录，未纳入版本管理。
