# 实验级安全续跑

更新：2026 年 10 月 28 日，Asia/Shanghai。`--resume-experiment --plan / --run` 接受原实验或已有实验续跑结果，仅为明确未开始项创建新批次。连续续跑保留完整原矩阵与所有历史证据，终态结果生成独立版本 3 报告；首轮报告保持版本 2，见 [059](changes/2026-10-28-059-continuation-chains.md)。首版预检、执行和报告分别见 [054](changes/2026-10-27-054-experiment-resume-preflight.md)、[055](changes/2026-10-27-055-experiment-resume-execution.md)、[056](changes/2026-10-27-056-experiment-resume-report.md)。

## 入口与返回值

```powershell
python -m dsh_eval --resume-experiment 'runs/experiments/<experimentId>/experiment-result.json' --plan --max-samples 6
```

API 为 `plan_experiment_resume(result_path, *, max_samples=None)`。--max-samples 限制拟执行的未开始样本数，不包括可复用项；原实验的 maxSamples 及原指纹仍按原计划独立复核。两种上限都不是模型调用 / token / 费用预算。

预检不安装宿主、不创建身份 / 输出目录、不写领取文件、不修改旧实验、输入或报告。允许原 evaluator 调用 Node inspect 读取录制，并使用已有批次内核锁协调；锁文件需可读写，内容不变。

成功预览 JSON 为 experimentResumePlanFormatVersion=1、valid=true、modelCalled=false、executionSupported=true。eligibleForResume 表示当前证据和调度规则允许续跑；执行仍须重新复核。结构有效且可续跑时退出 0；存在未知项、原停止策略、重复领取或无剩余项时退出 2，仍为 valid=true。缺少绑定、输入冲突、源批次不可用 / 持锁或输入参数错误返回 2，输入错误 JSON 为 valid=false；CLI 组合错误仍由 argparse 拒绝。

--runs-root / --host-modules / --cancel-after-stream / --output / --evidence / --reports-root 等执行或输出控制不可用于预检。计划仅打印 stdout，不自动保存文件；必须选择 --plan 或 --run。

显式执行须传入**实验预览的**摘要及相同的上限。下面的 --run 可能调用所配置的真实模型：

```powershell
$source = 'runs/experiments/<experimentId>/experiment-result.json'
$plan = python -m dsh_eval --resume-experiment $source --plan --max-samples 6 | ConvertFrom-Json
# 核对退出码、eligibleForResume、counts 和 reasons 后再执行。
python -m dsh_eval --resume-experiment $source --run --max-samples 6 --expected-plan-sha256 $plan.planFingerprint.sha256 --runs-root runs/experiment-resumes
```

执行 API 为 `resume_experiment(result_path, runs_root=None, modules_dir=None, cancel_after_stream=False, *, max_samples=None, expected_plan_sha256=None)`。摘要必填，接受 64 位十六进制并统一小写；不能用 batchPlanFingerprint 替代实验摘要。--host-modules / --cancel-after-stream 传给既有批次 / runner；--evidence / --output / --reports-root 不接受。执行结果使用 experimentResumeResultFormatVersion=1，passed / failed / unevaluable 分别退出 0 / 1 / 2；输入错误返回版本化 JSON 和退出 2，参数组合错误由 argparse 返回 2。

## 显式绑定与证据复核

新建实验在首次 checkpoint 前预留下游批次 UUID，保存：

```json
"resumeSupportVersion": 1,
"batchBinding": {
  "batchId": "<reservedBatchId>",
  "resultPath": "batches/<reservedBatchId>/batch-result.json"
}
```

run_batch 接受可选的 batch_id，使用该预留身份创建目录。batchBinding 是计划中的绑定，不表示已创建批次或调用模型；原 batchId / batchResultPath 仍在批次返回后才保存为观察结果。预检必须找到实际批次元信息，验证身份、sourceManifest、冻结清单和全部样本，不扫描目录猜测对应批次。批次尚未创建或旧实验缺少绑定时拒绝，不补造历史支持声明。

预检先锁定该实际批次，重新读取实验并确认绑定未变，然后：

1. 核对实验身份、顺序、配置、轮次、失败策略、原 maxSamples、plan-input.json 与原指纹，必须 planVerification=verified。
2. 在完整样本数量一致后，按 repeat / case / configuration 顺序检查 sampleId、caseEntryId、configurationId、repeatIndex、caseId 与请求配置。
3. 比较原始计划、冻结实验用例、expanded 用例及批次 inputs；使用规范化 JSON 比较，区分布尔与数字、整数与浮点数，拒绝错配、非法路径和不一致输入。
4. 复用既有批次预检，重新 inspect / 评测已执行项，核对输入、身份、路由和退出事实。只将正常完成且复核一致的 passed / failed 标为复用；完整结果已保存但 checkpoint 落后时允许恢复完成事实。
5. 未开始项保持 source / outcome / caseRunId 为空；未知执行或坏录制阻断整个拟续跑，原 stop 失败策略和领取限制继续生效。

