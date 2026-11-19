# 修改记录 119 整份实验的规则影响预览

日期为 2026 年 11 月 9 日（Asia/Shanghai）。插件版本 0.1.2，基线为 `030ef26`。本批尚未提交。

## 问题与实现

修改评分规则后，需要知道受影响的是哪些用例、配置和重复轮次。选择一条轨迹复验会漏掉同一实验的其他样本，也可能漏算证据缺失的任务。

- [预览器](../../dsh_eval/experiment_assertion_preview.py)检查普通实验已完成，复核计划指纹、冻结矩阵和样本绑定。规则映射须恰好覆盖全部 caseEntryId。按样本的冻结配置生成候选用例，仅更换断言。复用实验报告和单轨迹断言对照的独立评测与文件摘要检查。
- 每行保留样本与任务身份、配置、轮次、两侧判定及变化断言的完整明细。汇总将全部计划项分成通过变失败、失败变通过、保持通过、保持失败及不可评五类。候选断言定义改变时，即使单项结果仍相同，也能从行明细看到改动。
- [CLI](../../dsh_eval/__main__.py)提供 `--compare-experiment-assertions <实验结果> --candidate <规则映射>`，可选 `--output` 在源实验外创建新文件。只读普通完成实验。比较完成时退出 0，有不可评项或输入错误时退出 2。

## 117 归档验收

实验为 `3d651107-a9fb-433b-b29a-6148e446e75f`，planFingerprint 为 `6ff81500dc4bcde6ae2e40dcfa43599145156d52281f79dd1aedbe787d354c05`。两个入口的候选都只删除必需 `answer` 的 `match`，保留 `equals: "done"`、诊断项及其他断言。规则映射的对象 SHA-256 为 `f38a0cd56b17167ce4be52d61d1c950b08e84e8908e1688c6c4ec55e3d5ff1cb`。

| 用例入口 / 轮次 | 轨迹中 actual | answerSeq | 原任务 → 候选任务 |
| --- | --- | --- | --- |
| confirmation / 1 | `done` | 40 | passed → passed |
| timeout-retry / 1 | `**done**` | 46 | passed → failed |
| confirmation / 2 | `done` | 34 | passed → passed |
| timeout-retry / 2 | `done` | 46 | passed → passed |

计划四项、可比较四项、不可评零项。唯一翻转样本的 caseRunId 为 `723d8331-f0ef-491c-b9ef-5cd05d878706`。逐样本另起 CLI 执行 `--compare-assertions`，四份单轨迹结果均与实验预览的变化明细一致。核对 117 的 80 份选定来源文件 SHA-256，原归档内容保持。本轮模型调用为零，117 的原任务结果继续为四项 passed。

## 验证与边界

`python -m unittest discover -s test -p test_experiment_assertion_preview.py` 覆盖多用例、多配置与多轮、全部转移类型、增删重排、缺失及身份不符、输入漂移、映射覆盖、源归档保护与 CLI 退出码。使用稳定归档；文件摘要的前后检查不等于原子快照。正常实验内不同规则的离线对照与新模型运行分别计数。完整输入示例见[评测格式](../evaluation-format.md#整份实验的规则影响预览)。已同步 [README](../../README.md)、[架构](../architecture.md)、[进度](../progress.md)及[修改索引](../../CHANGELOG.md)。

独立复查发现单个证据文件被目录替换时，最初的摘要检查会导致整份预览提前退出。修复后该样本保留为不可评，其他健康样本照常计入；越界引用和检测到的源文件漂移继续拒绝。最终 10 项预览回归及 8 项单轨迹对照回归通过，另有 20 项实验基线对比、8 项计划预检通过。独立从 CLI 再次复核 117，最终报告与首次预览逐字段相等。Python 编译及 `git diff --check` 通过。

11 月 9 日提交前执行 `python -m unittest discover -s test`，529 项全部通过（324.632 秒）。`npm.cmd run check` 检查 45 个 JavaScript 文件通过；23 份公开用例通过格式校验，7 份变动文档中的 523 个相对文件链接目标均存在。
