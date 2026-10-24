# M4.1 重复试验与指标口径

更新：2026 年 10 月 21 日，Asia/Shanghai。实验输入、结果及 metrics 均为版本 1。Python 将用例、配置、重复次数展开为已有 M3.4 顺序批次；隔离、取消、超时及清理策略继续由原 batch / runner 执行。

## 运行与输入

M6.3 的 [固定评测集](core-evaluation.md) 另提供 10 个用例各一次的单配置清单：`python -m dsh_eval --experiment fixtures/evaluation/core/core.experiment.json --run`。同样会调用真实模型；它验证任务覆盖，没有重复样本或双配置配对，不能据此推断配置提升。

在仓库根目录执行，以下命令会执行两个真实模型任务，每个任务可能包含多次模型调用：

```powershell
python -m dsh_eval --experiment fixtures/evaluation/recovery.experiment.json --run
```

`--experiment` 必须搭配 `--run`，不能与 `--case`、`--batch`、`--evidence`、`--output` 组合。`--runs-root` 是新实验目录的父目录，默认 `runs/experiments`；`--host-modules`、`--cancel-after-stream` 继续传给每次实际运行。退出码沿用 0 passed、1 failed、2 unevaluable / 输入或输出错误。宿主、凭据引用与预算范围见 [单用例运行](single-case-runner.md)。

```json
{
  "experimentFormatVersion": 1,
  "experimentName": "repeat-recovery",
  "repetitions": 2,
  "failurePolicy": "continue",
  "cases": [{ "entryId": "retry", "casePath": "retry-read.case.json" }],
  "configurations": [{
    "configurationId": "flash",
    "configRef": {
      "provider": "deepseek-official", "model": "deepseek-flash",
      "profile": "headless", "pluginVersion": "0.1.2"
    }
  }]
}
```

严格拒绝未知字段。experimentName 为非空名称；repetitions 为正整数，拒绝布尔值。cases 沿用 batch 的唯一 entryId 和相对清单解析的 POSIX casePath；允许同一 caseId 用多个 entryId 表示不同计划项。configurations 是非空数组，configurationId 在实验内唯一；configRef 四字段同 [评测格式](evaluation-format.md)。不同 configurationId 可以引用同一配置，但不会被自动视为不同模型。

读取并校验全部原始用例，再以每个实验 configRef **完整替换**用例原 configRef，预检全部组合的 headless / 插件版本；失败时不启动模型。输入与配置全部冻结后才运行。配置只包含现有 provider / model / profile / pluginVersion，不支持温度、系统提示词或任意宿主配置覆盖。

用例顶层可选 recorder.maxEventBytes / recorder.maxPendingBytes 沿原始输入、展开用例、批次输入和逐次执行快照完整保留；实验的 configRef 覆盖不会改动它。录制限制属于用例，不是实验 configurations 的维度，也不进入 requestedConfiguration / 实际路由匹配。若需比较不同录制限制，应使用各自明确声明的用例；报告的完整快照校验和非 configRef 任务指纹包含 recorder，省略与显式默认不会被静默归一化。字段约束见 [用例格式](evaluation-format.md)。

样本数 = cases 数 × configurations 数 × repetitions。顺序固定为重复轮次、用例顺序、配置顺序；repeatIndex 从 1 开始。没有随机化、并发或跨轮状态复用，每次都新建 home / workspace / store / session 与工具故障状态。

## 输出与关联

```text
runs/experiments/<experimentId>/
  experiment.json                   冻结输入，可再次运行成全新实验
  inputs/0001.case.json              原始用例快照
  expanded/sample-000001.case.json   实验配置替换后的输入
  expanded.batch.json               展开后的标准 batch 清单
  batches/<batchId>/
    batch-result.json               活动批次进度及终态
    cases/<caseRunId>/              原有逐次执行目录、case/evidence/evaluation/runtime
  experiment-result.json            实验计划、终态、样本及汇总
```

experimentResultFormatVersion=1。结果保存 experimentId、名称、原始清单路径、冻结清单路径、配置、重复数、顺序、策略和 UTC 起止时间，以及 batchId / batchResultPath。status / stopReason / outcome 沿用批次含义；completed 不表示任务全通过。

samples 按执行计划保留所有项，每项含 sampleId、caseEntryId、caseId、configurationId、repeatIndex，加上批次原有 entryId、caseRunId、runId、sessionId、三维结果、实际配置、source、metrics 和证据路径。sampleId 对应实际 batch entryId；执行身份去重并核对样本、caseId 和请求配置。结果内所有样本输出路径相对 experimentDirectory；原始来源路径仍为绝对路径。样本计划身份不等于实际模型调用，尚未执行项保留 skipped 和空事实。

requestedConfiguration 来自计划；configuration 来自实际适配器观察，缺失仍为 null。configurationMatch 为 matched / mismatched / unknown。groups 按 caseEntryId + configurationId 汇总**请求配置安排的样本**，不能把 mismatched 或 unknown 项解释成目标模型的成绩。每次原始结果与实际配置都可追溯。

实验开始先写 status=running 的计划文件；运行期间查看 batches 下的 batch-result.json。批次返回并核对关联后，才以同目录独立临时文件 replace 实验结果为终态；终态不再修改。若进程中断、关联检查失败或写入失败，可能保留 running、空 summary 或临时文件，不能当作成功。没有 fsync、崩溃恢复或 resume。再次运行保存的 experiment.json 会调用模型并创建新实验，不是轨迹重放。

离线复验某一样本时，使用该执行目录自己的快照，不修改原结果：

