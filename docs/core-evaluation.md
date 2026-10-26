# M6.3 固定评测集与真实验收

更新：2026 年 10 月 24 日，Asia/Shanghai。插件版本 `0.1.2`，沿用用例 2、实验 1、证据 / 评测 2；没有新增格式编号或调度器。审查修复 028 增加可选工具结果约束，旧输入仍可读取，新字段需要升级后的读取器。

## 本批范围

本文件保留 027 / 028 的十用例历史。2026 年 10 月 25 日 [044 小批真实验收](guarded-acceptance.md) 另复用 direct-read / retry-once 各两次，验证 041–043 的上限、指纹、快照与报告链路；先保留深目录准备失败，再以短目录完成四个真实任务。该新增单配置批次不改写原十用例结果，也未执行双配置比较。

本批使用 `deepseek-official / deepseek-flash` 执行 10 个固定用例，每个一次。本批验证单配置的任务覆盖，不包含第二套配置或重复统计，不推断模型整体能力、成本降低或配置优劣。用例清单与必要证据见 [用例目录](../fixtures/evaluation/core/README.md)，可运行清单为 [core.experiment.json](../fixtures/evaluation/core/core.experiment.json)。

10 项覆盖普通读取、嵌套发现、引用链、当前 / 归档值、缺失与空文件、中文、单路径与双路径暂时失败，以及旧路径后再重试。它们基于版本 2 的虚拟文件与真实工具桥接；文件不会物化到工作目录供原生 read 绕过，暂时故障计数逐用例重置。

## 运行与复验

在项目根目录运行。第一项只验证人工参考轨迹；第二项会调用模型，执行前应确认配置与任务规模：

```powershell
python -m unittest discover -s test -p test_core_suite.py -v
python -m dsh_eval --experiment fixtures/evaluation/core/core.experiment.json --run
```

清单使用 `failurePolicy=continue`。明确完成清理的任务失败 / 无法评测可继续；人工取消及不能确认进程退出时仍按原 runner 停止。模型执行前冻结全部输入，按用例 / 配置顺序调度，每项新 caseRunId、home、workspace、会话和故障状态。单项 timeoutSeconds=120 不包含全部准备与清理窗口，也不是费用硬上限。

从命令返回的 experimentDirectory 取得实际实验目录。对原冻结输入生成新报告，不调用模型或覆盖旧结果：

```powershell
python -m dsh_eval --report 'runs/experiments/<experimentId>/experiment-result.json'
```

报告重新 inspect，核对完整冻结输入、身份、来源和全部请求路由，列出 planned / attempted / finished / skipped / errors、三维分类和指标覆盖；缺失保留 null。仅一个配置时 comparisons 为空。观测 modelCalls 来自已结算事件，不等于供应商账单请求数；elapsedSeconds 包含准备 / 执行 / 清理，费用缺失不补零。原始证据保存在被忽略的 runs，公开文档不依赖私人日志才能理解协议或重跑。

## 027 首次真实验收与原冻结输入

2026 年 10 月 24 日在 Windows、Node.js v24.14.0 / Python 3.12.0、CLI / SessionStore 0.2.0-rc.2、Cordis 4.0.4 执行。实验 ID 为 `6530df76-86e2-4ea1-80a9-86ca71e74e4e`，独立复验报告 ID 为 `2a3253d3-69b8-49e9-9c09-51cd01baae7b`。两者文件分别位于上述默认 experiments / reports 目录，不把原始日志加入公开仓库。

本节保留记录 027 的历史命令、计数和原冻结断言结果。后续修复只对已有录制做离线检查，没有新增模型任务，也不改写本节的历史验证。

