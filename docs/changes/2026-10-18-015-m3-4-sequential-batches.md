# 修改记录 015 M3.4 顺序批次、状态重置与结果清单

日期：2026 年 10 月 18 日，Asia/Shanghai。类型：功能 / 测试 / 文档。插件版本：0.1.2。相关 Git 提交：已核实 M3.3 审查修复为 `3ce645d`；本批尚未提交。

## 问题与目标

M3.3 已能运行状态化单用例，但缺少一组任务的有序调度、输入冻结、失败策略和结果关联。本批复用单用例 runner，增加每项独立环境及会话、活动进度快照和终态清单，验证重复用例的故障状态重新初始化。执行、录制和断言仍分别记录，不以批次调度完成代替任务成功。

## 文件修改

| 文件 | 修改前 | 修改后 | 原因 |
| --- | --- | --- | --- |
| dsh_eval/batch.py | 无批次调度 | 预检与全部输入快照、顺序调用、checkpoint、策略及结果关联 | M3.4 核心 |
| dsh_eval/formats.py、__main__.py | 只有单用例入口 | 批次格式版本 1，`--batch --run` 与参数互斥校验 | 显式真实运行入口 |
| dsh_eval/runner.py | 自行分配 caseRunId，无批次身份和人工中断来源 | 接收已分配 UUID / batchId，记录准备进程退出和人工中断事实 | 保留尝试关联、判断能否启动下一项 |
| fixtures/evaluation/recovery.batch.json | 不存在 | 两个候选及一次重复用例的显式清单 | 实际批次及重置验收 |
| fixtures/evaluation/stale-path.case.json | 未明确必须实际尝试旧引用 | 要求尝试引用后再选替代文件 | 对齐必要的失败恢复证据，不放宽断言 |
| scripts/fixtures/batch-adapter.js、test/test_batch.py | 无批次回归 | 真实子进程中的合成适配器、原录制器及 15 项 Python 检查 | 无模型确定性回归 |
| README、CHANGELOG、docs | 下一阶段 M3.4 | 命令、格式、策略、验证及 M4.1 入口 | 文档状态同步 |

## 实现与技术取舍

调度器先读取并校验所有用例格式、headless 和插件版本，再在新 batchId 目录保存 inputs 与改写为本地相对路径的 batch.json。逐项分配 caseRunId，原 runner 创建独立 workspace / home / store / 会话 / Python 环境；后续修改原用例不会改变本批输入。每项配置来自自身快照，实际配置仍由真实请求头采集及离线复核。

batchId 使用既有 evidence / evaluation 的可选字段，不更改录制格式。批次以 entryId + caseRunId 区分重复 caseId，核对 runner 返回值与落盘结果、两份结果中的关联身份，再填入实际配置、runId / sessionId、证据路径和三类状态。未执行项为 skipped，caseRunId、会话、录制和任务结论为 null；已安排但启动失败的尝试可以有 caseRunId，但不能补造 runId。

batch-result.json 采用同目录独立临时 JSON + replace，在本批活动期间更新，正常终态不再修改。没有另建数据库或恢复调度器；批次 UUID 隔离已有结果，原始单项文件仍以新建方式保存。写进度失败停止后续调用，保留最后可用快照和单项证据；没有 fsync / 断电可靠或 resume 承诺。

continue / stop 适用于单项保存后的普通非 passed 结果，包括 failed、取消、超时、运行错误和证据不足。人工 KeyboardInterrupt 即使在单用例内部被处理，也通过 runtime.userInterrupted 停止整批；清理未确认或 runner / 关联异常同样停止。准备进程退出、执行适配器退出、写线程和专用宿主退出事实共同约束继续，不从“返回了 JSON”推断资源已清理。

批次 status 与 outcome 分开：completed 仅指全部项已执行。基础设施错误 / 人工中断 / 单项 unevaluable 优先产生 unevaluable；其次有明确 failed 则为 failed；全部项完成且 passed 才为 passed。停止策略遇到末项时无须再跳过，调度状态可为 completed。没有通过率、指标汇总或统计报告；详细语义见 [批次运行](../batch-runner.md)。

## 验证

Windows / Node v24.14.0 / Python 3.12.0；CLI / session 0.2.0-rc.2、Cordis 4.0.4。真实任务和进程强停检查在获准环境运行。实际模型配置均从各自请求头核对，正常任务为 deepseek-official / deepseek-flash。