```powershell
python -m dsh_eval --case 'runs/experiments/<experimentId>/batches/<batchId>/cases/<caseRunId>/case.json' --evidence 'runs/experiments/<experimentId>/batches/<batchId>/cases/<caseRunId>/evidence.json'
```

## 样本与分母

summary 与每个 group.summary 保留以下字段：

| 字段 | 口径 |
| --- | --- |
| planned | 所有计划样本，包括 skipped |
| attempted | 已分配 caseRunId 的尝试；包括准备 / 启动失败，不等于模型请求数 |
| finished / errors / skipped | 已取得单次结果 / 调度或结果错误 / 尚未执行，按原 status 计数 |
| outcomes | passed / failed / unevaluable 各自数量；skipped 的 outcome=null，不补成失败 |
| evaluablePassRate | passed / (passed + failed)，只有正常完成、录制有效、证据充分的任务进入分母 |
| attemptedPassRate | passed / attempted，取消、超时、启动或运行错误、证据不足都留在分母中 |
| evaluableCoverage | (passed + failed) / planned，显示无法评测和停止跳过的影响 |
| executionStatusCounts / recordingOutcomeCounts / assertionOutcomeCounts | 独立列出三维分布，缺失事实按 unknown 计数 |
| sourceCounts / configurationMatchCounts | 来源声明和实际配置匹配的覆盖情况；source 本身不是模型调用证明 |

每个比例都保存 numerator、denominator、value；分母为零时 value=null。人工中断和清理未确认仍停止整批。任务 isError 工具结果可为正常任务证据；取消与损坏录制不能计为普通答案失败。批次策略见 [批次运行](batch-runner.md)。

## 指标：metricsFormatVersion 1

每次离线 evaluate 都先重新执行真实 Node inspect，不沿用旧结果里的计数。日志必须 complete、身份匹配，并能确定唯一输入、唯一关闭轮次、连续序号及指标事件位于任务内，才提取日志指标；无闭合边界、缺失、损坏或不匹配时保持 null。metrics 的失败或缺失不会改写原三维任务结论。取消或运行错误也可以保留已经验证的闭合片段观测。

| 字段 | 实际来源与范围 |
| --- | --- |
| modelCalls | 任务内 assistant/message + assistant/attempt 的数量，表示**已记录并结算的模型尝试**；包含中断前缀和无消息失败尝试，不保证覆盖未结算请求或适配器内部未记录的重试，不是供应商账单次数 |
| toolCalls | 任务内 tool/call 事件数，含失败工具调用；不按结果数或成功数代替 |
| inputTokens / outputTokens / totalTokens | assistant/message.data.usage 对应字段逐消息求和；每条消息该字段都必须为可表示为有限浮点数的非负整数且无 assistant/attempt，该字段之和也须在有限范围内，否则该指标 null；没有报告 totalTokens 时不由其他字段补算 |
| elapsedSeconds | runner 的 monotonic 计时：保存初始 case 快照后，到保存 runtime 前；包含环境准备、安装、执行、清理及运行事实整理，排除离线 inspect / 断言和最终结果写入，不是纯模型延迟或任务预算 |
| cost | 当前没有价格及计费采集，恒为 null |

request/header 是模型配置 / 请求 epoch 的变更事件，不能代替请求次数；token 只读宿主声明的 usage，不能从流 chunk、字符数或步骤估算。inputTokens / outputTokens 缺失与数值 0 不同。暂不统计缓存、推理 token 或货币单位。

elapsedSeconds 保存到 runtimeFormatVersion=1 的可选字段。离线仅在 runtimeFormatVersion 与 caseRunId 匹配、值有限且非负时使用；历史文件没有计时仍为 null。runtime 是适配器事实，不受录制摘要签名保护，即使日志不可用也可以保留独立的运行耗时。

2026 年 10 月 21 日修复数值溢出：超出有限浮点表示范围的单值保持 null，避免 math.isfinite 转换超大整数时中断评测；有效 token 字段仍保留整数，不转成浮点数、截断或补零。各字段独立处理，某字段溢出不抹掉其他字段、调用次数或三维任务结论。

各指标汇总分别给出 observedSamples、missingSamples、observedTotal、observedMean。缺失样本包括 skipped；没有观测时总和与均值都为 null。部分样本有值时只汇总已观测子集，不能称为全实验总 token / 耗时或成本。合成数据用于确定性验证，不能作为模型表现比较。

汇总仅接纳非负、可表示为有限浮点数的 int / float，拒绝布尔值及超大数值，拒绝的单值计入 missingSamples。若单值均有效但求和超出范围，observedSamples / missingSamples 保持实际覆盖，observedTotal / observedMean 均为 null，另有可选 reason 说明汇总数值超出范围；不输出 Infinity 或 NaN，也不改变通过比例的分母。该字段为版本 1 兼容扩展，旧结果不改写。回归与验证见 [修复记录 018](changes/2026-10-21-018-m4-1-metric-overflow.md)。

M4.1 本身没有 pass@k、置信区间、显著性判断或性能提升结论，主体依据见 [修改记录 017](changes/2026-10-21-017-m4-1-repeated-experiments.md)。M4.2 已在独立报告中增加配置比较和不确定性边界：`python -m dsh_eval --report 'runs/experiments/<experimentId>/experiment-result.json'` 重新核对冻结输入 / 实际路由 / 来源并复验，不覆写实验。新报告说明全部分母、同来源配对、逐指标共同覆盖和观测范围；一个配置或同配置别名没有配置间差值。格式与限制见 [配置报告](configuration-reports.md)。