| 用例 | 执行 / 录制 / 断言 | 已结算模型调用 | 工具调用 | 已报告 totalTokens |
| --- | --- | ---: | ---: | ---: |
| direct-read | completed / complete / passed | 2 | 1 | 14963 |
| nested-discovery | completed / complete / passed | 3 | 2 | 22619 |
| reference-chain | completed / complete / passed | 5 | 4 | 37925 |
| current-over-archive | completed / complete / passed | 4 | 3 | 30354 |
| missing-file | completed / complete / passed | 2 | 1 | 14923 |
| empty-file | completed / complete / passed | 2 | 1 | 14979 |
| unicode-path | completed / complete / passed | 2 | 1 | 15042 |
| retry-once | completed / complete / passed | 3 | 2 | 22563 |
| independent-retries | completed / complete / passed | 3 | 4 | 22794 |
| stale-then-retry | completed / complete / passed | 6 | 5 | 45923 |
| 合计 | 10 项均通过 | 32 | 24 | 242085 |

planned=10、attempted=10、finished=10、skipped=0、errors=0，passed / failed / unevaluable 为 10 / 0 / 0；三个比例的分子 / 分母均为 10 / 10。离线复验 verification=verified 10 项、configurationMatch=matched 10 项、source=live 10 项、changedFields 全空，comparisons 为空。每个实际请求头路由均匹配，caseRunId / runId / sessionId 各 10 个唯一身份。10 个 run 清单均 sealed，实际配置均为默认 maxEventBytes=1048576 / maxPendingBytes=16777216。

7 个数值指标中，modelCalls、toolCalls、inputTokens、outputTokens、totalTokens、elapsedSeconds 均有 10 / 10 样本覆盖；cost 为 0 / 10、全部 null。已报告 inputTokens 合计 73723、outputTokens 1322，原始 usage 的 cacheReadTokens 合计 167040、cacheWriteTokens 为 0；本次 totalTokens 合计 242085 与这些原始字段相符。保留各独立 usage 字段，不把 inputTokens + outputTokens 作为 totalTokens，也没有校准供应商账单。单项 elapsedSeconds 约 4.265～7.719 秒，合计 56.795 秒，包含准备 / 执行 / 清理，排除离线复验，不代表纯模型延迟或整个命令的墙钟耗时。

重新检查前后，原实验清单、输入、结果、runtime / host / setup 及录制 JSON / JSONL 共 125 份文件 SHA-256 保持不变。10 项 host 均 childClosed=true、exitCode=0、forceStopped=false；准备进程已退出、stdinWriterStopped=true，保存的 10 个专用 CLI PID 再查均不存在。该进程核对限定这些专用进程，不扩张为任意外部进程树保证。

| 检查 | 结果 | 范围 |
| --- | --- | --- |
| `python -m unittest discover -s test -p test_core_suite.py -v` | 6 项通过 | 30 份合成录制 / fresh inspect、22 项必要工具证据删除检查、4 组替代列表 / 状态重置 |
| `npm.cmd run test:python` | 150 项通过，44.706 秒 | 含新增 6 项及原有真实子进程 / 清理回归，在获准环境运行；不调用模型 |
| `npm.cmd test` / `npm.cmd run check` | 79 Node / 36 文件语法通过 | 既有 Node 回归，本批未改生产执行代码 |
| `python -m compileall -q dsh_eval test` | 通过 | Python 语法 |
| 上述实验 `--run` 与原结果 `--report` | 10 项首次运行及独立复验均通过 | 单配置各一次，未追加重跑模型任务 |

本轮未运行云端 CI，未重跑早期模型任务、smoke:host、check:output 或资源测量；历史结果单独保留。修改范围及取舍见 [记录 027](changes/2026-10-24-027-m6-3-core-evaluation.md)。

## 028 审查修复与无模型复验

审查发现两种误通过：发现 / 引用 / 恢复的步骤反序时，原断言只确认必要调用存在；空文件的工具返回非空、最终答案仍为 EMPTY_FILE 时，原断言只确认读取成功。README 当前里程碑状态也未同步。本次修复六个顺序用例及一个空文件用例的断言，任务文本、环境、配置和预算保持。

