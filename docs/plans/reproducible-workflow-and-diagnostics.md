# 可重复工作流演示与结构化诊断计划

更新日期为 2026 年 11 月 9 日（Asia/Shanghai）。批次 A、B 已在当前工作区实现，分别见 [123](../changes/2026-11-09-123-reproducible-workflow-demo.md) 与 [124](../changes/2026-11-09-124-structured-assertion-diagnostics.md)。以下保留形成计划时的目标和依赖说明，实际验证范围以两份修改记录为准。

## 接续基线

- 工作目录示例为 `C:/work/dsh-eval-lab`，当前开发分支为 `20261109/feat/experiment-rule-impact`。
- 起始提交为 `0504755a79e31fa72bf5f644e06b5900936ec867`，包含已交付的 [120](../changes/2026-11-09-120-experiment-rule-preview-delivery-ci.md) 和 [121](../changes/2026-11-09-121-rename-skip-readbacks.md)。本计划形成前工作区干净。
- 该提交的 Windows push CI run 42509709548、attempt 1、job 128819889600 和全部 13 个步骤成功。云端核验到步骤状态，本地定向验证为 21 项 Python 测试。[CI 作业](https://github.com/1412698607/dsh-eval-lab/actions/runs/42509709548/job/128819889600)
- 新会话先读仓库 `AGENTS.md`、[当前进度](../progress.md)及本计划，核对分支、HEAD、未提交文件和现有修改记录最大编号。本文与 122 文档记录也应纳入接续时的工作区检查。

## 目标与实施顺序

先交付批次 A，再交付批次 B。每批分别保留实现和验证记录，逐项复核后再安排提交与 CI。

### 批次 A 单命令离线工作流演示

当前入口为 `npm.cmd run demo:workflow`；自动化使用 `-- --generate-only`。具体依赖、输出和停止方式见[使用说明](../workflow-demo.md)。

目标是让使用者从新 checkout 生成可浏览的合成证据，顺着任务、工具轨迹、断言和最终文件找到结论。一次运行生成一个独立输出目录及清楚的结果索引。

入口名为 `demo:workflow`，123 已实现生成归档、运行评测和规则预览，并提供只读浏览地址与停止方式。自动化检查可只生成产物并退出，方便 CI 验证。

| 场景 | 生成内容 | 必须看到的结论 |
| --- | --- | --- |
| 完整步骤 | 超时后先读源、确认目标缺失，再重试并读回 | 执行 completed、录制 complete、任务 passed，工具顺序和完整文件快照可定位 |
| 漏步 | 复用 121 的超时后直接重试行为 | 最终文件与回复正确，首个缺证项为 source-still-present，6 项 passed、4 项 insufficient_evidence，任务 unevaluable |
| 规则影响 | 两用例各两轮，固定其中一项为加粗回复，另三项为精确 done | 原确认词规则四项 passed；候选必需精确 done 使唯一加粗样本翻转，其他三项通过，预览分母为 4 |

生成器应事先固定任务与脚本行为，输出 `source=synthetic` 和 `modelCalled=false`，再使用真实 recorder、独立 inspect 与现有评测器计算结果。每次新建运行身份和输出，原归档可继续单独复验。

#### 已知技术依赖

以下保留形成计划时的依赖快照；123 已处理批次 A 的合成入口、固定回复与预览浏览接入，当前行为见[工作流演示说明](../workflow-demo.md)。

1. [demo-eval.js](../../scripts/demo-eval.js) 当前只生成 read-project 与 missing-file 两组录制，README 需要手工代入目录。保留其已有调用契约，新增工作流入口可以复用 `recordExample` 或更合适的公共执行逻辑。
2. [runner.py](../../dsh_eval/runner.py) 的宿主准备与适配器当前面向真实任务。合成执行主要由测试 mock 并改写 evidence.source 完成。对外入口需要明确的合成执行路径，并在创建证据时声明 synthetic。可把真正共用的监督、记录和评测逻辑抽出复用，演示实现应使用产品模块。
3. [mutation-adapter.js](../../scripts/fixtures/mutation-adapter.js) 已有正常和漏步轨迹，但新确认场景默认回复 `**Done.**`。四样本演示需显式控制各样本回复，才能得到“仅一项翻转”的确定结果。
4. [实验规则预览](../../dsh_eval/experiment_assertion_preview.py) 已可生成版本 1 JSON。该格式目前尚未接入 [browser.py](../../dsh_eval/browser.py) 的类型列表及前端。此批增加一个最小结果视图，展示分母、四类转移、不可评数量、样本变化与关联证据，使第三个场景可在同一浏览流程中打开。

#### 验收

- 新 checkout 只使用公开受版本管理的输入及已声明的 Python / Node 运行依赖，可以完成全部演示。验证实际是否需要宿主安装，将依赖写清。
- 默认流程有固定顺序和结果索引，用户可以在五分钟内查看三个场景。生成模式返回明确退出码，后台浏览服务有可验证的停止方式。
- 逐项独立读取 JSONL 和快照，核对预期调用、返回、顺序及完整文件映射。判分来自现有评测器。
- 对新生成的四样本实验运行 `--compare-experiment-assertions`，核对唯一翻转及四个可评样本。对源归档前后计算摘要。
- 第二次运行创建新目录。覆盖正常生成、输出冲突、无法启动或读取失败等实际新增分支，保持原命令回归有效。
- 浏览器继续遵守根目录与运行身份检查，原文通过文本节点呈现。按需增加端到端、Python 和 Node 定向回归。

### 批次 B 首个缺证步骤与依赖影响

124 选择评测顶层可选 assertionDiagnostics 版本 1，保留原断言字段和聚合，默认随新评测生成；旧结果显式离线复验到新文件。浏览器展示原因、直接依赖和未计分的实际匹配事件；[格式说明](../evaluation-format.md#结构化原因与依赖诊断124)记录兼容方式和原因码。

目标是把 121 中原始缺证与后续依赖关系直接呈现出来，并能点开实际发生的成功重试和最终读回。

在 [check_assertion](../../dsh_eval/evaluate.py) 的实际判定分支产生稳定原因码和前置断言 ID。可采用 `reasonCode`、`blockedBy` 等可选字段，名称在实现前确定并写入[格式说明](../evaluation-format.md)。

| 情况 | 建议结构 | 验收重点 |
| --- | --- | --- |
| 找不到匹配调用和结果 | 原始缺证原因码，保留 reason 和原有 evidence | 121 的 source-still-present 能被定位为源头 |
| 前置断言未通过 | 依赖阻断原因码与前置 ID | target-still-missing、retry、verify 可以沿依赖关系回溯 |
| 结果或顺序明确不符 | 对应现有失败分支的原因码 | 单项 failed 与证据不足各有准确说明 |

原因字段应由评分分支直接产生。前端可以据此构造依赖关系，保留多条独立问题各自的源头。展示成功重试的真实事件时，明确该事件尚未满足用例声明的前置条件。

#### 兼容性与验收

- 先核对 [resume.py](../../dsh_eval/resume.py) 对历史评测的逐字段校验，以及单轨迹与实验规则预览对结果的比较。为新增元数据选择可验证的兼容方式，例如可选诊断输出或独立派生对象，记录适用版本和开启方式。
- 用 121 固定反例验证第一处缺证和三条后继依赖，仍得到 6 passed、4 insufficient_evidence 和 task unevaluable。
- 正例显示完整证据链。前置项明确 failed、多个独立缺证源头和老结果无新字段时也须能展示。
- 继续沿用现有 passed / failed / insufficient_evidence / not_run 及任务聚合规则，对历史产物做新进程离线复验。

## 文件路线与验证命令

| 区域 | 起点 |
| --- | --- |
| 用例与行为 | [超时用例](../../fixtures/evaluation/rename-timeout-retry.case.json)、[合成适配器](../../scripts/fixtures/mutation-adapter.js)、[矩阵测试](../../test/test_rename_confirmation_matrix.py) |
| 运行与评测 | [runner.py](../../dsh_eval/runner.py)、[evaluate.py](../../dsh_eval/evaluate.py)、[recorder.js](../../src/recorder.js)、[inspect.js](../../src/inspect.js) |
| 规则影响 | [实验预览](../../dsh_eval/experiment_assertion_preview.py)、[单轨迹对照](../../dsh_eval/assertion_comparison.py) |
| 浏览 | [读取层](../../dsh_eval/browser.py)、[前端](../../dsh_eval/web/app.js)、[浏览测试](../../test/test_browser.py)、[前端测试](../../test/browser.test.js) |

优先执行受影响模块的定向测试，以及以下现有检查。子进程创建受限时按 AGENTS 约定记录，并在允许真实子进程的环境复验。

```powershell
npm.cmd run check
python -m compileall -q dsh_eval scripts test
python -m unittest discover -s test -p test_rename_confirmation_matrix.py
python -m unittest discover -s test -p test_assertion_constraints.py
python -m unittest discover -s test -p test_experiment_assertion_preview.py
python -m unittest discover -s test -p test_browser.py
node --test --test-isolation=none test/browser.test.js
```

根据实际影响再安排完整回归及新 demo 命令的 CI 集成。每批完成后同步 CHANGELOG、进度和相应说明，按实际命令记录合成、组件及其他验证范围。

## 完成条件

批次 A 完成可独立重建、浏览、停止和离线复验的演示。批次 B 完成准确的原因与依赖展示，并验证历史输出的兼容方式。使用者可以从一个任务的最终结论定位至具体断言、工具事件和文件状态，也可以解释规则改变导致的单项与任务判定变化。
