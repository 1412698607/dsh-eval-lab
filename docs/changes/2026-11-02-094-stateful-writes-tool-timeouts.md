# 修改记录 094 受控写入、最终状态与工具级超时

日期：2026 年 11 月 2 日，Asia/Shanghai。类型：功能 / 测试 / 文档。插件版本：0.1.2。相关 Git 提交：尚未提交；起始 HEAD 为已核实的 8129678。

## 问题与目标

原受控环境只有 read / list，故障注入局限于暂时读取失败；任务仅有整体墙钟预算，桥接五秒超时按基础设施错误处理，不能验证写入结果及模型对工具超时的恢复。

本批增加可选虚拟文件创建 / 覆盖、最终完整文件集合断言、默认及按工具配置的期限、延迟注入和待执行写入取消。旧用例不增加工具、不修改历史固定集或模型样本。

## 文件修改

| 文件 | 修改前 | 修改后 / 原因 |
| --- | --- | --- |
| [formats.py](../../dsh_eval/formats.py) | 只允许读取故障与任务期限 | 校验工具选择、延迟、工具期限、状态断言及快照摘要字段 |
| [environment.py](../../dsh_eval/environment.py) | 同步 read / list | submit / poll 调度、write、超时 / 取消去重、最终状态快照 |
| [runner.py](../../dsh_eval/runner.py) | 收到请求立即执行 | 持续监督任务期限、推进工具、接收取消、清理后保存状态证据 |
| [evaluate.py](../../dsh_eval/evaluate.py) | 根据闭合轨迹断言 | 核对状态快照及实际工具预算执行标记，再比较最终文件 |
| [tool-bridge.js](../../scripts/lib/tool-bridge.js)、[case-control.js](../../scripts/fixtures/case-control.js)、[case-host.js](../../scripts/case-host.js) | 固定 read / list、统一桥接等待 | 传递工具策略、注册写入、转发取消、工具期限之外保留桥接看门狗 |
| [app.js](../../dsh_eval/web/app.js) | 通用断言卡片 | 显示最终文件期望和保存实际值 |
| [write-retry.case.json](../../fixtures/evaluation/write-retry.case.json) | 无写入用例 | 超时 → 重试 → 读回 → 完整状态断言，不加入旧 core 集 |
| [write-adapter.js](../../scripts/fixtures/write-adapter.js)、[test_stateful_writes.py](../../test/test_stateful_writes.py) | 无写入链路夹具 | 真实子进程 / 录制器的无模型执行、身份 / 篡改反例、续跑及报告复验 |
| [tool-bridge.test.js](../../test/tool-bridge.test.js)、[browser.test.js](../../test/browser.test.js)、[test_report.py](../../test/test_report.py) | 读取 / 通用卡片及重录夹具 | 写工具与取消 / 可恢复超时回归、状态卡片、合成重录身份同步 |
| [smoke_bridge.py](../../scripts/smoke_bridge.py)、[smoke-bridge.js](../../scripts/smoke-bridge.js) | 四次读取请求检查 | 保留读取检查，增加 --writes 的六请求真实工具注册 / IPC 检查 |

## 实现与技术取舍

1. stateful.tools 可选启用 eval_read / eval_list / eval_write，省略维持原两工具。write 的 path / content 为完整文本创建或替换，空文本允许；路径逃逸与文件 / 目录冲突失败。只写 Python 内存环境，不改变宿主 read-only 策略。
2. budget.toolTimeoutMs 默认 5000 ms；toolTimeoutsMs 按工具覆盖，允许 1～3600000 的整数毫秒。stateful.toolDelaysMs 是逐工具新请求的延迟数组（0～3600000 ms），耗尽后为零，同 requestId 不推进次数。超时从 Python 调度请求开始，不包含进入 Python 之前的 IPC 延迟。
3. 受控操作在同一监督循环中推进，不引入睡眠线程或不可取消的后台写入。到期优先于提交，任务期限优先于工具推进；超时返回 TOOL_TIMEOUT，允许后续调用恢复。等待不超过 100 ms，并根据最近工具就绪 / 期限和任务剩余时间缩短；事件处理后也推进工具。这不是实时系统保证。原生工具、网络请求或任意长时间同步计算没有获得工具级硬限额。
4. AbortSignal 发送 tool-cancel，Python 校验身份后取消待提交操作。已提交操作不回滚；重复或迟到响应不重新激活工具。任务停止 / 收尾清空剩余操作。发生待执行操作取消时，最终快照保守标为不完整。
5. runtime.json 的 environmentSnapshot 使用独立版本 1，保存 caseRunId / runId / sessionId、初始环境规范 JSON 摘要、工具预算、完整标记和最终 files。evidence 版本 2 保存对象 SHA-256 及 toolTimeouts 执行标记。新断言 environment_files.equals 精确比较全部文件；运行报告 / 证据复用原归档冻结和续跑核验。
6. 离线仍先 fresh inspect；快照缺失、摘要变化、身份 / 输入 / 策略不符或不完整均无法评测。旧证据不生成新状态；工具成功文本不替代最终状态。摘要不是签名，协同改写所有文件不在认证保证内；本功能不是轨迹重放或模型会话恢复。

