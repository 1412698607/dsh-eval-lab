# M4.1 重复试验与指标口径

更新：2026 年 10 月 25 日，Asia/Shanghai。实验输入、结果及 metrics 均为版本 1；独立预览使用 experimentPlanFormatVersion=1。Python 共用加载 / 预检和计划展开逻辑，再按显式模式打印预览或交给已有 M3.4 顺序批次；隔离、取消、超时及清理策略继续由原 batch / runner 执行。

[双配置八任务准备](guarded-comparison.md) 固定两用例、两配置、两轮，提供第二配置为空的待填写模板；原模板校验拒绝，填妥后使用既有 --plan / cap / 指纹链路。该准备批次只有合成回归，没有真实双配置执行。

## 无模型预检与计划预览

在仓库根目录运行，只需 Python，不安装 Harness 或读取模型凭据：

```powershell
python -m dsh_eval --experiment fixtures/evaluation/core/core.experiment.json --plan
```

读取清单、全部用例及本项目 package.json，校验输入结构、用例预算 / 录制声明和全部实验配置组合的 headless / 当前插件版本。成功向 stdout 输出缩进 UTF-8 JSON，退出码 0；输入、文件或兼容性错误返回版本 1 的计划错误 JSON（valid=false、modelCalled=false、error），退出码 2。参数冲突由命令行解析器向 stderr 报错并返回 2。valid=true 只表示这些静态检查通过，不代表宿主安装、凭据、provider / model 可用、运行时环境创建或任务答案已经验证。

| 字段 | 含义 |
| --- | --- |
| experimentPlanFormatVersion / valid / modelCalled | 独立版本 1 预览，静态预检通过，当前预览未调用模型 |
| experimentName / sourceManifest / configurations | 清单名称、解析后的来源路径及请求配置声明 |
| repetitions / failurePolicy / order | 重复次数、continue / stop 策略与 repeat-case-configuration 固定顺序 |
| counts.cases / configurations / samples | 用例条目数、配置条目数、计划任务数；不同条目可引用同一用例或配置 |
| maxSamples | 本次调用的任务数上限；未传入为 null，旧计划 / 结果可以没有此字段 |
| planFingerprint | {version: 1, sha256: 小写 64 位十六进制摘要}，覆盖本次加载的实验输入、顺序与任务上限 |
| estimates.modelCalls / totalTokens / cost | 未来执行的调用数、token 和费用未知，均为 null；任务数不等于调用数 |
| samples | 按执行顺序列出 sampleId、caseEntryId、caseId、configurationId、repeatIndex、requestedConfiguration、budget、recorderOverrides |

10 个用例条目 × 2 个配置条目 × 3 轮会列出 60 个任务，而不是声明 60 次模型调用。每项 budget 保留原 timeoutSeconds，它不是总退出硬期限或费用上限。recorderOverrides 只展示用例原始录制覆盖：未声明为 null，空对象为 {}，部分 / 完整覆盖保留声明值；不在 Python 预览中复制 Node 默认值或将原始输入补齐。实际录制有效值仍由宿主配置解析并写入 run.json。

`--plan` 只用于 `--experiment`，与 `--run` 互斥；拒绝 --evidence、--output、--runs-root、--host-modules、--cancel-after-stream 及浏览 / 报告参数，包括空字符串选项值。预览只打印 JSON，不创建实验 / batch / workspace 目录，不安装宿主、调用 inspect、启动任务或生成执行 UUID、状态和 outcome。需要保存输出时由调用方处理 stdout；它不是可执行的冻结清单。

预览和 --run 共用同一套加载 / 预检及样本展开逻辑。预览不锁定源文件；后续 --run 仍会重新读取、校验并冻结当时输入，期间修改文件可能改变计划。原预览实现与无模型验证见 [记录 040](changes/2026-10-24-040-experiment-plan-preview.md)，可选任务数上限见下节。

## 可选任务数上限

```powershell
python -m dsh_eval --experiment fixtures/evaluation/core/core.experiment.json --plan --max-samples 10
```

`--max-samples N` 只适用于 `--experiment --plan` 或 `--experiment --run`，N 必须是正整数。默认不设上限，保持已有调用兼容。总任务数按 cases 条目数 × configurations 条目数 × repetitions 计算；重复引用同一用例、同一请求配置也分别计数。等于上限允许，超过则整份拒绝，不截断矩阵或自动减少重复次数。

