# 修改记录 071 四任务真实用量停止与连续续跑验收

日期：2026 年 11 月 1 日，Asia/Shanghai。类型：文档 / 真实验收。插件版本：`0.1.2`。已核实实现提交：`c7b627a755266276ae343c2ef397f2ea4f9d54aa`；本批未改生产代码、测试、协议或断言。

## 问题与目标

067 已通过合成轨迹验证 token 调度停止，069 补齐普通执行入口的 Windows 输出根预检。此前没有真实模型证据证明：完整四任务计划能因已观测 token 阈值停止，再经过两轮 fresh 预检续跑，最终独立报告仍保留原矩阵、来源及历史 / 新增用量。

本批使用已有 DeepSeek Flash 配置和两个公开用例各两轮，限定总共四项任务。先核实实现提交 CI 成功和短根离线准备，再按阈值 1 / 1 / 100000 执行，实际形成 1 / 1 / 2 三段；没有追加任务或重跑替换样本。

## 文件修改

| 文件 | 修改前 | 修改后 | 原因 |
| --- | --- | --- | --- |
| docs/experiment-resume.md | 只有任务数停止的真实连续续跑示例 | 增加四任务用量停止的输入构造、运行入口与实际结果 | 可从公开输入复现，原六任务历史保留 |
| README、docs/batch-runner.md、experiments.md、output-paths.md | token 停止为无模型验证，路径接受只有离线准备 | 链接独立真实验收及短根范围 | 区分代码、合成、离线准备与真实任务 |
| docs/progress.md、plans/m6-reliability-validation.md、CHANGELOG、本记录 | 尚无本批模型证据 | 补充本次任务数、来源、停止原因、用量与限制 | 不扩大到完整十用例或双配置比较 |

## 输入与技术取舍

- 从 guarded-acceptance.experiment.json 及其 direct-read / retry-once 两个用例构造全新输入副本，实验名为 observed-token-acceptance-20261101，failurePolicy 显式选择 continue。原 public 清单的 stop 策略不改写，两个用例的提示、环境、配置、预算和精确断言原样保留。
- 计划为两用例 / 一配置 / 两轮，maxSamples=4，原指纹 `d09a81002cd74a0b86a29bb2d8cbb111da0ce479b672f88d8d15068f7ca2d684`。每项 timeoutSeconds=120，准备 / 清理另计；任务数与 token 停止均不是费用或任务内硬限额。
- 三段均显式 stopAfter=2；前两段 stopAfterTokens=1，最后一段为 100000。原实验与首次续跑各新增一项便达到 token 阈值，末轮完成剩余两项。续跑各自重新预检，maxSamples 分别为 3 / 2，历史用量不计入本轮阈值。
- 使用通过预检的短绝对输出根和全新 UUID 目录，隔离 profile 沿用现有凭据引用。离线准备为实际 CLI `0.2.0-rc.2`，没有模型调用；真实任务再单独执行。实际原始输入和归档不加入 Git，公开说明使用可移植短根示例。

## 验证

下表列实际调用的 Python API / 操作；执行 API 通过既有适配器驱动真实 headless CLI，没有替换模型、录制器或评测器。