| 命令或操作 | 结果 | 证明的范围 |
| --- | --- | --- |
| `npm.cmd run test:python` | 获准环境 73 项通过（原 58 + 新 15） | 批次格式、全量预检、重复状态重置、快照不受源文件修改影响、配置分开、策略和关联检查、清理未知、写 checkpoint 失败 |
| `python -m unittest discover -s test -p test_batch.py` / `test_evaluation.py` | 提示更新后 15 项 / 28 项通过 | 批次与既有离线断言兼容 |
| `npm.cmd run check` / `npm.cmd test` | 29 个 JS 文件 / 42 项通过 | 新合成适配器语法与原 Node 回归 |
| `python -m compileall -q dsh_eval test` | 通过 | Python 语法 |
| `python -m scripts.smoke_bridge` | 实际注册 / IPC 四次请求通过，未调用模型 | 新 runner 元数据与既有桥接兼容 |
| `python -m dsh_eval --batch fixtures/evaluation/recovery.batch.json --run` | 新提示批次 completed / passed，CLI 退出 0，三项 passed | 两个真实恢复任务及重复故障重置；独立身份、配置、目录与录制对应 |
| 实际 batch API，未注册 provider 后接正常用例，continue | completed / unevaluable；第一项 runtime_error，第二项 passed | 运行错误保留后继续，未误归普通任务失败 |
| 相同输入策略为 stop | stopped / unevaluable；第二项 skipped | 未运行项没有会话 / 录制身份 |
| 两个正常用例，首流取消控制 + stop | stopped / unevaluable；第一项 cancelled、第二项 skipped | 真实取消、日志封存和批次停止 |
| 五个实际批次的十个启动项，保存快照离线复验 | 保持原三维分类与 batchId，录制均 complete | fresh inspect 与逐项关联，不复用旧检查结果 |
| 查询十个专用宿主 PID | 均不存在；childClosed=true、forceStopped=false，写线程已退出 | 当前受控任务资源回收 |

新 15 项回归使用真实 Node 子进程、运行中的 Python 状态环境和原录制器 / fresh inspect；准备被替换为测试路径，适配器是合成程序，不能算实际 Harness / 模型验证。人工中断覆盖了注入 KeyboardInterrupt 以及 runner 已处理的中断来源，未执行手工按键验收。普通断言失败、取消与超时的 continue / stop 均有确定性测试；真实额外验收限定上表列出的路由错误与取消停止。

首次实际批次使用旧任务文字，模型先列根目录，正确读到新文件并回答，但未尝试旧引用。因此第一项为证据不足、整批 unevaluable，后两项仍 passed。没有删除旧路径失败断言或把该运行改判通过。任务文字明确“实际尝试引用文件，再选择替代文件”后，新快照批次三项通过；它只是明确本用例必需的故障恢复行为，发现目录仍支持根目录或 docs。

本机批次编号只用于核对，不作为公开依赖：

- 旧提示批次 `e34cfda8-9629-4509-a8f0-d327d39a07db`：第一项 unevaluable，其余两项 passed，完整保留。
- 新提示批次 `6c1d1599-ee90-4059-b54b-57defe6ada33`：三个 caseRunId 为 `1afd8781-0be2-402d-8a88-c4f99d07c5b8`、`5021b3dd-6788-4c87-ac84-35f46d076d5d`、`d6123aac-44ec-4cb0-b7c2-ee293c6f54cd`；分别 41 / 37 / 37 条、55889 / 50166 / 50783 字节。两次 project.md 读取各自为失败后成功，未把发现列表结果计为读取次数。
- 路由 continue / stop 分别 `2be9f21c-f2b6-4166-97bd-b16105b81a00` / `0b1235a6-8cce-42ee-83a2-7a1b7394ae53`；取消 stop 为 `8030d80f-7865-451b-af6a-3954a1f576f9`。

原始材料在被忽略的 runs/batches 与本轮本机验证目录中，不链接它们作为公共仓库依赖。本批没有重复 smoke:host / check:output 或旧模拟 demo 验收，不把历史结果写为本批执行。

## 风险与后续

实现限定顺序单会话任务，未增加并发、恢复会话 / fork、崩溃续跑、完整会话重放或配置统计。batch-result.json 可保留 running 状态，不能据此认定成功；写入与进程回收仍依赖本机文件系统和权限，不推定所有平台或外部工具树。未知实际配置 / 身份保持 null，不能用于填零统计。

状态重置和少量真实验收不构成模型成功率估计，也没有性能、成本改善数据。下一批 M4.1 先定义重复试验及指标 / 分母口径，再做 M4.2 配置比较与报告；剩 M4、M5 两个主要阶段，拆为三批。

## 文档同步

已更新 README、CHANGELOG、progress、architecture、M3 路线、评测格式、单用例 / 状态化工具说明、公开用例说明，并新增批次运行文档；历史 014 及更早验证保留，当前 Git 提交状态以本批核对为准。最终 29 份公开 Markdown 的 135 个本地链接有效且无忽略目标，五个公开用例及批次清单格式有效；git diff --check 通过，runs / private-notes 无跟踪文件且忽略有效，CLI help 与实际入口一致。
