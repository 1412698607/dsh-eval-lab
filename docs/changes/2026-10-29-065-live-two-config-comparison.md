# 修改记录 065 新双配置完整八任务比较

日期：2026 年 10 月 29 日，Asia/Shanghai。类型：配置 / 验收 / 文档。插件版本：`0.1.2`。相关 Git 提交：本批尚未提交；已核实起始 HEAD 为 `3f229262a38b1a9229a01b2f90377ced075e09e6`，063 实现及 064 验收文档仍在工作区。本批没有修改生产代码、测试、公共模板、提示、断言或数据格式，没有提交 / 推送或新云端 CI。

## 问题与目标

050 首次双配置比较因普通任务失败，按原 stop 策略只执行四项、跳过后四项，每用例只有第一轮一对。064 已完成单配置连续续跑，但不提供跨配置比较。本批创建新实验身份，以同一组公开用例和既有两套真实模型配置执行完整两轮，保留普通断言失败，并独立验证每用例两对样本的来源、路由、分母和指标。

## 文件修改

| 文件 | 修改前 | 修改后 | 原因 |
| --- | --- | --- | --- |
| docs/guarded-comparison.md | 047 / 048 模板准备与 050 四项历史 | 增加 065 的新 continue 实验、可移植命令、失败与配对结果 | 区分完整八项执行、历史停止及任务通过 |
| README、docs/experiments.md、docs/core-evaluation.md、docs/architecture.md | 当前双配置状态仍主要指向部分执行 / 待定 | 同步两用例小批完成与完整十用例仍未扩大，不改变架构 | 避免将两用例结果扩大为整个固定集 |
| docs/progress.md、docs/plans/m6-reliability-validation.md | 新八任务比较待执行 | 当前小批范围完成，保留七通过一失败、来源及限制 | 不覆盖旧失败、跳过和历史验证 |
| CHANGELOG、本记录 | 缺少新比较范围和结果 | 记录 065 导航、技术取舍及实际命令 / 指标 | 公开资料可独立接续 |

新输入、具体业务端点、命令回执、原始任务内容和报告保存在忽略的运行目录，不作为公共固定配置提交。原比较模板仍为 candidate 空值及 failurePolicy=stop，原始 050 输入和结果不覆盖或续跑。

## 实现与技术取舍

使用 baseline=deepseek-official / deepseek-flash、candidate=bailian / qwen3.7-plus；headless、插件 0.1.2，direct-read / retry-once 两用例各两轮，共八项，每项 timeoutSeconds=120。复制后的用例除添加相同 modelProviders 外，与公开版本按 JSON 内容核对一致；提示、环境、工具故障和精确最终文本断言保持原样。端点、模型目录和凭据引用沿用既有本机配置，密钥仍由凭据服务解析，没有复制密钥或导入原 profile。

为观察完整两轮，在新的实验清单中显式选择 failurePolicy=continue，并设置新 experimentName。普通断言失败保留后继续后项；清理不明、用户中断和调度异常仍按原内核停止。该策略只影响新实验，不解除原 050 的 stop，也不重试其失败任务或清除领取。策略包含在完整计划指纹中；--plan 与 --run 都使用 maxSamples=8，运行带 fresh expected SHA，不设置 stop-after。八任务上限和模型容量声明不限制实际模型请求数、token 或费用。

输入和执行格式、展开顺序仍为 repeat-case-configuration。两个用例分别按相同 repeatIndex、live 来源及 matched 实际配置配对；普通任务失败不是排除配对的理由。报告同时保留八项分母、四组用例 / 配置结果及各指标覆盖，不将缺失费用补为零。

## 验证

环境：Windows、Python `3.12.0`、Node.js `v24.14.0`、CLI / SessionStore `0.2.0-rc.2`、Cordis `4.0.4`。八项均为真实模型任务；无模型回归和注册检查分别记录。实际业务端点不写入公共资料，公开命令使用准备好的新目录和短输出根示例。

