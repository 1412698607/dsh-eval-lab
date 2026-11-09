# 修改记录 124 结构化原因与依赖展示

日期：2026 年 11 月 9 日，Asia/Shanghai。类型：功能、测试、文档。插件版本：0.1.2。相关 Git 提交：尚未提交；起始 HEAD 为已核实的 `0504755`，工作区含批次 A 的未提交实现。

## 问题与目标

121 的超时漏步反例能判断六项通过、四项缺证，但原始缺证与后续依赖只写在 reason 文本中。使用者需要直接定位第一处缺证、区分后续阻断，并查看实际成功重试和最终读回，同时保持旧评分与续跑约束。

本批完成[接续计划](../plans/reproducible-workflow-and-diagnostics.md)的批次 B。新诊断来自实际评分分支，独立保存，不修改历史归档、原断言结果或任务聚合。

## 文件修改

| 文件 | 修改前 | 修改后 | 原因 |
| --- | --- | --- | --- |
| dsh_eval/evaluate.py | 原因与前置关系主要在自由文本中 | 可选顶层 assertionDiagnostics 版本 1，含分支原因码、直接依赖和未计分的观察位置 | 提供稳定的诊断数据，同时保留原 assertions 完整兼容 |
| dsh_eval/web/app.js | 只显示原 reason 与断言证据 | 原始问题、首个缺证步骤、直接前置 / 阻断、完整通过链与观察事件入口 | 从结果定位步骤与依赖，保留多条独立源头 |
| dsh_eval/workflow_demo.py | 只核对任务与规则预览结论 | 额外核对原因、三条阻断关系和成功观察位置 | 可重复演示同时验证新增诊断 |
| test/test_assertion_diagnostics.py | 无结构化分支回归 | 11 项后端测试 | 原始缺证、失败前置、独立源头、结果 / 顺序与全局门禁 |
| test/test_diagnostics_compatibility.py | 无跨历史字段兼容回归 | 3 项真实录制集成测试 | 旧结果续跑、核心篡改拒绝、报告及两类规则预览 |
| test/test_workflow_demo.py、test/browser.test.js | 无依赖展示集成覆盖 | 新增工作流诊断与前端正反例 | 实际事件定位、旧结果与异常元数据降级 |

## 实现与技术取舍

`check_assertion` 在每个返回分支向可选诊断容器写入稳定 reasonCode。通过项保留 matched，工具缺证、结果不符、顺序不符和前置未通过分别产生不同码；录制、执行和全局证据门禁也有对应原因。旧单项返回对象保持原字段、reason 文本、evidence 选择与顺序语义。新 evaluate 默认在顶层添加独立对象，不为原格式增加必填字段或新开关。[完整字段与原因码](../evaluation-format.md#结构化原因与依赖诊断124)

`after` 保留声明的直接前置；`blockedBy` 只记录直接未通过的前置 ID。前置明确 failed 时，后继仍按原规则 failed；其他未通过前置使后继证据不足。被阻断项可收集 observedMatches：工具 / 参数 / 返回谓词匹配且结果早于最终回复，但不检查前置条件。位置只用于展示，不加入原 evidence，不会使后继通过。漏步反例的 retry 与 verify 因此既能点开实际成功结果，又保留 insufficient_evidence。

采用独立顶层扩展，是因为 resume 对旧 assertions 逐字段核对，实验预览也比较原结果行。兼容验证证明无需放宽这些比较；缺少可选新字段的旧评测可以继续复验与复用，篡改核心断言仍被拒绝。单轨迹与实验预览不把新元数据当成规则变化。

前端核对诊断与保存断言 ID / 类型 / 结论，保留多个独立源头及必需 / 诊断角色。关系引用、循环、部分元数据、未知版本或原因码均明确降级，不解析 reason 文本推断依赖。全局证据核验失败单列为未评分原因，不标记首个步骤缺证。被阻断项的观察事件使用既有运行身份与序号定位，只通过文本节点显示原文。

复核发现并修正两类关系准确性问题：矛盾元数据不能声称已通过的前置造成阻断；全局证据门禁不能误列为独立步骤源头。前置 failed 的合法后继仍须保留 failed 依赖链，与评分器原语义一致。

## 验证

环境为 Windows、Node.js v24.14.0、Python 3.12.0。验证使用合成轨迹及批次 A 的已有合成归档，无新增模型调用；真实子进程与 recorder / inspect 实际运行不等于真实模型验收。

| 命令或操作 | 结果 | 证明的范围 |
| --- | --- | --- |
| python -m unittest discover -s test -p test_assertion_diagnostics.py | 11 项通过 / 2.544 秒 | 实际分支原因、正例、漏步六通过 / 四缺证、失败前置、多个源头、结果 / 顺序差异及门禁 |
| python -m unittest discover -s test -p test_assertion_constraints.py | 8 项通过 | 原内容与顺序判定保持 |
| python -m unittest discover -s test -p test_diagnostics_compatibility.py | 3 项通过 / 4.221 秒 | 历史结果续跑 / 领取、核心篡改拒绝、报告无变化、两类规则预览及源摘要保持 |
| python -m unittest discover -s test -p test_workflow_demo.py | 9 项通过 / 21.040 秒 | 三场景、依赖链与实际 retry / verify 位置，新旧评分分开 |
| node --test --test-isolation=none test/browser.test.js | 52 项通过 | 首缺证、多源头、失败前置、旧结果、异常关系、全局门禁和观察事件跳转 |
| npm.cmd test（允许真实子进程的环境） | 144 项通过 / 7.005 秒 | 最终完整 Node 回归，包含上述前端及真实 Web 子进程退出 |
| npm.cmd run test:python（允许真实子进程的环境） | 563 项通过 / 336.175 秒 | 当前完整 Python 回归，包含原评分、历史续跑、报告、两类规则预览及真实子进程检查 |
| npm.cmd run check；python -m compileall -q dsh_eval scripts test | 45 个 JS 文件及 Python 编译通过 | 语法与编译 |
| 六次独立 python -m dsh_eval --case … --evidence … --output … | 五项 passed、一项 unevaluable；六项核心字段保持 | 对批次 A 的六份无诊断历史结果做新进程复验；仅评测时间及可选诊断新增，99 份源文件摘要不变 |
| python -m dsh_eval.workflow_demo、实际页面浏览 | 生成成功；首个缺证及三条阻断显示，重试定位 seq 5 / 第 6 行，最终读回有 seq 7 入口 | 浏览新元数据与实际事件；仍为 completed / complete / unevaluable |
| 前台服务 Ctrl+C 后检查端口 | 监听数为 0 | 本次演示服务已停止 |

最终完整 Python 与 Node 回归全部通过。九份本轮变动文档共 583 个相对文件链接指向当前可提交文件，git diff --check 通过。测试与演示均使用新输出，旧 121 / 123 结论与原文件保留；runs 和 private-notes 保持忽略且无跟踪文件。

## 风险与后续

浏览仍只显示保存值，不重新评测。旧结果不会自动增加诊断，可显式离线复验并写入新文件。原因和依赖描述当前评分条件，不能据此推断模型意图；观察到成功工具结果也不能替代声明的前置条件。来源与元数据不是签名，SHA-256 不提供防共同篡改或断电保证。

本批尚未提交、推送或核对新云端 CI。批次 A 的无模型 CI 命令继续覆盖工作流生成及新增诊断检查，云端结果须在后续实际运行后另记。

## 文档同步

更新 README、CHANGELOG、进度、架构、评测格式、结果浏览、工作流说明和两批计划；保留 123 的历史验收范围和未提交事实。公开文档不链接原始运行产物或私人资料。
