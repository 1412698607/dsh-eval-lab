# 修改记录 064 六任务真实连续续跑验收

日期：2026 年 10 月 29 日，Asia/Shanghai。类型：验收 / 文档。插件版本：`0.1.2`。相关 Git 提交：本批尚未提交；已核实起始 HEAD 为 `3f229262a38b1a9229a01b2f90377ced075e09e6`，063 的实现、测试与文档仍在工作区。本批没有修改生产代码、测试、输入清单、断言或格式，没有提交 / 推送或新云端 CI。

## 问题与目标

063 已通过任务边界停止的无模型回归、六任务合成续跑及真实宿主离线准备；尚未证明真实模型任务能在原实验与两轮续跑之间保持身份、来源、证据和报告分母一致。本批使用现有单配置六任务清单，通过实际 CLI 的 --stop-after 2 形成两次边界，再逐轮预检与执行，独立复验最终版本 3 报告。

## 文件修改

| 文件 | 修改前 | 修改后 | 原因 |
| --- | --- | --- | --- |
| docs/experiment-resume.md | 只有通用入口，当前验收为合成范围 | 补充可复现的六任务命令、实际结果和报告差异解释 | 区分合成、准备与真实任务证据 |
| README、docs/batch-runner.md、docs/experiments.md、docs/batch-resume.md | 六任务仍为候选 / 准备或无模型状态 | 链接独立真实验收，保留独立批次 CLI 的验证边界 | 当前状态与实际执行入口一致 |
| docs/progress.md、docs/plans/m6-reliability-validation.md | 真实连续续跑待验收 | 当前单配置六任务范围完成，下一批为新双配置比较 | 保留旧失败和未覆盖范围 |
| CHANGELOG、本记录 | 缺少本轮验收结果 | 增加 064 导航、命令 / 结果 / 指标与限制 | 可核对验收范围，不覆盖历史记录 |

## 实现与技术取舍

复用 [continuous-resume.experiment.json](../../fixtures/evaluation/core/continuous-resume.experiment.json)：direct-read / retry-once 两用例、deepseek-official / deepseek-flash、headless、各三轮，共六项，failurePolicy=stop。每项 timeoutSeconds=120，准备和清理另有期限，不是总退出或费用硬限额。没有修改提示、环境或精确断言。

三个执行命令均显式传 --stop-after 2，原实验 maxSamples=6，首次 / 第二次续跑分别为 4 / 2。每个命令使用刚取得的本轮计划摘要；不将历史预览摘要当作未来执行许可。输出使用通过 062 保护的短绝对根及普通路径，没有接入 Windows 扩展路径原型。每个任务仍建立独立工作区、home、会话和状态化故障计数，不复制密钥或修改原 profile。

原实验和首次续跑在完成、清理并保存两项后停止，后项 skipped / 空执行身份。第二次续跑执行最后两项，正常 completed / passed；原实验及首次续跑的 stopped / unevaluable 不回填。两次领取仍各写入对应源批次的新标记，原来已有文件不改写。

## 验证

