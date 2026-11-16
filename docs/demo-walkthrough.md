# 从任务结论到原始证据的演示路线

本路线使用已有工作流、配置报告和规则预览，展示一个问题：最终文件和回复正确，是否足以证明任务满足了声明的执行要求？演示数据为固定合成任务，经过实际工具桥接、录制、inspect和评测，不调用模型。真实模型与合成路径的职责见[架构总览](design-overview.md)，历史问题另见[工程案例](engineering-case-studies.md)。

## 提前生成，再只读展示

需要Windows、Python3.12+和Node.js22.8+；下面的保存输出脚本使用PowerShell7.4+（`pwsh`），在仓库根目录运行。PowerShell从7.4起对原生命令stdout重定向保留原始字节；Windows PowerShell5.1的`>`不会原样保存这里的UTF-8 JSON，不能照搬保存命令。这个要求针对下面的重定向写法，Python生成与浏览入口本身不依赖PowerShell版本。依据见[PowerShell原生命令重定向说明](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_redirection?view=powershell-7.5#redirecting-output-from-native-commands)。

生成与离线复验应在展示前完成，展示时只启动已有结果的浏览服务。每次选择新输出目录：

```powershell
if ($PSVersionTable.PSVersion -lt [version]"7.4") { throw "Use PowerShell 7.4 or newer (pwsh) for these commands." }
$demoRoot = "runs/demo-" + [guid]::NewGuid().ToString("N")
New-Item -ItemType Directory -Path $demoRoot | Out-Null
python -m dsh_eval.workflow_demo --generate-only --output-dir "$demoRoot/workflow" > "$demoRoot/workflow-output.json"
if ($LASTEXITCODE -ne 0) { throw "Workflow generation failed; inspect workflow-output.json" }

# 可选：需要展示跨实验门禁时再生成。
python -m dsh_eval.regression_demo --output-dir "$demoRoot/regression" > "$demoRoot/regression-output.json"
if ($LASTEXITCODE -ne 0) { throw "Regression generation failed; inspect regression-output.json" }

python -m dsh_eval --browse --cases-root "$demoRoot/workflow/inputs" --runs-root "$demoRoot"
```

终端会给出带令牌的本机URL，打开完整地址，保留终端。关闭网页不会停止服务，结束后在终端按Ctrl+C。重新启动时把`$demoRoot`设置为刚才生成的目录，不要重新执行生成命令覆盖已有叶目录，也不要复用上次服务的令牌URL。原生Python入口无npm批处理确认层。

所有输入和原证据在所选根内，因此可以从比较页面进入关联。CI仅下载的五文件包不满足这个条件，缺源时按钮不可用属于预期。不要为演示完整证据而把浏览根扩大到整个磁盘。

## 四个查看点

先选“工作流演示”，打开“可重复合成工作流演示”。索引有“1. 完整重试步骤”“2. 跳过中间读回”“3. 四样本规则影响”三个场景。主线从第二项开始，第一项留作正常对照。

| 查看点 | 实际页面与操作 | 应看到什么 | 说明的设计 |
| --- | --- | --- | --- |
| 1. 漏步评测 | 打开“2. 跳过中间读回”，查看三维结果和“断言原因与依赖” | execution=completed、recording=complete，但任务unevaluable；6项passed、4项insufficient_evidence；首个缺证步骤source-still-present | 执行结束、录制完整与行为满足分别判断；最终状态正确不会补齐缺失步骤 |
| 2. 原始事件 | 在retry的“实际观察”中打开结果事件，再返回详情 | 重试确实成功，但直接前置target-still-missing未通过，仍保留dependency_not_passed | 导航到事件不等于将事件算作通过证据；after是事后顺序约束，不驱动重试 |
| 3. 实验报告 | 切“配置报告”，打开该演示的报告，查看“结构化原因汇总” | 四个样本均passed；必需项无源头问题，诊断角色有1个final_text_mismatch，定位sample-000002 | 诊断失败可被看见，但不参与必需项任务门禁；分母与角色分别保存 |
| 4. 同轨迹规则变化 | 切“实验规则预览”，打开结果，在sample-000002展开answer | timeout-retry第1轮的原文是`**done**`；answer始终为必需项，仅删除match改为精确`done`后失败；汇总1项passToFail、3项unchangedPassed | 同一轨迹、不同匹配规则，角色保持；不修改原回复、冻结用例或原评测 |

第3、4点的四样本来自独立实验，不是第1点漏步任务的四次重跑。规则预览中的`answer`是可展开条目；“仅看变化”按钮属于另一种“断言对照”页面，不在此处。事件按钮上的seq来自实际结果；每次生成身份会变化，使用页面核准的runId / sessionId / seq，不手工拼接旧事件位置。

漏步直接依赖链为：`source-still-present → target-still-missing → retry → verify`。首项是`tool_evidence_missing`，后三项是`dependency_not_passed`。retry和verify存在观察到的成功事件，也不能绕过未满足的前置；不会据此推断模型为什么漏步。

## 跨实验门禁作为扩展

如已生成可选数据，切“基线回归比较”，分别打开no-regression.json、regression.json和incomplete.json：

| 文件 | 原退出码 | 覆盖 | 关键结论 |
| --- | --- | --- | --- |
| no-regression.json | 0 | 2/2 | 无退化 |
| regression.json | 1 | 2/2 | 1项退化；可打开基线 / 候选各自原评测、证据和轨迹 |
| incomplete.json | 2 | 1/2 | 保留1项已确认退化和1项不可用；覆盖不足优先 |

这里比较两份独立实验；上一节规则预览是在同一轨迹上换规则。浏览显示的“比较时复验值”来自生成比较文件时的复验，打开原评测显示来源保存值，浏览本身不会再次评分。演示包装命令退出0只表示三个预设场景符合预期，真实门禁仍需保留比较CLI的0 / 1 / 2。详见[基线比较](baseline-regression.md)。

## 展示前检查与替代路径

确认本机URL可以打开、分类正确、原证据按钮可用；关闭其他输出根的旧标签页。先查看source=synthetic和modelCalled=false，再说明生成器模拟了工具序列，真实路径才由模型决定调用。

如果浏览服务或页面不可用，使用文本编辑器依次打开`workflow/workflow-index.json`，沿其中的evaluationPath、reportPath、previewPath查看同一套保存结果。不要在展示中重新跑真实模型或临时改规则“修好”失败，也不把只读JSON检查称作前端交互验收。

本次命令与数据核对、HTTP / API范围和限制记录在[141](changes/2026-11-16-141-design-walkthrough.md)。历史页面交互验收仍按[137](changes/2026-11-11-137-baseline-regression-browser.md)保留，摘要网页渲染继续未验证。
