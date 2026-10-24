# M4.2 离线配置比较报告

更新：2026 年 10 月 21 日，Asia/Shanghai。`comparisonReportFormatVersion=1`。读取一个已经结束的 M4.1 实验，重新核对样本并生成独立 JSON / Markdown，不执行模型任务。

## 使用

在仓库根目录，把路径中的实验 ID 替换为已保存的实际值：

```powershell
python -m dsh_eval --report 'runs/experiments/<experimentId>/experiment-result.json'
# 可选：指定新报告目录的父目录
python -m dsh_eval --report 'runs/experiments/<experimentId>/experiment-result.json' --reports-root 'runs/reports'
```

`--report` 与 `--case` / `--batch` / `--experiment` 互斥，不能使用 `--run`、`--evidence`、`--output`、`--runs-root` 或宿主运行控制。退出码 0 表示报告成功生成；样本 failed / unevaluable、无法配对仍可正常生成报告。输入结构、关联或写入错误返回 2。原有运行 / 离线评测退出码不变。

输入必须为终态 completed / stopped / interrupted / error 且含 finishedAt；running 不接受。当前仅支持一个现有版本 1 实验及其完整目录，不合并多个实验，不用新公共用例替换历史快照。增加待比较配置应在实验清单中填写不同 configRef，并执行新的实验；不同 configurationId 指向同一 configRef 时，报告不会把它们当作不同模型。

默认创建 `runs/reports/<reportId>/`：

```text
report.json                       结构化报告、样本与比较
report.md                         可阅读的统计、差值和证据链接
evaluations/000001.json            本次重新 inspect 和断言的结果
```

每次新建 UUID 目录，文件以排他创建方式写入；不覆盖原实验、旧 evaluation 或已有报告。stdout 输出报告 JSON，包含 reportDirectory。写入错误可能留下未完成的新报告目录，不支持原子发布、断电保证或续写。整个目录仍在忽略的 runs 内，包含私人任务与本机证据路径，不作为公开夹具。

命令行 JSON stdout 固定 UTF-8，重定向时不随 Windows 系统代码页改变。JSON 的 generatedAt 保存 UTC，Markdown 显示 Asia/Shanghai 时间。Markdown 将缺失数值显示为“缺失”、浮点数显示六位有效数字；完整原数值在 JSON 中保留，不参与重新舍入后的统计。

## 核对顺序与失败行为

1. 从传入结果旁解析冻结的 experiment.json 和批次结果，不依赖历史 experimentDirectory / batchDirectory 等绝对位置。核对版本、终态、配置、重复次数、展开顺序、完整样本数、计划位置及 batchId / sampleId / caseRunId / runId / sessionId。重复执行 / 录制身份或实验与批次关联冲突会拒绝整份输入。
2. 检查实验和批次路径一致、保持在对应目录内。清单路径须为相对 POSIX 路径，拒绝绝对路径、越界与符号链接逃逸；现有 runner 证据中的 Windows 分隔符另行兼容。完整实验目录复制到新位置后，可以从新位置报告。
3. 每项以原冻结用例完整替换 configRef 得到期望输入，与批次输入及执行目录 case.json 比较，包含任务、环境初始声明 / 故障计数、预算、断言、版本和 caseId。`taskFingerprint` 是除 configRef 外整个用例的规范 JSON UTF-8 SHA-256，不是签名，也不能证明磁盘环境实际被怎样创建。
4. 核对 evidence 的执行 / 会话 / 批次身份、source、实际配置、录制与 runtime 路径，然后调用原 evaluate，重新运行 Node inspect 和断言。不沿用保存的通过结论或指标。旧汇总只保留为 savedSummary，逐样本保存 saved 和 changedFields，便于解释复验变化。
5. 实际配置只有同时满足 evidence 全 configRef 匹配、录制 complete 且身份一致、至少一个 request/header、所有头的 provider / model 匹配，才记 matched。声明不同或头路由不同为 mismatched，缺配置 / 无可靠日志 / 缺路由为 unknown。profile 仍是适配器声明；日志可核对 provider / model 及录制器插件版本，不另推断隐藏配置。

样本 verification=verified 表示关联核对及复验处理完成，**不表示任务或录制通过**；具体看执行 / 录制 / 断言三维结果。输入快照不符、证据丢失或身份冲突的 finished 样本为 rejected，保留在计划 / 尝试分母中，新的 outcome=unevaluable，不沿用旧成功。原调度 error 且无法复验为 unavailable；skipped 不构造实际身份或任务结果。

