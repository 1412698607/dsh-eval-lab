# 修改记录 125 工作流与结构化诊断复查

日期：2026 年 11 月 9 日，Asia/Shanghai。类型：修复、测试、文档。插件版本：0.1.2。相关 Git 提交：尚未提交；复查起点为已核实的 `0504755`，覆盖 122–124 的当前工作区改动。

## 问题与目标

复查批次 A 的合成执行、冻结输入、独立报告与浏览，以及批次 B 的评分原因、依赖展示和历史结果兼容。发现并修复两个问题，原评分器聚合与既有真实执行路径保持。

1. 合成适配器忽略用例的 recorder 覆盖配置。实际声明 maxEventBytes=64、maxPendingBytes=123456 时，录制仍使用默认 1048576 / 16777216，任务可能错误地录制完整并通过。
2. 前端保留结构化诊断元数据的输入顺序，却将其描述为保存断言顺序。元数据数组被反向排列时，“首个缺证步骤”会指向后面的独立源头。

## 文件修改

| 文件 | 修改前 | 修改后 | 原因 |
| --- | --- | --- | --- |
| scripts/fixtures/mutation-adapter.js | createRecorder 仅指定输出目录 | 同时传递 task.recorder，最后固定 outputDir | 使用冻结用例声明的录制限制，与真实入口一致 |
| test/test_synthetic_runner.py | 未覆盖录制限制透传 | 新增定制限额与 64 字节事件上限两项真实子进程回归 | 核对 run.json 实际配置，防止超限静默通过 |
| dsh_eval/web/app.js | 过滤后按诊断数组顺序展示 | 按原保存断言的唯一 ID 位置排列诊断 | 首个缺证与多个源头保持原断言顺序 |
| test/browser.test.js | 未覆盖完整但重排的诊断 | 新增反向诊断元数据回归 | 同时核对首项、源头列表、表格顺序和原数据不变 |

## 实现与技术取舍

录制配置沿用现有 createRecorder 的校验与运行事实，不复制另一套限制实现。输出目录放在配置展开之后，仍固定于本次任务 traces。普通限额可完成并通过；超小事件上限由实际 recorder 拒绝 / 标记，离线检查与评测保留无法完整验证的结论。

前端只调整已经通过身份和结果关联检查的诊断行顺序，不修改保存数据，不改变原因码、依赖关系或聚合。多个独立源头、失败前置、全局门禁和未知元数据的降级行为继续沿用 124。

其余复查覆盖普通真实 runner 调用契约、合成来源创建、禁止合成续跑、管道 / 清理、快照、目录范围、事件身份、文本节点、规则预览分母、历史续跑核心字段核对及报告比较，未发现需要修改的确定问题。公开文档按当前行为同步，123、124 的历史结果不改写。

## 验证

环境为 Windows、Node.js v24.14.0、Python 3.12.0。所有新增演示、轨迹与差分输入均为合成数据，没有新增模型调用。

| 命令或操作 | 结果 | 证明的范围 |
| --- | --- | --- |
| python -m unittest discover -s test -p test_synthetic_runner.py | 8 项通过 / 7.559 秒 | 实际录制限额、超限门禁及原合成执行错误分支 |
| python -m unittest discover -s test -p test_workflow_demo.py | 9 项通过 / 23.861 秒 | 固定三场景、独立复验、唯一翻转、依赖链、新身份与输出保护 |
| python -m unittest discover -s test -p test_assertion_diagnostics.py | 11 项通过 | 原因分支与观察位置不改变原评分 |
| python -m unittest discover -s test -p test_diagnostics_compatibility.py | 3 项通过 | 旧结果续跑、核心篡改拒绝、报告与两类规则预览兼容 |
| python -m unittest discover -s test -p test_assertion_constraints.py | 8 项通过 | 原工具内容和顺序约束 |
| node --test --test-isolation=none test/browser.test.js | 53 项通过 | 新排序反例和原浏览 / 诊断边界 |
| npm.cmd test（允许真实子进程的环境） | 145 项通过 / 7.687 秒 | 完整 Node 回归，含真实 Web 子进程退出 |
| npm.cmd run test:python（允许真实子进程的环境） | 565 项通过 / 330.531 秒 | 当前完整 Python 回归，包含两项新增限额反例及批次 A、B 全部既有覆盖 |
| npm.cmd run check；python -m compileall -q dsh_eval scripts test | 45 个 JS 文件及 Python 编译通过 | 语法与编译 |
| npm.cmd run demo:eval；npm.cmd run demo:workflow -- --generate-only | 原两份示例、新三场景均生成成功 | 公开入口保持，固定结果与源归档摘要检查通过 |

评分还做了一次探索性差分审计：PowerShell here-string 输入 python -，以 random.Random(125) 生成 1,000 条经 task_view 校验的轨迹，覆盖交错工具调用 / 结果、缺失返回、错误与文本、after 链、禁止 / 计数和最终文本 / 结束断言。通过 git show 0504755:dsh_eval/evaluate.py 加载基线评分函数，复用相同当前依赖，对比完整原断言结果字典，全部一致。该内联脚本未纳入公共回归，不是全输入等价证明；可持续复验以上表公开测试入口为准。

完整 Python 与 Node 回归全部通过。当前十二份变动文档共 593 个相对文件链接指向可提交目标，git diff --check 通过。已核对忽略规则与实际跟踪文件；runs、private-notes 和原始运行内容不纳入提交。

## 风险与后续

验证范围为合成流程与实际组件 / 子进程，不推广为模型表现或性能结论。修复不改变持久化格式。远端提交及对应精确 SHA 的 CI 应独立核对，历史基线 CI 不代表当前工作区；交付结果另行记录。

## 文档同步

更新 CHANGELOG、进度、架构、工作流说明与结果浏览说明；保留 122 计划及 123、124 的历史验证与当时未提交状态。
