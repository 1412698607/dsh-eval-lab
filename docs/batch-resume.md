# 批次级安全续跑

更新：2026 年 10 月 31 日，Asia/Shanghai。首版复用既有 batch / runner / evaluate / inspect，仅对明确未开始的项创建新批次；原批次结果、输入和已执行任务不覆盖。[052](changes/2026-10-26-052-safe-batch-resume.md) 的首版验收为合成任务与真实子进程检查；[064](changes/2026-10-29-064-live-continuation-acceptance.md) 已通过实验连续续跑验收共用批次核心，没有额外执行独立 --resume-batch CLI 的真实模型任务。领取前的 Windows 路径保护见 [062](changes/2026-10-29-062-resume-output-path-guard.md)。

## 入口

对新调度器创建、包含 resumeSupportVersion=1 与 inputFingerprint 的批次，先预览：

```powershell
$source = 'runs/batches/<batchId>/batch-result.json'
$plan = python -m dsh_eval --resume-batch $source --plan --max-samples 2 | ConvertFrom-Json
$plan.counts
$plan.canResume
$plan.blockedEntries
$plan.reasons
```

预览会重新读取冻结输入、复核已执行任务并调用 Node inspect，不安装宿主或调用模型，不分配身份、不创建输出文件。它需要对原批次的已有锁文件取得独占锁，因此锁文件需可读写；文件内容不变。可执行计划退出 0；结构有效但存在阻断 / 无剩余任务时退出 2、valid=true、canResume=false；输入错误时退出 2、valid=false。modelCalled 始终 false。

确需执行时，带入同一任务上限和摘要。以下命令可能调用配置的真实模型：

```powershell
python -m dsh_eval --resume-batch $source --run --max-samples 2 --expected-plan-sha256 $plan.planFingerprint.sha256 --runs-root runs/resumes
```

--max-samples 在此限制**本次待执行的新任务数**，不包含复用项；不是模型调用、token 或费用上限。--expected-plan-sha256 为执行必需参数，必须是 64 位十六进制。执行时先重新锁定 / 复核 / 比对，再创建身份、领取续跑资格和输出；变化或阻断先于任务启动拒绝。--host-modules / --cancel-after-stream 沿用原 runner；不接受 --evidence / --output，也不能与其他选择入口组合。

API 为 `plan_batch_resume(result_path, *, max_samples=None)` 和 `resume_batch(result_path, runs_root=None, modules_dir=None, cancel_after_stream=False, *, max_samples=None, expected_plan_sha256=None, stop_after=None, stop_after_tokens=None)`，位于 dsh_eval/resume.py。