日志损坏、未封存或 inspect 不可用时，原 evaluate 保留 invalid / unverified，断言和日志指标按原规则缺失；独立且身份匹配的 runtime 耗时仍可观测。关联通过后发现坏日志的样本仍可能 verification=verified，其 configurationMatch=unknown，不能进入配对。

## 分母、来源与比较

`summary` 以及每个 caseEntryId / configurationId 的 `groups.summary` 统计**全部计划项**，沿用 M4.1 的三个比例：

| 比例 | 分子 / 分母 |
| --- | --- |
| evaluablePassRate | passed / (passed + failed) |
| attemptedPassRate | passed / 已分配 caseRunId 的样本数 |
| evaluableCoverage | (passed + failed) / planned |

每项保存 numerator / denominator / value，零分母 value=null。skipped、调度 error 和三维状态分别保留；attempted 不是供应商请求次数。重新核对失败不会删除计划项。

组内另外提供 matchedSummary 和 bySource。matchedSummary 只描述复验完成且实际配置匹配的子集，其 planned 是该子集数量，不替代全部计划分母。bySource 的 planned 是该来源的样本数，未知 / 被拒绝 / skipped 为 unknown。请求分组中的全部指标可能含配置不符或来源不同的样本，必须结合匹配分布与来源阅读，不能直接当作目标模型成绩。

`comparisons` 按每个用例、两个 configurationId 和来源分开。只将同 repeatIndex、source 相同且两侧均 verified / matched 的项配对，不跨用例或拼接不同重复编号。live / synthetic 只是证据声明，不是签名；合成来源始终分开，不能证明模型表现。没有已知来源时保留 unknown / unavailable 条目。

| 比较字段 | 含义 |
| --- | --- |
| plannedPairs | 此用例每个配置计划的重复次数；各来源条目均使用这个原始上限 |
| pairedSamples / excludedPairs / repeatIndices | 当前来源下共同可配对数量、排除数量与实际重复编号 |
| leftSummary / rightSummary | 同一配对子集的三维分布、分母与指标覆盖 |
| rateDifferences | 右侧比例减左侧比例；任一分母为零则 null；比例单位为 0 到 1 的差 |
| status / reason | 有可配对且 configRef 不同为 descriptive；没有样本或同配置别名为 unavailable，差值保持 null |

completed 且断言明确失败的任务保留 failed；取消、超时、运行错误保持 unevaluable。若取消样本仍有完整匹配路由，可进入同来源配对子集，其尝试分母保留、可评测分母排除。未启动且配置 unknown、坏日志或 skipped 不能进入配对，但全部计划统计仍显示其影响。配对覆盖不足可能产生选择偏差，不能用条件通过比例代表整个实验。

## 指标与不确定性

继承 [M4.1 指标口径](experiments.md)：调用是已结算录制事件，token 是宿主报告的 usage，耗时包含准备 / 执行 / 清理，费用缺失。每项汇总增加 observedMin / observedMax，原 observedSamples / missingSamples / observedTotal / observedMean 保留。缺失、实测零、有效子集求和溢出分别呈现；溢出 reason 在 JSON 和 Markdown 中保留，不输出 Infinity / NaN。

每个比较指标还会再次选择**两侧都有该指标的相同配对**，输出 pairedSamples / missingPairs、两侧汇总、meanDifference（右均值减左均值）、单对差值的 minDifference / maxDifference。missingPairs 以 plannedPairs 为分母，包含路由 / 来源 / 录制排除和指标缺失；不能将两侧覆盖不同的独立均值直接相减。某侧有效值求和溢出时，覆盖和范围保留，均值与均值差为 null，即使单对差值范围可计算。

报告公开样本量、实测范围、来源、覆盖、排除项和缺失原因；不计算置信区间、pass@k、显著性或赢家。固定重复 / 用例 / 配置顺序没有随机化，也没有验证独立同分布假设。范围是当前样本的范围，不是总体不确定性的置信区间。两个验收样本不足以宣称成功率、性能或成本提升。

复验须读取停止写入后的稳定实验目录；本工具没有在线一致快照、证据签名或隐藏运行配置的验证能力。已实现与本轮验证分别见 [开发进度](progress.md) 和 [修改记录 019](changes/2026-10-21-019-m4-2-configuration-reports.md)。M5 已提供 [只读结果浏览](result-browser.md)，可查看保存报告与证据；打开页面不会重新生成报告或验证日志。