| 命令或操作 | 实际结果 | 证明的范围 |
| --- | --- | --- |
| `python -m unittest discover -s test -p test_guarded_comparison.py -v` | 六项 / 10.646 秒，OK | 无模型计划、顺序、模板拒绝、来源 / 路由 / 损坏排除、配对及停止分母；不是模型结果 |
| 对新副本核对用例、路由及八项矩阵 | 两用例除相同 modelProviders 外与公开基准一致；2 用例 / 2 配置 / 2 轮，continue，三份新输入 | 不修改提示或断言以影响通过结论 |
| `npm.cmd run check:model-providers -- <new-input>/direct-read.case.json` | 退出 0，registrationVerified=true、credentialsPresent=true、endpointVerified=false、modelCalled=false | 本机真实 pi-ai / 凭据组件可注册百炼目录；不发起生成或远端发现 |
| 同一真实凭据服务分别 describe 两个引用 | DEEPSEEK_API_KEY / DASHSCOPE_API_KEY 均 configured=true，启动环境均未含对应值 | 仅确认本机存在性，不输出密钥值 |
| `python -m dsh_eval --experiment <new-input>/experiment.json --plan --max-samples 8` | 退出 0，valid=true / modelCalled=false；counts=2 / 2 / 8，continue；顺序与八行身份匹配 | 完整输入 / 组合 / 任务数静态校验 |
| 同清单 `--run --max-samples 8 --expected-plan-sha256 <fresh SHA> --runs-root C:/r` | CLI 退出 1，status=completed、outcome=failed、stopReason=null；planned / attempted / finished=8，passed=7 / failed=1 / skipped=0 / errors=0 | 新身份的完整八项实际执行；普通失败没有阻止后两项 |
| `python -m dsh_eval --report <new-result>/experiment-result.json --reports-root <reports-root>` | 退出 0，报告版本 1，plan verified，八项 verified / matched / live，changedFields 全空 | 独立 fresh inspect、实际路由、执行 / 录制 / 断言复核；失败仍为 failed |
| 配对分母与算术独立核对 | 两个用例分别 plannedPairs=2 / pairedSamples=2 / excludedPairs=0，repeatIndices=[1,2]；用量 / 耗时均值差与逐项求和一致；费用每用例 paired=0 / missing=2 | 四组样本均保留，失败不删除，缺失费用不补零 |
| SHA-256 对照 | 新三份输入、153 份本轮选定归档、96 份历史 050 输入 / 归档及 064 的 147 份选定文件均不变 | 本轮报告 / 浏览不改原证据，050 的停止 / 跳过和 064 连续续跑历史保留；排除 home / pnpm-store / node_modules 安装缓存 |
| runtime / setup / run.json 与操作系统 PID 核对 | 八项准备进程退出、adapterExitCode=0、stdinWriterStopped=true；host childClosed=true / exitCode=0 / forceStopped=false；八份清单 sealed；八个专用 CLI PID 均不存在 | 八个专用任务正常清理；setup 中路由声明与实际冻结 case 一致，不扩张到任意外部工具进程 |
| ArtifactBrowser 读取层遍历报告、链接及完整分页轨迹 | 80 份文档、八份轨迹 / 238 行，无预览错误 | 当前真实归档可只读浏览，没有追加页面点击验收或新任务 |
| 当前修改 / 新增 Markdown、补丁、业务端点及跟踪检查 | 十四份文档 / 440 个本地链接存在且未被忽略，git diff --check 通过；实际业务端点及完整主机名在这些文档中无匹配，runs / private-notes / secrets 无已跟踪文件 | 包含工作区 063 / 064 文档的公开导航检查；不把端点检查当作任意字符串的秘密扫描 |

