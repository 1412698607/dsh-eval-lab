# M6.3 固定评测集与真实验收

更新：2026 年 10 月 24 日，Asia/Shanghai。插件版本 `0.1.2`，沿用用例 2、实验 1、证据 / 评测 2；没有新增格式或调度器。

## 本批范围

用户选择先用现有 `deepseek-official / deepseek-flash` 执行 10 个固定用例，每个一次。本批验证单配置的任务覆盖，不包含第二套配置或重复统计，不推断模型整体能力、成本降低或配置优劣。用例清单与必要证据见 [用例目录](../fixtures/evaluation/core/README.md)，可运行清单为 [core.experiment.json](../fixtures/evaluation/core/core.experiment.json)。

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

## 验证结果

2026 年 10 月 24 日在 Windows、Node.js v24.14.0 / Python 3.12.0、CLI / SessionStore 0.2.0-rc.2、Cordis 4.0.4 执行。实验 ID 为 `6530df76-86e2-4ea1-80a9-86ca71e74e4e`，独立复验报告 ID 为 `2a3253d3-69b8-49e9-9c09-51cd01baae7b`。两者文件分别位于上述默认 experiments / reports 目录，不把原始日志加入公开仓库。

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

## 边界与下一批

每项只执行一次，来源均单一配置，不能作重复稳定性或显著性结论。断言检查必要工具结果和精确答案，不禁止全部额外行为，也不提供通用调用顺序 / 次数断言。目录发现接受合理列表范围，暂时故障的实际先后由状态化环境限定。

双配置真实比较仍待选择第二套配置与预算，M6.4 页面点击取消、正常退出及处理中断仍未验收。当前方案见 [M6 计划](plans/m6-reliability-validation.md)。
