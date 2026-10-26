# 修改记录 050 外部模型路由与双配置真实验收

日期：2026 年 10 月 26 日，Asia/Shanghai。类型：功能 / 配置 / 测试 / 文档。插件版本：`0.1.2`。相关 Git 提交：尚未提交；起始基线为已核实的 `8f3bef2`。

## 问题与目标

已有实验可以声明不同的 provider / model，但单用例适配器只覆盖默认模型选择，不会为新隔离 profile 注册外部路由。因此外部配置需要显式、可冻结的端点、模型目录及凭据名称，不能仅替换 configRef 或依赖原用户 profile。

本批补齐该配置入口，并以现有两用例 / 两配置 / 两轮清单进行首次真实跨厂商验收。保留原始待填写模板及历史单配置结果；实际运行失败即停。

## 文件修改

| 文件 | 修改前 | 修改后 | 原因 |
| --- | --- | --- | --- |
| dsh_eval/formats.py | 用例不接受外部路由 | 可选 modelProviders，严格校验路由、HTTPS 端点、凭据名称和模型容量 | 在身份 / 输出 / 子进程创建前拒绝无效声明 |
| dsh_eval/experiment.py | 计划样本展示配置、预算及录制覆盖 | 声明存在时显示 modelProviders | 使预览可核对实际待配置路由；沿用完整输入指纹 |
| scripts/lib/model-providers.js、scripts/case-host.js | 仅选择默认模型 | 准备前再次校验，写入隔离 llm-pi-ai profile 与 setup.json | 直接 Node 入口与 Python 入口保持相同约束 |
| scripts/check-model-providers.js、package.json | 没有无模型外部路由检查 | check:model-providers 检查真实本机组件、目录及凭据存在性 | 在生成请求前分开验证本地接入；不发起生成 / 远端发现 |
| test/test_model_providers.py、test/case-recorder-config.test.js | 缺少外部路由覆盖 | 新增四 Python / 两 Node 回归 | 校验、秘密字段拒绝、冻结传递、指纹变化及启动前拒绝 |
| README、进度、架构、格式、实验、运行、比较与 M6 方案、CHANGELOG | 只有待填写比较和默认路由说明 | 同步配置入口、真实样本结果及边界 | 保留历史结果，明确本次失败和跳过 |

## 实现与技术取舍

modelProviders 是用例顶层的可选字典，caseFormatVersion 1 / 2 均可使用。每条路由只接受 api=openai-completions、baseURL、apiKeyEnv 和 models，模型条目只接受 id、contextWindow、maxTokens。容量为正安全整数；原生 DeepSeek 路由名保留。仅支持显式 HTTPS 文本端点，拒绝 URL 中的用户信息 / 查询串 / 片段和 apiKey / headers 等未支持字段。apiKeyEnv 是凭据名称，不是密钥值。

复用完整用例的加载、冻结与批次 / 实验展开，实验仍只替换 configRef。因此端点、凭据名称及模型目录自动纳入原有指纹和 plan-input.json；没有另设不受计划约束的环境配置文件，也没有新调度器或指纹版本。Node 将声明写入 llm-pi-ai 的 config.providers 和 setup.json.modelProviders；原用户 profile 不导入，密钥仍由原凭据服务按名解析。

没有使用任意宿主 patch 注入接口，避免在本批暴露与模型接入无关的插件配置面。当前字段是受限子集，尚不支持自定义请求头、推理档位或其他协议；旧严格读取器会拒绝新字段，旧用例不需迁移。路由声明和日志头均不构成远端模型版本的认证。

## 无模型验证

环境为 Windows、Node.js v24.14.0、Python 3.12.0、CLI / SessionStore 0.2.0-rc.2、Cordis 4.0.4。

| 命令或操作 | 结果 | 证明的范围 |
| --- | --- | --- |
| python -m unittest discover -s test -p test_model_providers.py -v | 首轮四项中两项因未知字段报错；实现后四项通过 | 两版本可选字段、不改写源对象、非法配置、创建身份前拒绝、指纹与冻结传递 |
| node --test --test-isolation=none test/case-recorder-config.test.js | 六项通过，含两项新增 | 实际 profile / setup 文件与声明一致；非法字段先于安装拒绝 |
| npm.cmd run check:model-providers -- runs/c50-input/direct-read.case.json | 退出 0；registrationVerified=true、credentialsPresent=true、endpointVerified=false、modelCalled=false | 真实本机 LLM / pi-ai / 凭据组件注册；不代表远端认证或任务成功 |
| 同一注册检查使用新的空 DSH_HOME、移除启动环境中的对应引用 | 退出 2；注册仍成功、credentialsPresent=false、modelCalled=false | 缺少本机凭据时保持未就绪，没有生成请求 |
| npm.cmd test | 初次沙箱 85 / 87 通过，两项 spawn EPERM；获准环境 87 / 87 通过、无跳过 | 原生 Web 子进程回归也已实际执行 |
| npm.cmd run test:python | 初次沙箱运行 234 项、五项进程操作错误；获准环境完整 253 项 / 65.445 秒通过 | 合成任务、离线复验、真实子进程监督等无模型回归 |
| npm.cmd run check | 43 份 JavaScript 语法通过 | 含两个新增脚本 |
| python -m compileall -q dsh_eval test | 退出 0 | Python 语法 |

初次沙箱错误保留为环境限制，没有替换成 mock 或计作产品通过。新增测试不调用真实模型。

## 首次双配置真实结果

