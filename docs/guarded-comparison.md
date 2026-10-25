# 双配置八任务比较准备

更新：2026 年 10 月 25 日，Asia/Shanghai。本批完成模板和无模型回归，复用现有 experiment / batch / runner / report；没有执行第二套真实模型，也没有新增调度器或数据格式。

## 范围与待填写项

[比较模板](../fixtures/evaluation/core/guarded-comparison.experiment.template.json) 固定 direct-read / retry-once 两个版本 2 用例、baseline / candidate 两个配置、各两轮，共 8 个计划任务。顺序为每轮先 direct-read 的 baseline / candidate，再 retry-once 的 baseline / candidate。failurePolicy=stop；每项独立环境、home、会话和故障状态，timeoutSeconds=120。

baseline 沿用 deepseek-official / deepseek-flash；candidate 的 provider / model 为 null，表示尚未选择。原模板不能直接预览或执行：现有配置校验会拒绝空值，并在创建运行身份 / 目录和启动子进程前退出。null 是待填写模板内容，不是有效实验格式的新可选值。只换 configurationId 而保留同一 configRef 时，报告不会将它们当成两套配置。

任务数不等于模型调用数，8 不是 token / 费用上限。失败停止可能只执行部分任务，跳过项仍保留在八任务计划中。预览不验证 provider 可用性、凭据、宿主安装或模型行为。

## 无模型验证

在项目根目录运行：

```powershell
python -m unittest discover -s test -p test_guarded_comparison.py -v
```

测试只在临时目录填入 synthetic / baseline 与 synthetic / candidate，并用既有 Node 合成适配器、真实 Python 桥接、录制器和 inspect 运行八任务。宿主安装被替换，未接 Harness 或真实模型。原运行检查完成后，再统一证据、逐任务评测、批次 / 实验样本及实验 / 分组摘要中的来源；尝试项为 synthetic，跳过项仍为 null、摘要计为 unknown，然后生成独立报告。批次本身没有摘要字段。

六项回归覆盖：原始模板两配置声明和全部 / 部分未填写时启动前拒绝；八任务顺序 / 上限 / 第二配置变更指纹；成功 / 停止两类归档来源一致；按同用例 / 同轮次配对；路由声明不符、来源冲突和损坏录制只排除对应配对；首项失败后保留 1 attempted / 7 skipped 和四组各 2 的分母。

正常合成报告的计划 verified、8 个样本 verified / matched / synthetic，四个用例配置组、两个比较各含两对。测试人为指定 elapsedSeconds，以验证直接读取均值差 2、恢复用例均值差 5 的计算；这些是确定性输入，不能当作实测速度。未报告的 totalTokens / cost 保持缺失，不能补零。来源冲突负例中故意写入 live 声明，复核拒绝归属，不构成真实模型证据。

## 以后选定配置后的预览

保留原模板和用例，将三份文件复制到新的忽略目录；目录已存在时更换名称，不覆盖历史输入：

```powershell
$inputDir = 'runs/c47-input'
New-Item -ItemType Directory -Path $inputDir -ErrorAction Stop | Out-Null
Copy-Item 'fixtures/evaluation/core/guarded-comparison.experiment.template.json' "$inputDir/experiment.json"
Copy-Item 'fixtures/evaluation/core/direct-read.case.json', 'fixtures/evaluation/core/retry-once.case.json' $inputDir
```

编辑新目录中的 experiment.json，将 candidate 的两个 null 填成已选定的真实 provider / model；保持 headless / 插件版本匹配，不在清单中放密钥。用例放在清单旁边，保留相对路径。随后只预览：

```powershell
$plan = python -m dsh_eval --experiment "$inputDir/experiment.json" --plan --max-samples 8 | ConvertFrom-Json
$plan.counts
$plan.configurations
$plan.planFingerprint
```

核对 valid=true、counts=2 / 2 / 8、maxSamples=8、stop 策略、实际候选配置和八行顺序。真正运行仍需另行确定模型与任务规模，并把相同 cap / 指纹带入 --run；沿用 [四任务验收](guarded-acceptance.md) 的短输出根方法，避免已知宿主深目录准备限制。本批不执行这一步。

## 报告验收与边界

以后真实运行结束后，对返回的 experiment-result.json 使用现有 --report 独立复验。检查 planVerification、各项 verification / configurationMatch / source，以及执行、录制、断言三个结果。每个用例只能按同轮次、同来源、实际配置匹配的样本成对；两用例不能合并成四对来掩盖任务差异。

路由不符、来源冲突、坏录制、失败、跳过与缺失均公开。计划 verified 不代表任务 passed；少量配对、固定顺序和缺失覆盖不能推断配置优胜、总体成功率、显著性或费用 / 性能改善。当前真实证据仍只有既有单配置验收，本批合成结果不扩大其范围。

格式和统计规则见 [实验说明](experiments.md)、[配置报告](configuration-reports.md)，原始交付见 [记录 047](changes/2026-10-25-047-guarded-comparison-preparation.md)，来源修正与模板回归加固见 [复审 048](changes/2026-10-25-048-comparison-source-review.md)。047 的旧结果和记录保留，不把原始归档标记不一致写成实际模型调用。