共用加载函数先校验参数和实验清单，再直接乘法检查总数，通过后才读取用例、校验全部组合、展开任务。超限不生成 UUID 或运行目录，不调用宿主 / 模型。--plan 返回原计划错误 JSON（valid=false、modelCalled=false、error）/ 2；--run 沿用实验错误 JSON（outcome=unevaluable、error）/ 2，它是启动前拒绝，没有生成实验结果文件。非法值或无关模式由命令行解析器向 stderr 报错并返回 2。Python API 的 plan_experiment / run_experiment 使用仅关键字参数 max_samples=None，同样严格拒绝布尔值、零、负数和非整数。

新计划及实验结果以 maxSamples 记录本次参数，未指定为 null；输入清单格式不变，不能将 maxSamples 加入 experiment.json。它是当次调用的保护，不写入冻结清单，重新运行冻结清单仍需显式传入。预览后修改输入，实际 --run 会重新计算并检查；只在 --plan 使用该参数不能限制下一次未带参数的 --run。

该上限只约束计划任务数：单任务仍可多次调用模型，超时不是费用预算，modelCalls / totalTokens / cost 估算继续为 null。清单本身仍须完整读取 / 校验，单个用例大小和调用方选用的上限没有内建硬限制；不设上限时仍会完整展开矩阵。实现与无模型验证见 [记录 041](changes/2026-10-25-041-experiment-sample-limit.md)。

## 计划指纹与执行前一致性检查

预览输出 planFingerprint.version=1 / sha256。需要后续执行与本次预览的输入一致时，保存这个摘要，运行时传入 --expected-plan-sha256；不传保持旧行为。以下第一条只预览，第二条是实际运行示例，会调用配置的真实模型，需先安排实际规模：

```powershell
$plan = python -m dsh_eval --experiment fixtures/evaluation/core/core.experiment.json --plan --max-samples 10 | ConvertFrom-Json
```

确认预览的 valid / counts / configurations / maxSamples 后，实际运行示例：

```powershell
python -m dsh_eval --experiment fixtures/evaluation/core/core.experiment.json --run --max-samples 10 --expected-plan-sha256 $plan.planFingerprint.sha256
```

--expected-plan-sha256 仅适用于 --experiment --run；API 对应仅关键字 expected_plan_sha256=None。预期值必须恰好包含 64 个十六进制字符，大小写均接受，运行结果保存时转为小写；不接受前后空白。错误模式 / 缺失参数值由 argparse 向 stderr 报错 / 2；执行模式中的非法摘要或指纹不匹配沿用实验错误 JSON（outcome=unevaluable、error）/ 2，没有生成运行目录或实际执行身份。不匹配错误包含预期 / 实际摘要；静态输入校验和 --max-samples 检查仍然必须通过。

指纹版本 1 的输入是对象 `{"version":1,"manifest":<完整已校验清单>,"cases":[<按 cases 条目顺序加载的原始用例>],"maxSamples":<本次上限或 null>,"order":"repeat-case-configuration"}`。使用 Python json.dumps 的 ensure_ascii=False、sort_keys=True、separators=(",", ":")、allow_nan=False，按 UTF-8 编码后计算 SHA-256。对象键递归排序，数组保留顺序，按解析后的 JSON 内容计算：文件缩进、空白、Unicode 转义写法和对象键顺序不影响摘要；清单及用例整体搬迁且保留相对路径 / 内容，也不影响摘要。不是对原文件字节计算摘要，也不声明其他语言任意 JSON 序列化器都产生同一结果。

覆盖清单名称、failurePolicy、重复次数、条目身份 / 顺序 / 相对 casePath、配置身份 / 声明，以及每个原始用例的任务、环境 / 故障状态、预算、断言、configRef 和原始 recorder 声明。即使用例 configRef 会被实验配置覆盖，它仍属于原始输入快照；省略 recorder、空对象或显式默认值不同。任务上限也属于指纹，所以预览带上限而运行遗漏或改变上限会拒绝。只是改相对 casePath、即使指向相同内容，也会改变摘要。

运行先重新读取 / 校验输入，再生成当前指纹并核对；匹配后才生成 UUID、创建目录、冻结已读入的同一组数据并展开 / 执行。不会在核对后重新读取源用例。新实验结果保存实际 planFingerprint 和预期 expectedPlanSha256（未传为 null），新字段不进入冻结 experiment.json。旧版本 1 计划 / 结果没有这些字段仍能按原方式使用；要启用检查应重新预览。冻结清单改写了相对 casePath，因此对冻结清单重跑时应重新预览获取指纹，原摘要不自动继承。

[043](changes/2026-10-25-043-plan-snapshot-report-verification.md) 为新实验增加 plan-input.json，保存上面版本 1 的完整指纹载荷，experiment-result.json 用 planInputPath 声明相对路径。保存发生在预期摘要通过之后、任务展开 / 执行之前；--plan 仍只输出 JSON，不生成快照。它保留原始 casePath 与全部用例内容，原指纹算法及预览摘要不变。快照失败时不运行任务，但可能留下尚未完成的新目录。

