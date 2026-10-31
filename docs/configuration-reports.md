# M4.2 离线配置比较报告

更新：2026 年 10 月 28 日，Asia/Shanghai。普通实验保持 `comparisonReportFormatVersion=1`，首轮续跑报告保持版本 2，连续续跑使用版本 3。都重新核对计划及样本，生成独立 JSON / Markdown，不执行模型任务。

[双配置八任务准备](guarded-comparison.md) 新增两用例各两轮的合成链路回归，验证各用例独立配对、异常配对排除、缺失指标与停止分母。它不提供第二模型的真实比较结论，报告协议和计算规则不变。

## 使用

在仓库根目录，把路径中的实验 ID 替换为已保存的实际值：

```powershell
python -m dsh_eval --report 'runs/experiments/<experimentId>/experiment-result.json'
# 可选：指定新报告目录的父目录
python -m dsh_eval --report 'runs/experiments/<experimentId>/experiment-result.json' --reports-root 'runs/reports'
```

`--report` 与 `--case` / `--batch` / `--experiment` 互斥，不能使用 `--run`、`--evidence`、`--output`、`--runs-root` 或宿主运行控制。退出码 0 表示报告成功生成；样本 failed / unevaluable、无法配对仍可正常生成报告。输入结构、关联或写入错误返回 2。原有运行 / 离线评测退出码不变。

普通实验输入必须为终态 completed / stopped / interrupted / error 且含 finishedAt；running 不接受。支持一个现有版本 1 实验及其完整目录，或下节所述的单个显式实验续跑，不合并任意实验，不用新公共用例替换历史快照。增加待比较配置应在实验清单中填写不同 configRef，并执行新的实验；不同 configurationId 指向同一 configRef 时，报告不会把它们当作不同模型。

默认创建 `runs/reports/<reportId>/`：

```text
report.json                       结构化报告、样本与比较
report.md                         可阅读的统计、差值和证据链接
evaluations/000001.json            本次重新 inspect 和断言的结果
```

每次新建 UUID 目录，文件以排他创建方式写入；不覆盖原实验、旧 evaluation 或已有报告。stdout 输出报告 JSON，包含 reportDirectory。写入错误可能留下未完成的新报告目录，不支持原子发布、断电保证或续写。整个目录仍在忽略的 runs 内，包含私人任务与本机证据路径，不作为公开夹具。

命令行 JSON stdout 固定 UTF-8，重定向时不随 Windows 系统代码页改变。JSON 的 generatedAt 保存 UTC，Markdown 显示 Asia/Shanghai 时间。Markdown 将缺失数值显示为“缺失”、浮点数显示六位有效数字；完整原数值在 JSON 中保留，不参与重新舍入后的统计。

## 实验续跑的跨批次报告

055 产生的终态实验续跑结果可以直接交给同一个入口：

```powershell
python -m dsh_eval --report 'runs/experiment-resumes/<resumeId>/experiment-resume-result.json' --reports-root runs/reports
```

它读取一个显式关联的原实验、原批次、批次续跑及新批次，生成版本 2 的 report.json / report.md。原实验可能因中断仍为 running；实验续跑、下层批次续跑及新批次本身必须终态且状态一致。纯批次 resume-result.json 没有用例 / 配置 / 轮次矩阵，不是该入口的输入。成功返回 0，结构 / 关联错误仍使用公共版本 1 错误 JSON / 退出 2，不创建新报告目录或运行模型。

在 inspect 和输出之前核对：

1. 实验续跑与 resume-plan.json 的身份、来源、摘要、上限、分类和样本映射一致。重新验证原计划快照与完整矩阵，并要求保存的原实验 / 冻结输入 / 源元信息字节摘要一致。
2. 下层续跑必须位于显式的 continuations/<batchResumeId>/resume-result.json，源批次领取记录的身份 / 目录与它一致；下层保存的计划摘要、原批次 / 待执行与复用项、上限和计数必须对应。
3. 新批次的来源、身份、输入指纹、剩余清单 / 冻结输入、顺序和原 sampleId 对应，不重复或遗漏原矩阵位置。跨两个批次的 caseRunId / runId / sessionId 不能重复。路径继续采用包含关系检查；skipped 不允许带实际执行 / 来源 / 指标事实。

核对绑定后，历史复用项和新增项都交给同一 _recheck / evaluate / Node inspect 流程，分别使用其实际批次 ID 和证据根。原 checkpoint 落后但完整评测已保存的复用项，按受控 caseDirectory 补出固定文件位置后再检查证据，不扫描目录猜测运行。

[058 修复](changes/2026-10-27-058-resume-lock-report-version.md) 后，共用归档加载器只做静态结构与一致性检查，不调用 validate_live_case 或要求归档 pluginVersion 等于当前 package.json。本地插件升级后，已有续跑结果仍可重新生成报告；保存配置、录制插件版本和实际请求路由的逐项核对继续有效。当前安装版本及 headless 限制仍用于续跑预检 / 执行，生成报告成功不表示可在当前环境继续执行。

