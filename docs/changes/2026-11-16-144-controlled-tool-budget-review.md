# 修改记录 144 受控工具预算复查与退出边界修正

日期：2026年11月16日，Asia/Shanghai。类型：修复、测试、文档。插件版本：0.1.2。相关Git提交：本记录形成时尚未提交；起点为已核实的 `ff7428512cfc208ded461136023cafe2611cc651`。

## 问题与复查范围

复查[143预算实现](2026-11-16-143-controlled-tool-call-budget.md)全部源码、测试、真实IPC夹具、前端标签及公开文档，核对接纳计数、请求去重、停止顺序、无副作用和证据一致性。确认两项运行 / 证据问题及两处格式表遗漏，修正后再独立验证当前版本。

适配进程已经退出，但stdout队列中仍可能有尚未处理的工具请求。原supervise继续submit / poll，会在观察到进程已退出后执行虚拟文件操作。真实Python子进程输出selection和delete请求后退出0，先wait确认退出再进入监督器，旧代码仍得到admitted=1、文件被删除且protocolError为空。另两项反例证明，已经就绪但未提交的pending操作，以及已报告closed但父进程尚未退出时的迟到请求，也缺少相应守卫。

该退出问题属于监督器既有边界被预算链路继承，不归因于模型行为。

第二项是completed预算门禁只检查干预原因和计数收据，未核对其他完成事实。对正常maxToolCalls=3合成产物，仅在runtime.supervisor中加入protocolError，快照及其摘要不变，现有运行分类器会判runtime_error，但旧离线评测仍passed。现在仅在配置次数预算且声明completed的路径补查已有分类事实：监督协议错误 / 退出码，host错误 / 关闭 / 强停 / 退出码 / 信号及有效completed协议。未配置预算的历史路径保持。

## 文件修改与技术取舍

| 文件 | 修改 | 原因 |
| --- | --- | --- |
| dsh_eval/runner.py | 记录adapter_closed，在新接纳和poll前检查已观察到的退出 / 关闭，取消pending并保存协议错误 | 退出后不启动受控工作，不能凭伪completed报告判成功 |
| dsh_eval/evaluate.py | 完成预算门禁补齐监督与host的已有成功事实 | 单字段运行错误不能与completed声明并存而被判通过 |
| test/test_tool_budget_runner.py | 新增三项真实进程退出反例，并将坏收据 / 运行冲突扩展至22个子场景 | 原退出反例全部失败，协议错误单字段反例原先误通过；不以mock退出代替真实进程 |
| docs/evaluation-format.md | 补maxToolCalls字段表、budget_exceeded枚举及预算证据链接；区分早期静态合成样例与runner合成执行的期限标记 | 正式格式说明与实现一致 |
| docs/tool-call-budget.md | 补充退出守卫及批次、报告、续跑范围 | 未提交操作取消不等于回滚；预算中断项不能当未开始项恢复余额 |
| 本记录、架构、能力、进度、CHANGELOG | 登记当前修正和验证范围 | 保留143原候选及首次限制记录 |

守卫针对已经观察到的process退出或closed，不承诺与外部进程死亡时刻的跨进程原子事务。此前已提交的修改继续保留；未提交的pending通过已有cancel_all失效，后续poll不会执行。已有tool_budget / timeout / cancel等停止事实继续保留，关闭边界不覆盖其分类。

格式补充不改变判分或计数合同。maxToolCalls仍随完整冻结输入进入既有指纹，每个新执行独立计数；批次沿原failurePolicy处理unevaluable，清理不明仍阻止后续运行；来源续跑要求已执行项正常completed且passed / failed，因此预算中断项阻断来源续跑，不自动重试或恢复余额。

## 验证

Windows、Python3.12.0、Node.js v24.14.0；无模型调用。真实fork IPC仍使用轻量测试CLI与共享生产适配 / 桥接，没有加载Harness Agent runtime。下列定向与最终完整回归分别记录。

| 检查 | 实际结果 | 范围 |
| --- | --- | --- |
| 环境与格式独立复验 | 环境15项 / 0.009秒，格式6项 / 0.007秒通过 | 接纳、去重、取消、无副作用、严格schema及旧字段兼容 |
| 预算证据两项定向（允许真实子进程） | 2项 / 2.141秒通过 | 12个坏收据 / 停止冲突子场景，以及4条录制调用 / 3次接纳正例 |
| 新增三个真实进程反例在修复前执行 | 三项均失败 | 退出后新操作、退出后ready pending及closed后迟到请求均会误执行 |
| python -m unittest discover -s test -p 'test_tool_budget*.py' -v | 最终33项 / 18.675秒全部通过，无跳过 | 新三进程反例、22个坏收据 / 运行冲突子场景、预算计数及真实管道 / fork IPC；此前仅退出修正阶段33项 / 18.298秒另保留 |
| 同一持久化正常合成产物，只改supervisor.protocolError后独立复验 | 修复前classify=runtime_error但fresh=passed；修复后原产物passed、冲突副本unevaluable / insufficient_evidence | 只改变一个运行事实，未重写快照摘要；失败原材料与修正后回执分别保存 |
| 既有runner / environment / stateful写入与修改回归 | 59项 / 13.632秒全部通过，无跳过 | 旧期限、取消、进程清理及状态行为 |
| node --test --test-isolation=none test/tool-budget-ipc.test.js test/tool-bridge.test.js | 12项 / 0.544秒通过，无跳过 | 真实fork拒绝、abort / close及原桥接行为 |
| npm.cmd test；npm.cmd run check | 完整167项Node / 8.464秒、0失败 / 取消 / 跳过；47个JS文件语法通过 | 最终冻结版本Node回归 |
| npm.cmd run test:python（最终冻结源码、允许真实链接 / 子进程环境） | 完整706项 / 564.174秒，OK，无跳过 | 包含退出守卫三项和完成事实22个冲突子场景，旧路径全部回归 |
| python -m compileall -q dsh_eval scripts test | 退出0 | 最终Python编译检查 |
| 文档相对链接 / 锚点、补丁与边界检查 | 11份文档677个相对链接 / 锚点及git diff --check通过；175份运行代码 / 测试 / 配置自最终回归启动后保持 | 原始运行和本地辅助目录保持忽略且无跟踪文件 |

补齐第二项修正前，一轮完整Python检查在未结束时停止，不计为通过；确认自有测试进程已退出后，以最终冻结源码重新执行并通过上述706项及编译。Node源码未因第二项修正而变化，上述167项仍对应最终Node字节。143的703项Python、167项Node及原IPC产物保留修正前范围，不用旧快照替代新代码验证。完整回归后仅补记文档，提交后的CI与上传结果按完整SHA独立核对。

## 限制与后续

本轮不新增模型调用、实际摘要网页核验或跨平台声明。原始日志、IPC产物与本地辅助资料保持忽略，不进入提交；公开文档只链接可提交文件。摘要发布步骤、下载Markdown内容与网页渲染分别判断，网页继续未验证。

## 文档同步

正式字段表、执行状态、预算说明与当前进度同步；历史失败、沙箱限制、143旧验证和真实模型记录不覆盖。源码与相关公开文档在同一批交付，CI不继承旧提交结果。