预检不重新读取 sourceManifest 指向的原始输入位置。旧输入后续改变不影响已冻结的本实验；冻结计划或展开内容改变则拒绝。

## 预检输出

counts 提供 original / reused / newSamples / blocked。samples 保留全部原位置身份和 sourceStatus，disposition 为 reuse / pending / blocked；复用项保留实际 caseRunId、来源、结论、verification 与 recoveredCheckpoint，阻断项附 reason。failed 复用项仍是 failed，不能因工具成功或后续计划而改为 passed。

sourceExperimentResult / sourceExperimentId 和 sourceBatchResult / sourceBatchId 明确来源。planVerification 复核原实验输入；batchPlanFingerprint 是已有批次预检摘要；新 planFingerprint 版本 1 覆盖源实验和选定文件的原始字节 SHA-256、批次计划指纹、样本分类及新上限。sourceFilesSha256 展示实验层选定文件；批次层证据由 batchPlanFingerprint 覆盖。

摘要不是签名，也不是保存到磁盘的可执行计划；执行重读并比对同一摘要。新批次预留身份属于内部调度接口，普通独立 batch 不指定 batch_id 时保留原 UUID 行为。

## 执行协调与结果

执行从源批次取得内核锁后重新读取实验，复核全部输入 / 证据并比对实验摘要；阻断或摘要变化先于 UUID、输出及领取拒绝。锁保持到下游执行及结果写入结束。两个入口共用源批次的 `.batch-resume-claim.json`，因此从 --resume-batch 或 --resume-experiment 领取后，另一个入口均不能再次启动同一源。

[058 修复](changes/2026-10-27-058-resume-lock-report-version.md) 后，原实验运行也在批次结束后继续持有同一锁，直到原实验完成样本关联、汇总和最终 checkpoint。此期间两个续跑入口的预检 / 执行均报告持锁，不提前领取。收尾异常会释放锁，磁盘上的 running 结果仍须按现有证据规则复核；不会自动补写成功状态。该协调范围由更新后的原调度器提供，已经启动的旧代码仍需等待其退出和目录稳定。

预检 / 执行仍要求 headless 与当前安装的插件版本匹配；离线报告只核对归档版本、冻结输入、证据和录制的内部一致性，允许本地插件升级后重新报告已有续跑结果。

实验层创建新续跑目录并保存 running 结果，预留一个批次续跑 UUID 和结果路径，再调用共用的批次续跑执行核心。该核心以排他创建方式写入源批次领取记录，冻结明确未开始项并调用原 run_batch；新项保留 sampleId 作为 batch entryId，各自取得新的 caseRunId / 会话。已完成项只复用原事实；checkpoint 落后但完整评测可核对时不重复执行。

```text
runs/experiment-resumes/<resumeId>/
  resume-plan.json
  experiment-resume-result.json
  continuations/<batchResumeId>/
    resume-plan.json
    resume-result.json
    remaining.batch.json
    inputs/
    batches/<newBatchId>/
```

experiment-resume-result.json 保存源实验 / 批次身份、实验与批次摘要、maxSamples、counts、samplePlan、batchResumeResultPath、UTC 起止时间和调度 / 总体结论。samplePlan 是**启动时的分类与身份映射**，其中 pending 不会冒充最终状态；新执行状态与证据从显式下游结果读取。counts 的 reused / newSamples 同样是计划数。结果初始 outcome / newlyExecutedSummary 均为空，终态以同目录临时文件 replace 保存。

newlyExecutedSummary 仅来自新批次，不能把复用的历史调用量计作本次新增。下游批次续跑结果已有 combinedSummary，但它不是配置配对报告。总体 outcome 保留历史 failed，即使全部新任务 passed 也不改为 passed；中断 / 未知或无法评测仍为 unevaluable。原 experiment-result.json 的 samples / summary / groups 和原始证据均不回填或覆盖；源批次只新增领取记录。

## 连续续跑

把最近一轮的 experiment-resume-result.json 显式传给同一个入口。下面的 --run 会执行配置中的模型；无模型验证使用测试中的确定性适配器：