tool_result.after 引用前面的工具结果断言，要求先行结果返回后才发出后继调用；匹配多组调用时选最早完成的合格结果。nested-discovery 检查 list → read，reference-chain 和 current-over-archive 检查引用后读取；stale-then-retry 检查 README → 旧路径缺失 → 列表 → 当前路径暂时失败 → 重试。retry-once 及 independent-retries 也要求先收到各路径的失败结果再重试，独立路径可交错。empty-file 用 result.textEquals="" 精确检查全部文本块的拼接结果，空白不算空。协议及失败分类见 [评测格式](evaluation-format.md)。

新增 5 项固定集回归先在旧实现出现 9 个反例 subTest 失败，修复后固定集 11 项全过；另有 8 项格式 / 断言边界测试，覆盖无效引用、文本类型、空白与多块文本、并发结果乱序、先行缺失或失败及合法替代匹配。原 30 份合成轨迹保留，新加 12 份录制轨迹检查 9 个反例及 3 个合法路径。

| 检查 | 结果 | 范围 |
| --- | --- | --- |
| `python -m unittest discover -s test -p test_core_suite.py -v` | 11 项通过 | 42 份合成录制 / fresh inspect，原 22 项必要证据删除和 4 组列表 / 状态重置继续通过 |
| `python -m unittest discover -s test -p test_assertion_constraints.py -v` | 8 项通过 | 两个用例版本的可选字段、依赖和精确文本边界 |
| `python -m unittest discover -s test -p test_evaluation.py` | 36 项通过 | 原离线评测兼容回归 |
| `npm.cmd run test:python` | 163 项通过，45.800 秒 | 获准环境，包含真实子进程清理；无模型调用 |
| `npm.cmd test` / `npm.cmd run check` / `python -m compileall -q dsh_eval test` | 79 Node / 36 文件语法及 Python 编译检查通过 | 不启动模型任务 |
| 当前 10 个用例对已有录制调用 evaluate | 10 项 passed | 七个用例仅断言变化，来源是已有真实录制，不是新的模型执行 |
| 原冻结实验重新 generate_report | 10 项 verified / matched / passed，changedFields 全空 | 新报告 ID `c1a95bab-f3c9-4f1c-9dcd-2a33bd98ef36`，另存本机验证目录；原 125 份证据摘要不变 |

标准 `--report` 始终使用原冻结断言。需要对保存的录制检查当前更严格的断言时，可在项目根目录使用另一入口，路径从该实验样本的 caseDirectory 取得：

```powershell
python -m dsh_eval --case 'fixtures/evaluation/core/<name>.case.json' --evidence 'runs/experiments/<experimentId>/batches/<batchId>/cases/<caseRunId>/evidence.json'
```

此命令只输出新的离线结论。当前七个用例的完整输入已不同于旧快照，后续新实验会冻结新版；旧报告不会自动替换断言。本次没有新模型任务、云端 CI、真实宿主重跑或新增成本 / 稳定性结论。实现与取舍见 [记录 028](changes/2026-10-24-028-m6-3-assertion-constraints.md)。

## 边界与下一批

首次真实验收每项只执行一次，来源均单一配置，不能作重复稳定性或显著性结论。当前断言检查必要工具结果、声明的 after 关系及精确答案；没有指定次数或禁止全部额外行为的断言，允许额外调用之后出现合法匹配链。目录发现接受合理列表范围，独立路径之间没有额外顺序要求。

双配置真实比较仍待选择第二套配置与预算。M6.4 已完成 Windows / 当前 CLI 的页面实际取消、普通退出及处理中断验收，034 补齐取消工作区匹配；这些生命周期样本不增加本固定集的重复次数，也不改变单配置首次验收的统计范围。当前方案见 [M6 计划](plans/m6-reliability-validation.md)，状态修正见 [记录 035](changes/2026-10-24-035-m6-4-status-review.md)。
