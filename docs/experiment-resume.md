# 实验级续跑预检

更新：2026 年 10 月 27 日，Asia/Shanghai。当前仅实现 `--resume-experiment --plan`，读取并复核保存的实验 / 批次 / 单项证据，输出样本的复用、未开始或阻断分类。**实验续跑执行与报告汇总整合尚未实现。** 实现与验证见 [054](changes/2026-10-27-054-experiment-resume-preflight.md)。

## 入口与返回值

```powershell
python -m dsh_eval --resume-experiment 'runs/experiments/<experimentId>/experiment-result.json' --plan --max-samples 6
```

API 为 `plan_experiment_resume(result_path, *, max_samples=None)`。--max-samples 限制拟执行的未开始样本数，不包括可复用项；原实验的 maxSamples 及原指纹仍按原计划独立复核。两种上限都不是模型调用 / token / 费用预算。

预检不安装宿主、不创建身份 / 输出目录、不写领取文件、不修改旧实验、输入或报告。允许原 evaluator 调用 Node inspect 读取录制，并使用已有批次内核锁协调；锁文件需可读写，内容不变。

成功 JSON 为 experimentResumePlanFormatVersion=1、valid=true、modelCalled=false、executionSupported=false。eligibleForResume 仅表示证据和调度规则允许拟续跑，不表示已有可调用的实验执行入口。结构有效且可拟续跑时退出 0；存在未知项、原停止策略、重复领取或无剩余项时退出 2，仍为 valid=true。缺少绑定、输入冲突、源批次不可用 / 持锁或参数错误返回 2，输入错误 JSON 为 valid=false。

`--resume-experiment --run` 及未指定 --plan 的调用由参数解析直接拒绝，不读取证据或启动任务。--runs-root / --host-modules / --cancel-after-stream / --output / --evidence / --reports-root 等执行或输出控制不可用于预检。计划仅打印 stdout，不自动保存文件。

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

## 输出与边界

counts 提供 original / reused / newSamples / blocked。samples 保留全部原位置身份和 sourceStatus，disposition 为 reuse / pending / blocked；复用项保留实际 caseRunId、来源、结论、verification 与 recoveredCheckpoint，阻断项附 reason。failed 复用项仍是 failed，不能因工具成功或后续计划而改为 passed。

sourceExperimentResult / sourceExperimentId 和 sourceBatchResult / sourceBatchId 明确来源。planVerification 复核原实验输入；batchPlanFingerprint 是已有批次预检摘要；新 planFingerprint 版本 1 覆盖源实验和选定文件的原始字节 SHA-256、批次计划指纹、样本分类及新上限。sourceFilesSha256 展示实验层选定文件；批次层证据由 batchPlanFingerprint 覆盖。

摘要不是可执行冻结计划或签名。缺少显式绑定的旧实验、目录搬迁、跨实验合并、未知任务自动重试、实验结果回填和浏览器索引均未覆盖。新批次预留身份属于内部调度接口，普通独立 batch 不指定 batch_id 时保留原 UUID 行为。

当前验证使用合成适配器、真实 Python / Node 子进程及录制检查，不代表真实模型续跑验收。后续实现执行入口时仍需重新复核、单次领取保护、区分历史复用与新增用量，并单独进行真实验收。