执行入口及新目录准备步骤见 [比较说明](../guarded-comparison.md#065-完整八任务真实比较)。本次计划指纹为 `15c6fa714173e560f4d5dd10790900eab314ab86b7eaa59f533ee1cee7e70387`；它覆盖本轮全部输入、端点 / 模型声明、策略和上限，不可作为其他输入的执行许可。新实验 ID 为 `e6c91da0-2617-40af-b80f-7aefa08b6fd5`，独立报告 ID 为 `8ede9309-48b7-419e-b3cc-b42653521cae`。

### 八项实际结果

| 样本 | 用例 / 配置 / 轮次 | 执行 / 录制 / 断言 | 已结算模型事件 | 工具调用 | totalTokens |
| --- | --- | --- | ---: | ---: | ---: |
| sample-000001 | direct-read / DeepSeek / 1 | completed / complete / passed | 3 | 2 | 19102 |
| sample-000002 | direct-read / Qwen / 1 | completed / complete / passed | 3 | 2 | 19531 |
| sample-000003 | retry-once / DeepSeek / 1 | completed / complete / passed | 4 | 3 | 25663 |
| sample-000004 | retry-once / Qwen / 1 | completed / complete / passed | 4 | 3 | 26221 |
| sample-000005 | direct-read / DeepSeek / 2 | completed / complete / passed | 2 | 1 | 12643 |
| sample-000006 | direct-read / Qwen / 2 | completed / complete / failed | 3 | 2 | 19545 |
| sample-000007 | retry-once / DeepSeek / 2 | completed / complete / passed | 3 | 2 | 19120 |
| sample-000008 | retry-once / Qwen / 2 | completed / complete / passed | 4 | 3 | 26236 |
| 合计 | 八项实际、无跳过 | 七通过 / 一失败 | 26 | 18 | 168061 |

sample-000006 的读取工具和正常结束断言通过，唯一失败为 final_text：预期纯文本 `core-direct`，实际为 `**core-direct**`。没有移除 Markdown 加粗标记、修改断言、重写答案或重跑替换样本。整体 evaluablePassRate=7/8、attemptedPassRate=7/8、evaluableCoverage=8/8；八个 caseRunId / runId / sessionId 分别唯一。

### 逐配置与逐用例配对描述

| 配置 | 尝试 / 计划 | 通过 / 失败 | 已结算模型事件 | 工具调用 | totalTokens | elapsedSeconds 合计 |
| --- | ---: | --- | ---: | ---: | ---: | ---: |
| DeepSeek Flash | 4 / 4 | 4 / 0 | 12 | 8 | 76528 | 23.827 |
| Qwen3.7-Plus | 4 / 4 | 3 / 1 | 14 | 10 | 91533 | 36.735 |

| 用例 | 配对 / 计划 | DeepSeek 通过 | Qwen 通过 | Qwen 减 DeepSeek 的通过比例差 | totalTokens 配对均值差 | elapsedSeconds 配对均值差 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| direct-read | 2 / 2 | 2 / 2 | 1 / 2 | -0.5 | 3665.5 | 2.836 |
| retry-once | 2 / 2 | 2 / 2 | 2 / 2 | 0 | 3837 | 3.618 |

差值为同用例 / 同轮次 / live / matched 子集的描述值，失败样本仍参与；不把两用例合并成统一四对效果结论。inputTokens 总计 41270、outputTokens=1095，totalTokens 使用各厂商实际报告 usage，不由 input + output 补造。厂商 usage / 缓存计数可能存在口径差异。八项 elapsedSeconds 合计 60.562 秒，含准备 / 执行 / 清理，不是纯模型延迟或全验收流程耗时；费用八项均缺失，成本差值保持 null。

## 风险与后续

本批仅验证当前 Windows / 宿主版本、两套显式路由、两用例各两轮。八项全部执行不代表八项全部通过；verified / matched / complete 也不替代任务断言。固定顺序、每用例仅两对和不同厂商的 usage 口径不支持模型总体优劣、显著性、因果或成本 / 性能改善结论。Qwen 模型别名和远端实际版本仍不由本地声明独立认证。

050 的四项实际 / 四项跳过、064 的单配置六任务及各自原失败 / 限制保持原样，不跨实验合并配对。扩大完整十用例、增加重复或新增输出格式指标需另定范围；本批不改弱当前 final_text，以免把历史失败改成通过。未知执行、清理不明和原 stop 失败继续按既有规则阻断。

本轮仅运行六项相关无模型回归，没有重跑完整 Python / Node 套件；063 的完整回归属于历史结果。本批未改生产代码、公开模板、测试或格式，未提交 / 推送，也未新增云端 CI。

## 文档同步

同步 README、比较 / 实验 / 固定集说明、架构中的验收状态、当前进度、M6 顺序及 CHANGELOG。公开文档只链接可提交资料；实际路由业务空间、密钥、原始任务内容与运行 / 安装产物均不加入版本管理。原 047 / 048 / 050 / 063 / 064 修改记录保持原样。
