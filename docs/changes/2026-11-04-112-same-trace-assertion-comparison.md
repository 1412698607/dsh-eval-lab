# 修改记录 112 同轨迹断言对照

日期为 2026 年 11 月 4 日（Asia/Shanghai）。插件版本为 0.1.2，基线为 `b3bc3fa` 加工作区 107–111，本批尚未提交。

## 目标

[110](2026-11-04-110-assertion-roles.md) 和 [111](2026-11-04-111-confirmation-token.md) 在同一份 109 录制上均得到任务 passed，但两个判定的含义不同。新增命令固定证据和任务输入，让使用者直接查看每一条规则、证据与结论如何变化。

## 实现与取舍

- [对照器](../../dsh_eval/assertion_comparison.py)从证据旁读取冻结用例，仅允许候选用例的 assertions 不同。分别调用现有评测器重新检查录制和断言，核对运行身份、执行、录制、配置、预算与指标。在两次评测前后检查输入、runtime 及相关录制文件的字节摘要，避免把观察到的文件变动归为规则效果。
- 按断言 ID 汇合新旧定义、位置和完整结果。分别标记规则变化、判定变化、完整结果变化及位置变化。前置条件改变可能让后继定位到不同证据，即使后继本身的规则与 passed 判定保持，也可在摘要中找到该 ID。新增与移除的 ID 以空侧显示。
- [CLI](../../dsh_eval/__main__.py)提供 `--compare-assertions <evidence.json> --candidate <候选用例>`，默认向 stdout 输出，`--output` 以排他创建方式写入源归档外的新文件。比较完成的退出码为 0，未能得到两侧判定或输入错误为 2。任务通过与否单列在两侧。
- [合成演示](../../scripts/demo-eval.js)为新证据一并保存录制时读取的用例文本，使公开样例可直接作为对照的冻结基准。

## 实际验收

使用 caseRunId `20f69dbb-6f65-4d56-8b87-3c5cce3d06cb` 的既有 live 证据，候选分别使用原输入、110 的诊断角色副本和 111 的确认词副本。候选单项始终指向相同的 answerSeq 48 和实际文本 `Done.`。

| 基准与候选 | 任务变化 | 变化 ID | 单项变化 |
| --- | --- | --- | --- |
| 109 严格规则与自身 | failed → failed | 无 | 两侧回复均失败 |
| 109 与 110 诊断角色 | failed → passed | answer | 回复仍失败，角色变为 diagnostic |
| 109 与 111 确认词匹配 | failed → passed | answer | 必需角色保持，回复变为通过 |
| 新生成的 read-project 合成录制，候选修改回复期望 | passed → failed | answer | 原回复与新期望不符 |

四次对照均退出 0，输出文件与 stdout JSON 相等。前三组逐项与 109、110、111 各自的独立评测结果核对，27 份选定来源文件 SHA-256 保持一致。记录来源中的 live 指归档来源，本轮模型调用为零。

## 验证与边界

- `python -m unittest discover -s test -p test_assertion_comparison.py` 通过 8 项，覆盖角色和匹配、规则增删重排、仅后继证据改变、输入或录制变动、缺少录制以及 CLI 输出保护。
- `python -m unittest discover -s test` 完整运行启动时共发现 509 项，全部通过（337.728 秒）。最终的变更摘要及新增的第八项定向用例在上述 8 项复验中通过（3.241 秒）。`npm.cmd test` 完整 125 项通过，`npm.cmd run check` 检查 45 个 JS 文件，`python -m compileall -q dsh_eval scripts test` 通过。
- 新进程另行复核 109 的角色与匹配对照，结果与逐项检查一致。21 份公开用例通过格式校验，15 份工作区变动文档中的 668 个相对文件链接目标存在。
- 比较依赖可读取的稳定归档，文件摘要无法提供原子快照或证明历史来源真实性。没有相邻冻结用例时拒绝对照。实验级模型回归继续使用 `--compare-baseline`。
- 已同步 [README](../../README.md)、[评测格式](../evaluation-format.md#同轨迹断言对照)、[架构](../architecture.md)、[进度](../progress.md)和[修改索引](../../CHANGELOG.md)。
