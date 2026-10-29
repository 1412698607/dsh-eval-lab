# 双配置八任务比较

更新：2026 年 10 月 29 日，Asia/Shanghai。047 / 048 完成模板和无模型回归，050 首次真实计划按失败停止，065 另建 continue 实验完成两用例 / 两配置 / 两轮共八项实际执行。均复用现有 experiment / batch / runner / report，没有新增调度器或数据格式；原模板保持未填写 / stop 策略。

2026 年 10 月 26 日首次真实比较单列于 [050](changes/2026-10-26-050-external-model-providers.md)：DeepSeek Flash / 百炼 Qwen3.7-Plus，计划八项，实际第一轮四项中三通过、一失败，按 stop 策略跳过后四项。失败为恢复用例的最终值带 Markdown 反引号，工具重试与正常结束均通过；四实际样本录制 complete、路由 matched、独立复核 verified，每用例仅一对。下文 047 / 048 合成历史保留，原模板仍未填写，不将本次描述为八项全部执行或模型优劣结论。

2026 年 10 月 29 日 [065](changes/2026-10-29-065-live-two-config-comparison.md) 使用新的输入副本和实验身份，将 failurePolicy 显式选为 continue，八项全部执行、七通过一失败。DeepSeek Flash 为四通过，Qwen3.7-Plus 为三通过一失败；两个用例各有两对 verified / matched / live 样本。065 没有续跑、改写或解除 050 的旧失败停止，旧结果不合并进新比较。

## 范围与待填写项

[比较模板](../fixtures/evaluation/core/guarded-comparison.experiment.template.json) 固定 direct-read / retry-once 两个版本 2 用例、baseline / candidate 两个配置、各两轮，共 8 个计划任务。顺序为每轮先 direct-read 的 baseline / candidate，再 retry-once 的 baseline / candidate。failurePolicy=stop；每项独立环境、home、会话和故障状态，timeoutSeconds=120。

baseline 沿用 deepseek-official / deepseek-flash；candidate 的 provider / model 为 null，表示尚未选择。原模板不能直接预览或执行：现有配置校验会拒绝空值，并在创建运行身份 / 目录和启动子进程前退出。null 是待填写模板内容，不是有效实验格式的新可选值。只换 configurationId 而保留同一 configRef 时，报告不会将它们当成两套配置。

任务数不等于模型调用数，8 不是 token / 费用上限。失败停止可能只执行部分任务，跳过项仍保留在八任务计划中。预览不验证 provider 可用性、凭据、宿主安装或模型行为。

## 无模型验证（047 / 048）

在项目根目录运行：

```powershell
python -m unittest discover -s test -p test_guarded_comparison.py -v
```

测试只在临时目录填入 synthetic / baseline 与 synthetic / candidate，并用既有 Node 合成适配器、真实 Python 桥接、录制器和 inspect 运行八任务。宿主安装被替换，未接 Harness 或真实模型。原运行检查完成后，再统一证据、逐任务评测、批次 / 实验样本及实验 / 分组摘要中的来源；尝试项为 synthetic，跳过项仍为 null、摘要计为 unknown，然后生成独立报告。批次本身没有摘要字段。

六项回归覆盖：原始模板两配置声明和全部 / 部分未填写时启动前拒绝；八任务顺序 / 上限 / 第二配置变更指纹；成功 / 停止两类归档来源一致；按同用例 / 同轮次配对；路由声明不符、来源冲突和损坏录制只排除对应配对；首项失败后保留 1 attempted / 7 skipped 和四组各 2 的分母。

正常合成报告的计划 verified、8 个样本 verified / matched / synthetic，四个用例配置组、两个比较各含两对。测试人为指定 elapsedSeconds，以验证直接读取均值差 2、恢复用例均值差 5 的计算；这些是确定性输入，不能当作实测速度。未报告的 totalTokens / cost 保持缺失，不能补零。来源冲突负例中故意写入 live 声明，复核拒绝归属，不构成真实模型证据。

## 选择配置与预览

2026 年 10 月 26 日增加 [外部模型路由支持 050](changes/2026-10-26-050-external-model-providers.md)。保留原待填写模板；选择百炼等外部端点时，在复制出的两个用例中添加相同 modelProviders 路由声明，并将 candidate.configRef 的 provider / model 改为对应路由名 / 模型 id。凭据值只放在本机凭据库的 refs 分节，apiKeyEnv 填名称。百炼使用控制台的 **OpenAI 兼容地址**（包含 /compatible-mode/v1），不是 API Host 或原生 DashScope 地址。先对一个复制用例执行 `npm.cmd run check:model-providers -- <case.json>`，再预览；本地检查不调用模型或验证远端端点。

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