离线 --report 先核对该快照与冻结 experiment.json / inputs 的对应关系，再重新计算并核对实际 / 预期摘要；不重新读取 sourceManifest 或原用例路径，实验目录可整体搬迁。JSON 的 planVerification 和 Markdown 显示 verified / unverified；旧实验未声明快照时保留未复核状态，声明过但文件缺失或不一致时拒绝报告。计划一致不代表录制或任务通过，详见 [报告的计划复核](configuration-reports.md#计划输入与指纹复核)。

[045 复审修复](changes/2026-10-25-045-plan-review-fixes.md) 补齐报告端数量检查顺序：先直接计算并核对已保存项数，再逐项检查计划位置，不先构造完整矩阵；异常重复次数在新 / 旧实验中都先于 inspect 和报告输出拒绝。执行入口的上限与原指纹载荷不变。

该检查检测预览与运行读入数据的变化，不是签名、完整性认证或可直接执行的冻结计划。预览 / 运行的多文件读取没有事务锁，不保证各文件取自同一瞬间；指纹不覆盖宿主模块、模型服务、凭据、代码版本和运行控制参数（如 --host-modules / --cancel-after-stream / --runs-root）。不能用它证明实际模型路由、环境可用、任务成功或费用受限，实际事实仍由运行证据核对。实现和无模型验证见 [记录 042](changes/2026-10-25-042-experiment-plan-fingerprint.md)。

## 运行与输入

实验级 `--resume-experiment` 尚未实现。下游新批次可按 [批次续跑](batch-resume.md) 显式复核 / 继续明确未开始项；它保存独立续跑结果和新批次，不回填原 experiment-result.json 的状态 / 汇总，不将不同执行身份自动合并成原实验报告。

2026 年 10 月 26 日增加用例的可选 [modelProviders](evaluation-format.md#可选外部模型路由两个用例版本通用)。计划样本在声明存在时显示路由，完整原始用例已纳入指纹，因此更换端点、凭据引用或模型目录会使旧摘要失效；冻结清单、用例及展开任务保留声明。未声明的新旧用例保留原行为，没有新的 experiment 字段或指纹算法版本。模型容量声明不增加 token / 费用预算；真实组件的本地注册检查不代表远端可用。

需要小批验收计划约束链路时，另有 [四任务清单](../fixtures/evaluation/core/guarded-acceptance.experiment.json)：两个既有用例各两次、单配置、失败即停。搭配 --max-samples 4 和 --expected-plan-sha256，实际命令、短目录要求、首轮准备失败及四任务真实结果见 [044 验收说明](guarded-acceptance.md)。

M6.3 的 [固定评测集](core-evaluation.md) 另提供 10 个用例各一次的单配置清单：`python -m dsh_eval --experiment fixtures/evaluation/core/core.experiment.json --run`。同样会调用真实模型；它验证任务覆盖，没有重复样本或双配置配对，不能据此推断配置提升。

在仓库根目录执行，以下命令会执行两个真实模型任务，每个任务可能包含多次模型调用：

```powershell
python -m dsh_eval --experiment fixtures/evaluation/recovery.experiment.json --run
```

`--experiment` 必须搭配互斥的 `--run` 或 `--plan`，不能与 `--case`、`--batch`、`--evidence`、`--output` 组合。以下是 --run 的执行约定：`--runs-root` 是新实验目录的父目录，默认 `runs/experiments`；`--host-modules`、`--cancel-after-stream` 继续传给每次实际运行。执行退出码沿用 0 passed、1 failed、2 unevaluable / 输入或输出错误。宿主、凭据引用与预算范围见 [单用例运行](single-case-runner.md)。

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
  plan-input.json                   原始清单 / 用例、顺序和上限的指纹载荷（版本 1）
  inputs/0001.case.json              原始用例快照
  expanded/sample-000001.case.json   实验配置替换后的输入
  expanded.batch.json               展开后的标准 batch 清单
  batches/<batchId>/
    batch-result.json               活动批次进度及终态
    cases/<caseRunId>/              原有逐次执行目录、case/evidence/evaluation/runtime
  experiment-result.json            实验计划、终态、样本及汇总
```

experimentResultFormatVersion=1。结果保存 experimentId、名称、原始清单路径、冻结清单路径、配置、重复数、顺序、策略、maxSamples、planFingerprint、expectedPlanSha256、planInputPath 和 UTC 起止时间，以及 batchId / batchResultPath。旧结果可以没有新增计划元信息；离线报告对未声明快照的旧实验保留 unverified，声明快照的新实验必须复核一致。status / stopReason / outcome 沿用批次含义；completed 不表示任务全通过。

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