Windows 执行还会在领取之前检查实际输出根：为 resumeId / batchId / caseRunId 预留 UUID 长度，并计算到宿主安装临时目录 operation-XXXXXX 的完整路径，达到 248 个 UTF-16 单元即拒绝。报错返回退出 2，不创建身份 / 输出或领取文件，可以选用更短的绝对 `--runs-root` 后重新执行。`--plan` 不接收输出根，因此可续跑的源仍可能在执行时被路径保护拒绝；它也不保证宿主安装和远端模型可用。具体边界见 [Windows 输出根检查](experiment-resume.md#windows-输出根检查)。

## 判定与协调

`--stop-after-tokens N` 按本轮新批次报告的 totalTokens 停止后续调度；达到阈值或用量不可用时不启动下一项。结果保存 stopAfterTokens / tokenUsage，源阈值和历史用量不自动继承，复用项不进入本轮累计；该控制不进入预览指纹。下一轮仍须 fresh plan、单次领取和清理复核；它不能恢复未知执行或解除原失败策略，也不是任务内 token 硬限额，详见 [按已观测 token 停止调度](batch-runner.md#按已观测-token-停止调度)。

`--resume-batch --run` 可加 `--stop-after N`，只计算新批次中的尝试，复用项不计数。完整剩余清单仍冻结，maxSamples 检查不变；达到阈值后保存 stopAfter / stopReason 并保留无执行身份的 skipped 项，可显式选择下游新批次结果重新预检。该参数不解除原失败停止策略或单次领取，也不进入预览指纹。字段、优先级及退出码见 [任务边界停止](batch-runner.md#任务边界停止)。

| 源条目 / 调度状态 | 行为 |
| --- | --- |
| pending / skipped，所有执行身份、路径、指标及结论均为空 | 列为待执行；仍受原失败策略和其他阻断项约束 |
| finished，冻结输入一致、fresh inspect 完整、正常执行 / 退出、保存与新评测一致 | 复用 passed 或 failed 事实，不重复调用模型 |
| running，但完整 evaluation / evidence / runtime / 录制已保存且符合上述复核 | 恢复已完成事实，recoveredCheckpoint=true；不重复执行 |
| running 无完整证据、error、录制损坏、来源 / 身份 / 路径 / 配置冲突、清理未知 | 阻止整个续跑，不自动猜测是否调用过模型 |
| 原 stop 策略遇到失败，或 stopReason=failure_policy | 保留停止策略，不把 skipped 项当作新的执行许可 |
| 另一个调度器持锁 | 拒绝预览 / 执行 |
| 已存在续跑领取文件 | 阻止再次从同一源启动；新批次的后续中断应检查其自身结果 |
| 旧批次缺协调元信息 / 锁文件 | 拒绝，不补造历史支持声明 |

原批次首次执行持有 `.batch-execution.lock`，本地内核在进程退出后释放锁。源结果增加 resumeSupportVersion=1 和完整冻结清单 / 用例的版本化 inputFingerprint。续跑同时检查条目顺序、用例 / 路由、路径包含关系、身份和正常退出事实，保留已完成任务的精确断言结果。

若批次由实验创建，[058 修复](changes/2026-10-27-058-resume-lock-report-version.md) 后原实验会继续持有同一锁，覆盖批次返回后的关联 / 汇总及实验最终 checkpoint。即使 batch-result.json 已终态，原实验仍在收尾时，批次与实验续跑均拒绝进入。独立批次的锁生命周期不变；异常退出释放锁，后续仍须重新核对证据。

预览摘要版本 1 覆盖源结果路径、选定源文件的原始字节 SHA-256、待执行 / 复用条目身份及上限。因此源结果、冻结文件、评测、runtime 或录制的字节变化会使旧摘要失效，包括仅格式变化；不同于实验计划按解析后 JSON 计算的语义摘要。摘要不是签名，也不承诺多个文件的事务快照或对抗协调改写。

执行前在原目录以排他创建方式写 `.batch-resume-claim.json`，记录新 resumeId / 输出目录，保证同一源只领取一次。进程退出会释放内核锁，领取记录仍保留。若在领取后、创建新批次结果前中断，需人工检查新目录，首版不自动移除领取记录或重跑。这些步骤没有 fsync / 断电可靠保证。

## 输出与复核

[059](changes/2026-10-28-059-continuation-chains.md) 后，新批次续跑在启动前预留新批次 UUID 并保存 batchBinding，实际结果必须位于 batches/<reservedBatchId>/batch-result.json。预留不表示任务已执行，batchResultPath 仍在收尾后填写。新批次锁持有至批次续跑最终写入；由实验 / 连续续跑调用时延长至外层最终 checkpoint。实验层可显式选择已有续跑结果继续未开始项，纯批次报告入口范围保持不变。

```text
runs/resumes/<resumeId>/
  resume-plan.json             本次重新复核的计划与源文件摘要
  inputs/0001.case.json        仅待执行项的冻结副本
  remaining.batch.json        保留原 entryId 顺序和 failurePolicy
  resume-result.json          新续跑身份、源关联、复用项与新批次关联
  batches/<newBatchId>/        既有批次输出和新的 caseRunId / 会话
```

batchResumePlanFormatVersion / batchResumeResultFormatVersion 均为 1。计划显示 counts.original / reused / newSamples / blocked，及 canResume / blockedEntries / reasons。执行结果保留 sourceBatchResult、sourceBatchId、planFingerprint、reusedEntries、batchResultPath、UTC 起止时间及调度 / 总体结论。

newlyExecutedSummary 只统计新批次；combinedSummary 将复用事实与新批次按原 entryId 顺序汇总，指标包含复用任务的历史观察值，不能当成本次新增调用量。费用与跳过项仍保持缺失；历史 failed 不因后续新任务通过而变成 passed。resume-result.json 先保存 running，终态使用同目录临时文件 replace；中断可能留 running / 空 batchResultPath。

复用项路径相对 sourceBatchResult 所在目录；新批次路径相对 resumeDirectory。逐项离线复验继续使用原 case.json / evidence.json。不回填原实验的 summary / samples，纯批次 resume-result.json 仍不能交给 --report。054 / 055 已增加 [实验级安全续跑](experiment-resume.md) 的 --resume-experiment --plan / --run；两个入口共用源锁和领取记录。实验执行保存独立身份映射和新增摘要；056 允许终态 experiment-resume-result.json 生成版本 2 的跨批次报告，核对原实验及两个批次。纯批次续跑没有实验矩阵，不能套用该报告入口；当前浏览器已由 [057](changes/2026-10-27-057-resume-report-browser.md) 接入版本 2 报告与续跑关联。

目前只验证 Windows 当前组件与本地文件系统。锁是当前调度器的协作协议；不能约束绕开协议的程序，不提供原目录搬迁后的续跑保证，也不能恢复模型内部会话或确定性重放。原 050 比较因普通断言失败而停止，其历史结果与第二轮 skipped 保留。