核对 valid=true、counts=2 / 2 / 8、maxSamples=8、显式失败策略、实际候选配置和八行顺序。原模板为 stop；若新实验要完整观察两轮，即使普通断言失败仍继续，可在新副本中明确选择 continue，并重新预览，因为策略纳入计划指纹。清理不明、用户中断及调度异常仍停止。真正运行使用相同 cap / 指纹和短绝对输出根；047 准备批次没有执行这一步，065 的实际范围见下文。

## 065 完整八任务真实比较

065 保留两个公开用例的提示、环境、预算和精确断言，只在新的忽略目录添加相同百炼 modelProviders 路由。配置为 baseline=deepseek-official / deepseek-flash、candidate=bailian / qwen3.7-plus，headless / 插件 0.1.2，两轮，每项 timeoutSeconds=120；本次新清单 failurePolicy=continue。不设置 stop-after，完整计划上限为 8。业务端点和密钥不加入公开输入；apiKeyEnv 使用凭据引用名称。

按上文建立并填写新的输入目录后，将其 experimentName 设为新的名称、failurePolicy 设为 continue。以下是本轮 CLI 的可移植入口，--run 会实际调用模型；示例目录必须先准备完成：

```powershell
$manifest = 'runs/c65-input/experiment.json'
$plan = python -m dsh_eval --experiment $manifest --plan --max-samples 8 | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or $plan.counts.samples -ne 8 -or $plan.failurePolicy -ne 'continue') { throw 'Comparison plan rejected' }
$result = python -m dsh_eval --experiment $manifest --run --max-samples 8 --expected-plan-sha256 $plan.planFingerprint.sha256 --runs-root C:/r | ConvertFrom-Json
if ($LASTEXITCODE -notin @(0, 1) -or $result.status -ne 'completed' -or $result.summary.attempted -ne 8) { throw 'Comparison incomplete; preserve saved results' }
$source = Join-Path $result.experimentDirectory 'experiment-result.json'
python -m dsh_eval --report $source
```

本次实验 e6c91da0-2617-40af-b80f-7aefa08b6fd5 为 completed / failed，CLI 退出 1；planned / attempted / finished 均 8、skipped / errors 均 0。报告 8ede9309-48b7-419e-b3cc-b42653521cae 退出 0，plan verified，八项全部 verified / matched / live，changedFields 全空。普通任务失败仍作为可评测样本进入配对。

| 用例 | DeepSeek Flash 通过 | Qwen3.7-Plus 通过 | 实际配对 / 计划 | 排除 |
| --- | ---: | ---: | ---: | ---: |
| direct-read | 2 / 2 | 1 / 2 | 2 / 2 | 0 |
| retry-once | 2 / 2 | 2 / 2 | 2 / 2 | 0 |

唯一失败是 sample-000006，Qwen 的 direct-read 第二轮返回 `**core-direct**`，工具读取及正常结束均通过，final_text 因要求纯文本 `core-direct` 而失败。没有移除 Markdown 标记、改弱断言或重跑替换样本。总体通过 7 / 8、可评测覆盖 8 / 8；这些是当前八项的分母，不是模型总体成功率。

本次记录 26 个已结算模型事件、18 次工具调用、totalTokens=168061，费用八项均缺失。153 份本轮选定归档、三份输入及 96 份历史 050 输入 / 归档文件摘要不变；八个专用 CLI PID 均已退出。只读浏览读取层可访问 80 份文档及八份轨迹 / 238 行，未追加页面点击验收。逐项与逐配置用量、耗时和条件配对差值见 065；固定顺序、每用例仅两对及厂商 usage / 缓存口径限制了跨配置解释，不推断优胜、费用或性能改善。

## 报告验收与边界

以后真实运行结束后，对返回的 experiment-result.json 使用现有 --report 独立复验。检查 planVerification、各项 verification / configurationMatch / source，以及执行、录制、断言三个结果。每个用例只能按同轮次、同来源、实际配置匹配的样本成对；两用例不能合并成四对来掩盖任务差异。

路由不符、来源冲突、坏录制、失败、跳过与缺失均公开。计划 verified 不代表任务 passed；少量配对、固定顺序和缺失覆盖不能推断配置优胜、总体成功率、显著性或费用 / 性能改善。047 / 048 完成时真实证据只有既有单配置验收，其合成结果不扩大该范围；050 部分执行与 065 完整八项分别保留，不跨实验拼接样本或配对。

格式和统计规则见 [实验说明](experiments.md)、[配置报告](configuration-reports.md)，原始交付见 [记录 047](changes/2026-10-25-047-guarded-comparison-preparation.md)，来源修正与模板回归加固见 [复审 048](changes/2026-10-25-048-comparison-source-review.md)。047 的旧结果和记录保留，不把原始归档标记不一致写成实际模型调用。