| 操作 | 实际结果 | 证明的范围 |
| --- | --- | --- |
| `plan_experiment(..., max_samples=4)` | valid=true、modelCalled=false，2 / 1 / 4，指纹如上 | 固定配置、完整矩阵与输入 |
| 两个独立四层 UUID 单项目录的 `prepare_workspace` / `_prepare` | 实际离线安装成功，CLI `0.2.0-rc.2`，processStarted / processExited 均 true，home / workspace 关联正确 | 当前短根下真实宿主准备，不是模型任务 |
| `run_experiment(..., max_samples=4, stop_after=2, stop_after_tokens=1, expected_plan_sha256=<fresh SHA>)` | stopped / stop_after_tokens / unevaluable；本轮 1 项 passed、3 skipped；观测 19063 token | token 阈值先于任务数阈值停止，剩余项未执行 |
| 原实验 fresh plan，`resume_experiment(..., max_samples=3, stop_after=2, stop_after_tokens=1, expected_plan_sha256=<fresh SHA>)` | stopped / stop_after_tokens / unevaluable；本轮 1 项 passed、2 skipped；观测 19206 token | 只执行第二项，历史第一项不计入本轮累计 |
| 首次续跑 fresh plan，`resume_experiment(..., max_samples=2, stop_after=2, stop_after_tokens=100000, expected_plan_sha256=<fresh SHA>)` | completed / passed，stopReason=null；本轮 2 项 passed，观测 38470 token | 完成原计划剩余项，不回填原实验 / 首次续跑状态 |
| `generate_report` 对最后续跑结果独立复验 | 版本 3；原计划 verified，四项 verified / matched / live；历史复用 2 / 本轮新增 2；comparisons 为空 | 完整四项均 passed，来源 / 路由 / 身份一致，只有单配置 |
| 报告前后、各轮续跑前后的 SHA-256 | 最终 115 份选定输入 / 来源文件摘要不变；另六份报告 / 复验文件读取前后不变；三个原公开输入摘要不变 | 覆盖已有选定文件，不扫描 home / workspace / 安装缓存；领取仍按协议新增 |
| ArtifactBrowser 读取报告及全部可访问关联 / 分页 | 57 个文件，其中四份轨迹共 120 行，零预览错误；读取前后摘要不变 | 保存归档的读取层；没有新增页面点击验收或模型调用 |
| 每项 runtime、setup 与运行清单复核；操作系统核对四个专用 CLI PID | 四项准备进程退出，host childClosed=true / exitCode=0 / forceStopped=false，adapterExitCode=0 / stdinWriterStopped=true；四份 run.json 的 state=sealed，四个 CLI PID 均不存在 | 当前四个自有任务的正常退出，不扩大到任意外部进程树 |
| 对原实验、首次续跑及末轮结果再次预检 | 三个源均不可继续；前两者已领取，末轮 newSamples=0 | 无重复领取或额外启动 |
| 本次交付 / 验收十份 Markdown 的链接 / 锚点、复现示例 Python AST、补丁与范围检查 | 402 个本地链接 / 100 个目标、一个示例解析及 git diff --check 通过；生产代码、测试、公共输入和 069 历史记录无新差异 | 示例未再次执行模型，原始归档和凭据未纳入 Git |

四个 caseRunId、runId、sessionId 分别唯一。四项 changedFields 均仅为 configurationMatch：批次行未保存该字段，离线报告从实际路由解析为 matched；原任务、录制、断言与用量保持一致。补充清单读取曾误用 status 而报 KeyError，按既有 state 字段重读后确认四项 sealed，没有修改归档或追加任务。

| 指标 | 历史复用两项 | 末轮新增两项 | 四项合计 |
| --- | ---: | ---: | ---: |
| modelCalls | 6 | 6 | 12 |
| toolCalls | 4 | 4 | 8 |
| 已报告 totalTokens | 38269 | 38470 | 76739 |
| 任务 passed | 2 / 2 | 2 / 2 | 4 / 4 |

inputTokens=25147、outputTokens=392，totalTokens 保留实际报告值，不由 input + output 推造。四项 elapsedSeconds 合计约 21.765 秒，包含准备 / 执行 / 清理，不是纯模型延迟或全部验收流程时间。费用四项均缺失，保持 null，不能推断成本改善。

## 风险与后续

本批仅验证当前 Windows / CLI、已有单配置、两用例各两轮。阈值 1 的任务仍实际报告约 1.9 万 token，直接说明其只停止后续调度，不截断当前任务。没有执行完整十用例双配置 / 重复扩大，也不支持总体模型优劣、显著性、性能或费用改善结论。

源文件、原断言与历史失败不改写；未知执行、清理不明和原失败停止策略继续阻断。短根成功不代表扩展路径、任意崩溃恢复或归档迁移已支持，远端模型别名及实际权重版本没有独立认证。

本批没有重跑完整本地代码套件；069 的 378 Python / 91 Node 属于其历史结果，070 的 CI 属于精确实现 SHA。当前只追加真实任务、独立报告、读取层检查及文档，后续文档提交 CI 单独核对。

## 文档同步

同步 README、用量停止与实验 / 续跑说明、输出根验证范围、当前进度、M6 顺序及 CHANGELOG。生产代码、测试、格式、公共用例和模板保持原样，原始会话、凭据及安装产物保持隔离。
