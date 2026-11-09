# 修改记录 128 实验原因汇总复查

日期：2026 年 11 月 9 日，Asia/Shanghai。类型：修复、测试、文档。插件版本：0.1.2。相关 Git 提交：尚未提交；复查基线为已核实的 `4a1c261`。

## 问题与目标

复查 [127 实验原因汇总](2026-11-09-127-experiment-assertion-causes.md)的分类、角色 / 来源分母、普通与续跑报告、Markdown 和浏览跳转，修复两项不完整保存数据的显示问题：

1. 原因列表都是空数组，但摘要计数非零或缺失时，页面仍可能声称“没有问题”。
2. 逐样本 declaredAssertions 为零，却存在原因条目时，页面可能标为“未声明该角色断言”，从而隐藏矛盾数据。

## 文件修改与技术取舍

| 文件 | 修改前 | 修改后 | 原因 |
| --- | --- | --- | --- |
| dsh_eval/web/app.js | 仅以原因列表存在判断是否为零问题 | 两个角色的影响样本及条数计数均明确为零时，才显示零问题；其他情况明确不完整 / 不一致 | 缺失不能补零 |
| dsh_eval/web/app.js | 仅检查逐样本明细字段类型 | 原因条数总和不得超过声明断言数 | 与 Python 分类器的约束一致 |
| test/browser.test.js | 缺少上述矛盾输入 | 新增及扩展非零 / 缺计数、合法零、缺覆盖和矛盾声明回归 | 验证保存结果的保守展示 |

修改只影响可选原因元数据的展示，不重算原任务结论、诊断角色统计或评分。筛选仍通过原样本索引定位已经核对目录范围的评测链接，原数据不变。

后端复查确认：原因派生位于核心复验之后，changedFields 保持旧字段集合；原因码按样本去重，独立源头与后继阻断分开；角色声明分母限定在原因可用子集；来源、版本 2 / 3 续跑分区及 Markdown 链接符合已有契约。未发现其他需要修改的确定问题。

## 验证

环境为 Windows、Node.js v24.14.0、Python 3.12.0。无新增模型调用，127 的历史真实轨迹离线复验及其源摘要保持记录继续保留。

| 命令 | 结果 | 范围 |
| --- | --- | --- |
| python -m unittest discover -s test -p test_assertion_cause_summary.py | 12 项通过 | 分类、去重、声明覆盖与畸形元数据 |
| python -m unittest discover -s test -p test_assertion_cause_reports.py | 5 项通过 / 5.612 秒 | 普通与续跑报告、原评分和摘要、门禁 / 缺证及安全链接 |
| python -m unittest discover -s test -p test_diagnostic_reports.py | 3 项通过 / 1.920 秒 | 原诊断角色统计不变 |
| node --test --test-isolation=none test/browser.test.js | 60 项通过 / 217.647 毫秒 | 两项修正及全部前端回归 |
| npm.cmd test（允许真实子进程的环境） | 152 项通过 / 7.725 秒 | 完整 Node 回归，包含真实 Web 子进程退出 |
| npm.cmd run test:python（允许真实子进程的环境） | 583 项通过 / 421.426 秒 | 当前 127 实现与复查修正的完整 Python 回归 |
| npm.cmd run check；python -m compileall -q dsh_eval scripts test | 45 个 JS 文件及 Python 编译通过 | 语法与编译 |
| npm.cmd run demo:workflow -- --generate-only | 退出 0，三场景与实验原因摘要一致，89 份源文件摘要保持 | 公开合成入口 |

完整 Python 与 Node 回归全部通过。既有历史验证不覆盖；提交和精确 SHA 的新 CI 独立核对。

本次十份变动文档共 594 个相对文件链接目标有效，git diff --check 通过。原始运行与私人资料保持忽略且无跟踪文件。

## 风险与后续

当前复查不增加归档迁移或其他执行能力。可选摘要来自保存文件，不是签名；旧或不完整数据继续保留原判定并明确缺失。此记录仅覆盖 127 交付前复查，后续归档打包按独立范围记录。

## 文档同步

更新 CHANGELOG、进度及[结果浏览](../result-browser.md)的边界说明。原 127 本地结果与当时未提交状态保留，当前交付状态在新记录中同步。