```powershell
$source = 'runs/experiment-resumes/<previousResumeId>/experiment-resume-result.json'
$plan = python -m dsh_eval --resume-experiment $source --plan --max-samples 4 | ConvertFrom-Json
# 核对退出码、eligibleForResume、counts、samples 和 reasons。
python -m dsh_eval --resume-experiment $source --run --max-samples 4 --expected-plan-sha256 $plan.planFingerprint.sha256 --runs-root runs/experiment-resumes
```

原实验输入仍使用预检 / 结果版本 1。已有续跑结果作为输入时，输出 experimentResumePlanFormatVersion=2、experimentResumeResultFormatVersion=2，planFingerprint.version=2；executionSupported=true。参数组合和退出码不变，输入错误仍使用公共版本 1 错误 JSON。必须显式选择最新结果，入口不扫描目录寻找后续轮次，也不清除旧领取记录。

新建批次续跑在启动 run_batch 之前保存 batchBinding={batchId,resultPath}，resultPath 固定为 batches/<reservedBatchId>/batch-result.json；batchResultPath 仍在完成后填写。绑定只表示预留身份，实际批次及其元信息必须已存在。原子结果写入前退出时，外层续跑可保留 running，预检通过显式绑定核对实际新批次，不将预留路径当作已执行事实。旧终态版本 1 续跑可沿已有 batchResultPath 继续；旧 running 续跑没有绑定时拒绝。

预检按显式 sourceResumeResult 反向读取祖先链，拒绝循环、重复身份、未来版本及超过 32 个续跑结果的链。随后按原批次到最近批次的顺序取得全部内核锁，重读并核对链未变；每一批都走原批次预检及 fresh inspect / evaluate。所有历史已完成项重新复核，完整评测已保存的落后 checkpoint 可恢复；只有最近批次中明确未开始的项可以进入新批次。历史损坏或未知项、原 stop 失败策略、清理不明、最近批次已有领取或没有剩余项均阻断。达到 32 个续跑结果后仍可报告，但不再新增一轮。

版本 2 计划保留全矩阵 samples、各样本实际 sourceBatchId / sourceBatchResult、counts、各批次完整 batchPlans，以及 sourceResumeResult / sourceResumeId、原实验身份和当前待续批次。maxSamples 只限制本轮未开始项。sourceFilesSha256 使用规范化绝对路径作键，覆盖祖先续跑结果 / 计划和全部批次元信息 / 冻结输入；各 batchPlans 的指纹另外覆盖其检查的证据。版本 2 摘要同时覆盖来源、上限、归档摘要、批次预检和完整样本分类，执行时在领取及 UUID / 输出之前重算比较。

执行持有全部祖先锁和新批次锁直到批次续跑与外层实验续跑的最终 checkpoint。新一轮只领取最近批次，历史目录不改写；每轮都有新的执行身份。结果保存 sourceResumeResult / sourceResumeId、全矩阵启动 samplePlan、下游显式路径、newlyExecutedSummary 和全矩阵 combinedSummary。即使最后新增项全通过，历史 failed 仍保留。收尾写入失败释放锁并保留 running，后续复核实际证据；不自动补写成功。

终态连续续跑结果可直接交给 --report，生成 comparisonReportFormatVersion=3 的 JSON / Markdown 和只读浏览。报告逐项重新复验原矩阵，reusedSummary 汇总本轮之前所有批次，newlyExecutedSummary 只含本轮新批次；batchIds / batchResultPaths 按时间顺序列出全部批次，resumeChain 列出全部续跑结果。配对仍按原用例 / 配置 / repeatIndex 与来源，不按执行轮次重新编号。

## 限制与后续

终态结果仍独立保存，不回填或冒充原终态实验。报告核对来源、领取、各层计划和下游批次，再按原矩阵逐项复验，区分历史复用与本次新增。命令和格式见 [配置报告](configuration-reports.md#实验续跑的跨批次报告)。[浏览器](result-browser.md) 支持版本 2 / 3 保存报告，不在浏览时重新复验。旧实验缺绑定、原目录搬迁、未知任务自动重试和模型会话恢复均未覆盖。原失败停止策略继续生效，不把 skipped 视为额外执行许可。

输出写入或进程中断可能留下 running 结果。若在领取之前中断，下游预留路径可能尚不存在；预留本身不表示执行，没有实际批次元信息就拒绝。领取后同一源不能重复启动，后续须显式选择最近一轮结果重新预检。内核锁和摘要不提供签名、多文件事务、fsync 或断电恢复保证。绝对归档路径要求保持有效；Windows 下宜使用较短的输出根，长路径行为没有全局兼容保证。

当前验证使用合成适配器、真实 Python / Node 子进程、状态化环境和录制检查，没有真实模型续跑验收。真实验收仍需单独确定配置和任务规模。