在独立忽略目录复制原比较模板与 direct-read / retry-once，用两个用例相同的 modelProviders 声明注册 bailian 路由，使用百炼控制台提供的北京地域兼容端点。公开说明仅保留可移植端点示例，不包含业务空间标识或密钥。baseline 为 deepseek-official / deepseek-flash，candidate 为 bailian / qwen3.7-plus；headless、插件 0.1.2、两轮、timeoutSeconds=120、failurePolicy=stop。

实际命令：

```powershell
python -m dsh_eval --experiment runs/c50-input/experiment.json --plan --max-samples 8
python -m dsh_eval --experiment runs/c50-input/experiment.json --run --max-samples 8 --expected-plan-sha256 119a768bc7ce7050210de3479d00b7c3145f0575a35d6b65530e4240f290b92d --runs-root runs/c50
python -m dsh_eval --report runs/c50/5b438aeb-a446-4cc1-bfaf-e5b6174ad2f3/experiment-result.json
```

输入目录是本机准备产物，复现时按 [比较说明](../guarded-comparison.md) 从公开模板复制并填写自己的路由及凭据引用，重新取得摘要。上面的实际摘要只对应本次完整输入，不是其他业务空间或配置可复用的摘要。

实验 `5b438aeb-a446-4cc1-bfaf-e5b6174ad2f3` 于本地时间 19:04:45 至 19:05:15 执行，CLI 退出 1、status=stopped、outcome=failed、stopReason=failure_policy。planned=8、attempted=4、finished=4、skipped=4、errors=0；三项 passed，一项 failed，后四项未执行。

| 顺序 | 用例 / 配置 / 轮次 | 执行 / 录制 / 断言 | 已结算模型事件 | 工具调用 | totalTokens |
| --- | --- | --- | ---: | ---: | ---: |
| 1 | direct-read / baseline / 1 | completed / complete / passed | 3 | 2 | 22438 |
| 2 | direct-read / candidate / 1 | completed / complete / passed | 3 | 2 | 22779 |
| 3 | retry-once / baseline / 1 | completed / complete / passed | 3 | 2 | 22440 |
| 4 | retry-once / candidate / 1 | completed / complete / failed | 4 | 3 | 30652 |
| 合计 | 四个实际任务 | 三通过 / 一失败 | 13 | 9 | 98309 |

第四项工具失败、随后成功重试、步骤先后及正常结束断言全部通过。失败仅为 final_text：预期纯文本 core-retry，实际返回带一对 Markdown 反引号的同一值。保留原精确断言和模型答案，不移除反引号或重写输入以将历史失败变为通过。两种模型在直接读取中均通过；少量样本不足以判断总体优劣。

四项已报告 inputTokens 合计 31613、outputTokens=520、totalTokens=98309；totalTokens 使用原 usage，不以 input + output 补造。运行 elapsedSeconds 合计 30.079 秒，含准备 / 执行 / 清理，不是纯模型延迟。费用均缺失，跳过项仍未知。

## 独立复验与退出事实

离线报告 `44321a4c-4471-4f33-a8c1-fdeed74c17ac` 退出 0，planVerification=verified，四项实际样本均 verified / matched / live，changedFields 全空；任务结果仍三通过、一失败。四跳过项 verification=skipped、source=null、实际路由未知；报告既有逻辑对跳过项列出 metrics 字段差异，不意味着曾执行这些项。

每个用例有 plannedPairs=2、pairedSamples=1、excludedPairs=1，只有第一轮可配对；失败的实际样本仍保留在对应描述性比较中。整体 evaluablePassRate=3/4、attemptedPassRate=3/4、evaluableCoverage=4/8，不用跳过项补造零用量或八项全部执行的结论。

对实验内 88 份选定原始文件（排除 home / pnpm-store）在报告前后计算 SHA-256，全部不变。四份 runtime 的 childClosed=true、exitCode=0、forceStopped=false；四个专用 CLI PID 单独查询均不存在。录制完整、复核通过与任务断言通过分别记录，没有推定任意其他进程树已退出。

## 风险与后续

- 本批真实比较按失败停止，仅执行第一轮；不自动补跑第二轮、不追加智谱或扩大十用例。后续运行应使用新实验身份并保留本次失败。
- 仅验证当前 Windows / CLI / 两套显式配置；Qwen 的别名及远端实际版本不由本地目录声明独立证明。
- 单任务仍可多次调用模型，容量声明与八任务上限都不是 token / 费用硬限额；超时不约束准备 / 清理的总耗时。
- 路由字段校验拒绝常见密钥承载字段，但不是任意字符串的机密扫描。原始配置、运行日志及报告保存在忽略目录，不加入公开仓库。
- 未提交、推送或新增云端 CI；当前本地验证不继承旧提交的云端结论。

## 文档同步

同步 README、docs/progress.md、docs/architecture.md、docs/evaluation-format.md、docs/experiments.md、docs/single-case-runner.md、docs/guarded-comparison.md、docs/plans/m6-reliability-validation.md 和 CHANGELOG。历史验收保留，新模型失败和跳过范围在本记录单列。

链接检查发现既有 049 目标文件缺失；同轮 [049 补记](2026-10-26-049-public-documentation-record.md) 核对历史整理提交并修复导航，不补造历史测试结果。

修改 Markdown 的 354 个本地文件链接均可解析，git diff --check 通过；实际本机凭据值扫描本轮 19 份修改 / 新增文件，无匹配。runs / private-notes / secrets 无已跟踪文件，本次输入、原始实验和报告路径均命中忽略规则。