保存的预检摘要含历史录制文件的旧摘要，但报告不会要求这些证据字节保持不变而拒绝整份输入；录制 / evidence / runtime / 已执行 case 快照的当前问题按原逐样本规则重新判定，保留原计划 / 尝试分母。元信息、计划、绑定或冻结输入冲突则整份拒绝。配置或实际 request/header 不匹配、来源不同、坏录制等仍排除对应配对。

版本 2 新增或调整：

| 字段 | 含义 |
| --- | --- |
| sourceResumeResult / resumeId | 本次报告读取的实验续跑结果及其身份 |
| sourceExperimentResult / experimentId | 原实验来源与身份；原文件不修改 |
| batchId / batchIds | 单一 batchId 为 null；batchIds 顺序为原批次、新批次 |
| resumeVerification | 保存的两层续跑计划摘要、显式关联的下层结果及结构复核状态；不代表任务通过 |
| samples.executionOrigin | reused / new；与各样本 sourceBatchId / sourceBatchResult 一起说明实际证据来源 |
| reusedSummary / newlyExecutedSummary | 都由本次逐项复验重新计算；前者是历史任务，后者仅含新批次，包括其错误 / 跳过 |
| groups.byExecutionOrigin | 同一用例 / 配置内分别统计 reused / new，保留零分母和指标缺失 |
| savedSummary / summary | 下层保存的 combinedSummary / 本次重新复验的全部原计划样本汇总 |

原 samplePlan / counts 只是启动计划，不作为最终执行状态。最终新项状态取自实际新批次，再重新复验；历史 failed 不会因为新任务 passed 而消失。Markdown 显示历史 / 新增的分母、指标累计值、均值、范围、覆盖及逐样本来源，缺失费用保持“缺失”。普通批次摘要、源汇总和旧 evaluation 均不回填。

配置配对可以跨执行来源，例如同一原 repeatIndex 的左侧已完成、右侧为本次新增；仍须同用例、同轮次、同 live / synthetic 来源，且两侧 verified / matched。reused / new 表示执行时间归属，不替代 live / synthetic 的证据来源。调用和 token 的全部样本合计含历史观察量，不能全部当作本次新增消耗。

本批不合并多个实验、不自动跟随再次续跑，续跑来源不支持目录搬迁；普通版本 1 实验的整体搬迁能力保持原范围。[结果浏览器](result-browser.md) 已接入版本 2，展示保存的原 / 新批次关联与分开的历史 / 新增用量；浏览不重新复验，见 [057](changes/2026-10-27-057-resume-report-browser.md)。报告要求停止写入后的稳定来源，没有多文件事务、签名或断电保证。报告实现和无模型验证见 [056](changes/2026-10-27-056-experiment-resume-report.md)。

## 连续续跑报告版本 3

[059](changes/2026-10-28-059-continuation-chains.md) 让同一 --report 入口接受 experimentResumeResultFormatVersion=2 的终态结果。沿显式祖先链核对每轮计划、来源批次、领取、冻结输入、剩余顺序和身份，按完整原矩阵重新评测各样本。祖先续跑可保留崩溃时的 running；选定的最新结果及其下游必须终态。归档元信息 / 冻结输入冲突整份拒绝；历史录制 / 证据变化继续按逐样本复验处理，保留原分母。

版本 3 保留版本 2 的统计字段，batchIds 依次包含原批次和全部后续批次，batchResultPaths 给出对应的显式绝对结果路径；resumeChain 按顺序保存每个 resumeId / resultPath。sourceResumeResult 指向本报告选定的最新续跑结果。reusedSummary 是该轮之前所有批次的复验统计，newlyExecutedSummary 只描述该轮新批次。savedSummary 是该轮保存的全矩阵 combinedSummary；summary 是报告本次重新复验值。两者都不是纯粹的本轮新增消耗。

可以跨任意历史批次配对同一原用例 / 配置 / repeatIndex，仍须同 live / synthetic 来源并 verified / matched。报告不改变原轮次和计划数量，不扫描或自动跟随更新的续跑。最多读取 32 个续跑结果，循环、重复身份或未来版本拒绝；归档路径搬迁和任意跨实验合并不支持。浏览器支持版本 1 / 2 / 3，版本 3 可打开全部批次及祖先续跑，仍只读保存内容。

## 核对顺序与失败行为

报告先以用例条目数 × 配置数 × 重复数计算预期总数，核对保存的 samples / batch entries 类型与数量，再按固定顺序逐项检查；不先展开完整位置列表。这样损坏的重复次数或非法样本容器会在位置枚举、inspect 和输出之前拒绝，新快照与旧格式都适用。该检查不提供输入文件字节或总内存硬上限，见 [复审修复 045](changes/2026-10-25-045-plan-review-fixes.md)。