环境：Windows、Python `3.12.0`、Node.js `v24.14.0`、CLI / SessionStore `0.2.0-rc.2`、Cordis `4.0.4`。无模型前置确认凭据 configured=true，只观察存在性、不输出凭据值；短根通过现有路径保护。实际参数和可复现命令见 [六任务真实验收入口](../experiment-resume.md#六任务真实验收入口)。

| 命令或操作 | 实际结果 | 证明的范围 |
| --- | --- | --- |
| `python -m dsh_eval --experiment fixtures/evaluation/core/continuous-resume.experiment.json --plan --max-samples 6` | 退出 0，valid=true、modelCalled=false，2 / 1 / 6；原指纹 df54bafd7a735d83b47fcca384ec4cc048031964d6e9e1761ac6ec3580579055 | 输入、规模与明确配置通过，尚未调用模型 |
| 同清单 `--run --max-samples 6 --stop-after 2 --expected-plan-sha256 <fresh SHA> --runs-root C:/r` | 退出 2，stopped / stop_after / unevaluable；planned=6、attempted=2、passed=2、skipped=4 | 两项真实任务成功后受控停止，四项无 caseRunId |
| `--resume-experiment <original result> --plan --max-samples 4` | 退出 0，版本 1，eligible=true；original=6 / reused=2 / newSamples=4 / blocked=0 | 实际原证据重读 / inspect 后允许续跑 |
| 同源 `--run --max-samples 4 --stop-after 2 --expected-plan-sha256 <fresh SHA> --runs-root C:/r` | 退出 2，stopped / stop_after / unevaluable；本次批次 planned=4、attempted=2、passed=2、skipped=2 | 仅执行第三 / 四项，不重复原两项；原 53 份选定文件摘要不变 |
| `--resume-experiment <first continuation> --plan --max-samples 2` | 退出 0，版本 2，eligible=true；original=6 / reused=4 / newSamples=2 / blocked=0 | 全部祖先和最近批次复核通过 |
| 同源 `--run --max-samples 2 --stop-after 2 --expected-plan-sha256 <fresh SHA> --runs-root C:/r` | 退出 0，completed / passed、stopReason=null；本轮两项 passed；combined planned / attempted / passed 均 6 | 最后两项实际执行，六个身份唯一；原有 102 份选定文件摘要不变 |
| `python -m dsh_eval --report <last continuation> --reports-root <reports root>` | 退出 0，报告版本 3；plan verified，六项 verified / matched / live；历史复用 4 / 本轮新增 2 | 重新 inspect、原矩阵和三个批次关联、实际请求路由及断言复验 |
| 对三份终态结果再执行 --plan（上限依次 4 / 2 / 2） | 均退出 2；原实验 / 首次续跑拒绝已有领取；末轮 reused=6 / newSamples=0，拒绝无剩余项 | 单次领取及无剩余项门禁保持；没有启动任务 |
| ArtifactBrowser 实际读取报告及其全部可访问链接 / 分页 | 76 份文档、6 份轨迹、174 行，无预览错误 | 服务读取层的真实归档浏览；未新增页面点击验收，没有模型调用或重新评测 |
| 逐任务 runtime / host / run.json 及操作系统 PID 核对 | 六项准备进程退出、adapterExitCode=0、stdinWriterStopped=true；host childClosed=true / exitCode=0 / forceStopped=false，六份运行清单 sealed；六个专用 CLI PID 均已不存在 | 当前六个专用任务的正常退出事实，不扩张到任意外部工具进程 |
| 报告、浏览及终态预检前后的 SHA-256 | 147 份选定归档文件全部不变 | 输入、元信息、结果、runtime、setup、原始直接输出及录制文件；不扫描安装 home / pnpm-store / node_modules 缓存 |
| 修改 / 新增 Markdown 链接及补丁 / 跟踪检查 | 十一份文档 / 415 个本地链接存在且未被忽略，git diff --check 通过；runs / private-notes / secrets 无已跟踪文件 | 包含先前 063 工作区文档的当前完整导航检查，运行产物保持隔离 |

命令表的 C:/r 为可移植短根示例，实际每项均使用全新 UUID 目录；所有 CLI stderr 为空。记录中任务数为本批实际任务数，不等于模型请求数。

首次附加审计曾要求 changedFields 全空，该断言不成立。逐字段核对确认六项仅有 configurationMatch：原批次行未保存该字段，报告重新核对原始请求路由后由 null 解析为 matched；source、configuration、三维结果、outcome 和 metrics 均无变化。报告命令始终退出 0，六项均 verified / matched / passed；未修改报告、源归档或产品逻辑以清空差异，也未重跑模型任务。

### 本轮身份与阶段结果

| 对象 | 实际身份 | 结果 |
| --- | --- | --- |
| 原实验 | e7f8aa78-49b6-4d48-b269-9c313538b86a | 两项通过后 stopped，保留四 skipped |
| 首次实验续跑 | c382ff00-b34c-4faf-b877-5c218a3e9208 | 复用两项、增加两项，保留两 skipped |
| 第二次实验续跑 | c6f54a3b-251b-4a71-87d9-d1a1a749580a | 复用四项、增加两项，completed / passed |
| 独立报告 | ebe08c86-76cf-4bbf-8f43-cc81e7315450 | 版本 3，三个批次 / 两个续跑结果，六项全量分母 |

首次续跑计划摘要为版本 1 / 08dfb449134306fb186be4e3250f9b522a9fe30263011f3a8275c61fb1f4a342；第二次为版本 2 / ac34d78915e75178aa17cca91f373c83d304feecbfabf5c65ecb120bb33d1053。这些是本次源归档的历史记录，已有领取后不能作为再次执行许可。

### 六项实际指标

| 样本 | 用例 / 重复 | 执行阶段 | 已结算模型事件 | 工具调用 | 已报告 totalTokens |
| --- | --- | --- | ---: | ---: | ---: |
| sample-000001 | direct-read / 1 | 原实验 | 2 | 1 | 12721 |
| sample-000002 | retry-once / 1 | 原实验 | 4 | 3 | 25648 |
| sample-000003 | direct-read / 2 | 首次续跑 | 2 | 1 | 12699 |
| sample-000004 | retry-once / 2 | 首次续跑 | 4 | 3 | 25718 |
| sample-000005 | direct-read / 3 | 第二次续跑 | 2 | 1 | 12691 |
| sample-000006 | retry-once / 3 | 第二次续跑 | 3 | 2 | 19221 |
| 合计 | 六项 completed / complete / passed | 三个独立批次 | 17 | 11 | 108698 |

最终报告的三项比例分子 / 分母均为 6 / 6，六个 caseRunId / runId / sessionId 各自唯一。inputTokens=37258、outputTokens=528，totalTokens 保留实际 usage 汇总，不按 input + output 补造。六项 elapsedSeconds 合计 33.736 秒，含准备 / 执行 / 清理，既不是纯模型延迟，也不是全部验收命令耗时；费用六项均缺失，保持 null。仅一个配置，comparisons 为空，未执行双配置比较。

## 风险与后续

本批只扩充当前 Windows / 宿主版本、单配置、两用例各三轮及受控任务边界的真实证据。063 的合成回归和 061 / 062 的深路径失败及保护历史保留；普通短根成功不证明通用长路径、任意崩溃恢复或其他平台兼容。未知执行、清理不明和原失败停止策略仍阻断，不恢复模型会话或回填原实验。

下一批双配置八任务比较需使用新实验身份、冻结实际配置并保留全部失败 / 跳过和配对分母；050 的失败停止批次继续保留。六项成功不能推断模型总体成功率、配置优胜、性能或费用改善。本批没有重跑完整代码回归，063 的 358 Python / 91 Node 为上一批结果，不记作本批通过；本次实际验证为上述真实任务、独立复验、静态浏览和文档检查。

## 文档同步

更新 README、实验 / 批次 / 续跑说明、进度、M6 顺序与 CHANGELOG。没有架构、数据格式、生产代码或运行参数变更，不调整版本。原始任务内容、具体本机路径、命令回执和摘要清单保存在本地运行目录，不加入版本管理；公开 Markdown 不链接运行日志、缓存、凭据或私人材料。历史 063 及更早记录保持原样。