## 验证

Windows、Node.js v24.14.0、Python 3.12.0；均未调用模型。

| 命令或操作 | 结果 | 证明的范围 |
| --- | --- | --- |
| `python -m unittest discover -s test -p test_stateful_writes.py -v` | 最终 13 项通过，3.831 秒 | 写入 / 创建 / 空文本 / 路径冲突、默认与覆盖期限、超时 / 取消不迟到提交、完整录制与状态断言、快照篡改 / 身份 / 缺失、短期限唤醒、实验续跑和报告 |
| `npm.cmd run test:python` | 完整 462 项通过，289.696 秒 | 修正重录夹具后的全量；最终短期限调整另有下述定向复验 |
| `python -m unittest discover -s test -p test_runner.py -v` | 最终 17 项通过，4.090 秒 | 短期限调整后的任务超时、取消、管道阻塞与真实进程清理 |
| `npm.cmd test` | 最终 119 项通过，7.107 秒 | 新增三项桥接与一项前端回归，既有 Node 回归 |
| `node --test --test-isolation=none test/browser.test.js test/tool-bridge.test.js` | 37 项通过 | 状态卡片、工具注册、可恢复 TOOL_TIMEOUT 与桥接故障区别 |
| `python -m scripts.smoke_bridge --writes` | passed，六请求 | 实际 Cordis / Tools 注册、真实 fork IPC：首次写入超时不改值、重试成功、第三次写入取消后值不变 |
| `python -m scripts.smoke_bridge` | passed，四请求 | 旧读取 / 列举 / 故障恢复真实组件兼容 |
| `npm.cmd run check`；`python -m compileall -q dsh_eval scripts test` | 44 个 JavaScript 文件及 Python 编译通过 | 语法检查 |
| `npm.cmd run demo:eval` 及对两份新证据调用 `evaluate(casePath, evidencePath)` | 两项 synthetic / passed / complete | 原读取和缺文件样例兼容，不依赖新状态字段 |
| 修改文档相对文件链接 / 新章节锚点检查、示例 validate_case | 首轮 9 份文档 / 532 链接；补齐入口说明后最终 10 份 / 543 链接目标存在，新锚点与用例有效 | 公开导航与用例格式 |

首次定向写入测试 11 项通过，随后补续跑 / 报告形成 12 项。复查发现固定 100 ms 等待会误使短延迟操作跨过工具期限；改为最近到期点唤醒，补真实子进程短期限回归，最终 13 项通过。最终监督器 17 项定向回归另于 4.090 秒通过。首轮 Node 118 项中两项已有 Web 启动回收检查因 spawn EPERM 失败；真实桥接 fork 同样受限。在可创建真实子进程的环境复验后通过；最终 Node 增加状态卡片用例为 119 项。

首轮完整 Python 运行 442 项 / 293.682 秒，9 项失败、5 项错误：合成重录辅助函数创建新 runId / sessionId 却仍保留旧快照身份，导致回归比较、重复分布与区间用例被正确判为证据不足；修正夹具同步新合成录制的身份和摘要，不放宽生产核验。另四项真实进程终止检查受环境权限限制，一组生命周期夹具因 fork EPERM 未建立。修正后在可创建 / 终止真实子进程的环境中完整 462 项 Python 回归通过，289.696 秒。该全量进程加载的是短期限唤醒调整前的代码；最终等待间隔调整另有 13 项写入 / 续跑 / 报告和 17 项监督器定向复验通过，未将新增一项计入该全量数量。

## 风险与后续

只覆盖虚拟文件创建 / 覆盖，未实现删除、重命名、局部文本编辑、事务回滚、真实系统副作用或任意外部工具超时。延迟调度只用于受控环境；取消成功处理前已经提交的写入不回滚，不保证任意外部操作的恰好一次执行。未新增模型任务、提交、推送或远端 CI；已有读取模型结果不证明写入任务能力。实际模型验证需使用独立新运行并单列结果。

## 文档同步

同步 README、CHANGELOG、progress、architecture、evaluation-format、stateful-tools、single-case-runner、M6 方案及用例目录说明。进度表的“最新复核”更新到本次本地范围，旧 074–093 的历史验证不覆盖。