1. 从传入结果旁解析冻结的 experiment.json 和批次结果，不依赖历史 experimentDirectory / batchDirectory 等绝对位置。核对版本、终态、配置、重复次数、展开顺序、完整样本数、计划位置及 batchId / sampleId / caseRunId / runId / sessionId。重复执行 / 录制身份或实验与批次关联冲突会拒绝整份输入。
2. 检查实验和批次路径一致、保持在对应目录内。清单路径须为相对 POSIX 路径，拒绝绝对路径、越界与符号链接逃逸；现有 runner 证据中的 Windows 分隔符另行兼容。完整实验目录复制到新位置后，可以从新位置报告。
3. 每项以原冻结用例完整替换 configRef 得到期望输入，与批次输入及执行目录 case.json 比较，包含任务、环境初始声明 / 故障计数、预算、断言、版本和 caseId。`taskFingerprint` 是除 configRef 外整个用例的规范 JSON UTF-8 SHA-256，不是签名，也不能证明磁盘环境实际被怎样创建。
4. 核对 evidence 的执行 / 会话 / 批次身份、source、实际配置、录制与 runtime 路径，然后调用原 evaluate，重新运行 Node inspect 和断言。不沿用保存的通过结论或指标。旧汇总只保留为 savedSummary，逐样本保存 saved 和 changedFields，便于解释复验变化。
5. 实际配置只有同时满足 evidence 全 configRef 匹配、录制 complete 且身份一致、至少一个 request/header、所有头的 provider / model 匹配，才记 matched。声明不同或头路由不同为 mismatched，缺配置 / 无可靠日志 / 缺路由为 unknown。profile 仍是适配器声明；日志可核对 provider / model 及录制器插件版本，不另推断隐藏配置。

样本 verification=verified 表示关联核对及复验处理完成，**不表示任务或录制通过**；具体看执行 / 录制 / 断言三维结果。输入快照不符、证据丢失或身份冲突的 finished 样本为 rejected，保留在计划 / 尝试分母中，新的 outcome=unevaluable，不沿用旧成功。原调度 error 且无法复验为 unavailable；skipped 不构造实际身份或任务结果。

日志损坏、未封存或 inspect 不可用时，原 evaluate 保留 invalid / unverified，断言和日志指标按原规则缺失；独立且身份匹配的 runtime 耗时仍可观测。关联通过后发现坏日志的样本仍可能 verification=verified，其 configurationMatch=unknown，不能进入配对。

## 计划输入与指纹复核

043 之后的新实验声明 planInputPath，指向保存完整版本 1 指纹载荷的 plan-input.json。报告在逐样本 inspect 和新报告目录创建之前复核它；路径沿用相对 POSIX / 解析后真实目录包含关系检查，拒绝绝对路径、越界或目录链接逃逸，不读取历史 sourceManifest 或来源用例。全部实验目录搬迁后仍可核对。

先严格检查保存的 planFingerprint 版本 / 小写 64 位摘要和可选 expectedPlanSha256 的格式与相等关系，再核对快照的版本、精确字段、顺序、合法上限和完整用例数量。原始清单除冻结时重写的 casePath 外必须与冻结 experiment.json 一致，条目身份 / 顺序必须相同；按条目加载的每个原始用例必须与 inputs 中的完整冻结用例一致，含预算、环境 / 故障声明、原 configRef、断言及 recorder 原声明。最后复用版本 1 指纹计算，要求快照、结果 maxSamples、实际指纹及已声明预期值一致。

新 JSON 报告的 planVerification 包含：

| 字段 | 含义 |
| --- | --- |
| status | verified：快照与冻结输入 / 保存摘要一致；unverified：未声明可复核的计划输入快照 |
| fingerprint / expectedPlanSha256 | 保存的实际指纹 / 可选预期摘要，未知保持 null；unverified 状态不能把保存声明当作已重算事实 |
| inputPath / reason | 已复核快照的相对路径，或旧结果无法重算的原因；旧结果 inputPath=null |

Markdown 明示“计划指纹复核：verified / unverified”。未声明 planInputPath 的旧实验，包括只有 042 指纹元信息的实验，仍可正常报告和复验样本，计划状态保持 unverified；不补造快照或改写旧结果。新实验声明过快照却找不到文件、格式未知、越界或内容不一致，会以输入错误拒绝整份报告，CLI 返回 2，不创建报告目录，也不先运行 inspect。

[044](guarded-acceptance.md) 已用现有 deepseek-flash 的两个用例各两次完成真实链路验收，四样本复核 verified / matched / live、计划 verified，80 份选定源文件复验前后不变；一个配置不生成 comparisons。首轮准备失败的独立实验也保留一项 unevaluable / 三项 skipped，计划 verified 不代表该任务通过。

planVerification 与样本 verification、录制 outcome、任务 outcome 分别判断：计划 verified 后仍可能出现坏日志、取消或任务失败；旧计划 unverified 也不改变有充分录制证据的任务结论。SHA-256 和快照不是签名：若全部快照、冻结输入与摘要一起改写，或删除元信息后伪装成旧格式，本工具不能认证原始来源；不能据此证明模型表现、运行时环境、费用或当时是否实际执行了预期摘要检查。原算法与文件定义见 [实验说明](experiments.md#计划指纹与执行前一致性检查)，当前实现和验证见 [043](changes/2026-10-25-043-plan-snapshot-report-verification.md)。

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
