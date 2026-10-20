# 修改记录 017 M4.1 重复试验与指标口径

日期：2026 年 10 月 21 日，Asia/Shanghai。类型：功能 / 测试 / 文档。插件版本：`0.1.2`。相关 Git 提交：本批尚未提交；已核实前批 M3.4 修复为 `5cdd803`，纠正旧进度和私人交接中“尚未提交”的说明，不修改历史记录 016。

## 问题与目标

M3.4 能顺序隔离执行，但重复同一用例只能手写多个 entryId，没有明确重复编号、实验配置与统计口径。直接拿 passed 除以完成数可能隐藏取消、启动错误、无法评测和停止跳过；把缺失 token 当零也会产生错误比较。本批建立可追溯的重复样本和观测指标，为 M4.2 报告提供输入。

## 文件修改

| 文件 | 修改前 | 修改后 | 原因 |
| --- | --- | --- | --- |
| `dsh_eval/formats.py`、`dsh_eval/experiment.py`、`dsh_eval/__main__.py` | 单例 / 批次入口 | 版本 1 实验、全组合预检、冻结输入、样本关联、`--experiment --run` | 明确用例 × 配置 × 重复编号，复用既有清理 |
| `dsh_eval/metrics.py`、`dsh_eval/evaluate.py` | 无指标 | fresh inspect 后提取已结算尝试、工具与报告的 usage；明确分母和逐指标覆盖 | 保留无法评测与缺失事实 |
| `dsh_eval/runner.py`、`dsh_eval/batch.py` | 无运行计时 / 批次指标 | 单调时钟 elapsedSeconds，批次可选 source / metrics | 计时独立于任务预算和任务结论 |
| `test/test_metrics.py`、`test/test_experiment.py`、`test/test_evaluation.py` | 76 项 Python | 新 19 项，合计 95 项 | 确定性统计、真实管道与 fresh inspect 回归 |
| `fixtures/evaluation/recovery.experiment.json`、样例 README | 只有单例和 batch | 一个配置、一个恢复用例、两次重复 | 提供可运行入口，清单不是执行证据 |
| `docs/experiments.md`、README、进度、架构、格式、batch 说明、M3 路线、CHANGELOG | 下一批 M4.1 | 实际实现、口径、验证与 M4.2 入口 | 公开仓库可独立接续 |

本地存在的 private-notes/handoff.md / interview.md 同步当前结论和讨论，继续忽略；没有修改 src、录制协议、main.py、旧用例或历史记录。

## 实现与技术取舍

选择单独实验清单展开成版本 1 batch，避免再实现一套进程管理。读取并严格校验全部原始用例，然后完整替换 configRef，预检所有组合；配置不合规时不建执行目录、不调用模型。冻结原输入和全部展开项后，交给原 run_batch 顺序执行，继承独立 home / workspace / 会话 / 状态及 continue / stop、人工中断、清理未确认策略。固定重复 / 用例 / 配置顺序，不声称随机化或统计独立性。

sampleId 对应 batch entryId，caseEntryId + configurationId + repeatIndex 明确计划位置；返回后核对 caseId、请求配置、样本数、执行身份去重，保存实际配置及 matched / mismatched / unknown。实验初始计划和终态以独立临时文件 replace，运行中由原 batch 检查点提供进度，没有新增回调调度或 resume。

统计同时报告可评测通过比例、全尝试通过比例和可评测覆盖，每项保存分子、分母；零分母为 null。attempted 是分配 caseRunId 的尝试，不等于模型请求。skipped 保留空 outcome；三维分类和配置匹配单列。

指标复用每次真实 Node inspect 与身份校验，唯一闭合、连续的任务内才计数。核对当前安装的 dsh-session / dsh-llm 类型后，确认 request/header 是配置段变更，因此 modelCalls 使用 assistant/message + assistant/attempt 已结算事件，不能视为供应商账单请求数。usage 逐字段读取，不按字符、步骤或 input + output 估计 total；失败尝试用量不可得时保持 null。计数、用量可随取消保留，但不使任务变成 passed。

elapsedSeconds 从保存 case 快照后到保存 runtime 前采集，含准备 / 安装、执行、清理与运行事实整理，排除 offline inspect / 断言及结果落盘。runtime 身份必须匹配。没有价格采集，cost 恒 null；各指标只汇总观测子集并列缺失数量。不提前增加配置比较、置信区间或报告层。

## 验证

运行环境：Windows，Python `3.12.0`、Node.js `v24.14.0`；真实宿主固定版本继续为 DSH `0.2.0-rc.2` / Cordis `4.0.4`。2026 年 10 月 21 日执行：

| 命令或操作 | 结果 | 证明的范围 |
| --- | --- | --- |
| `python -m unittest discover -s test -p test_metrics.py` / `test_experiment.py` | 初次新 6 + 9 项通过；随后增加 3 项离线回归和 1 项真实 step 顺序回归，全部纳入完整检查 | 格式、配置展开、冻结、重置、关联、失败与跳过、取消 / 启动错误 / 中断、分母及缺失 |
| `npm.cmd run test:python` | 首次沙箱 94 项中四项进程树强停权限拒绝；获准环境 94 项通过；补边界回归后获准环境完整 95 项通过 | 原 76 + 新 19，包含真实自有进程 / 管道清理；权限失败未计通过 |
| `npm.cmd test` / `npm.cmd run check` | 42 项 Node / 29 个 JS 文件通过 | 既有 JavaScript 回归与语法 |
| `python -m compileall -q dsh_eval test` | 通过 | Python 语法 |
| `python -m scripts.smoke_bridge` | 获准环境真实工具注册 / IPC 四次请求通过，未调用模型 | 宿主桥接与状态连接 |
| `python -m dsh_eval --experiment fixtures/evaluation/recovery.experiment.json --run`，首轮 | 两个任务均 passed；计数 / token 因 step/start 早于 user/message 被错误排除而留空 | 发现指标边界过窄，不将首轮计数视为验收通过 |
| 同命令，修正后新实验 | 两个真实重复样本 passed / completed / complete，实际配置匹配；每次读取 project.md 先 Error 后成功 | 新入口、故障重置、实际关联及指标完整链路 |
| 四次实际执行分别用保存 case / evidence 调用离线 evaluate，前后核对原 JSON / JSONL SHA-256 | 均保持 passed；新实验指标一致；首轮新复验恢复指标，原文件全部未变 | fresh inspect、历史保留与离线可追溯 |
| `Get-Process` 查询四个专用宿主 PID | 均无进程；runtime 均 childClosed=true、forceStopped=false、写线程停止、适配退出 0 | 本次受控 Windows 宿主清理 |
| 内联 Python 核对公开 Markdown 相对链接与公开输入格式；`git diff --check`、`git check-ignore`、`git ls-files` | 32 份公开 Markdown / 161 个本地链接有效；5 个用例、1 个 batch、1 个 experiment 通过；无空白错误，runs / private-notes 忽略且无跟踪 | 公开接续文档及私人 / 原始内容隔离 |

最终新实验 ID `e3933155-4d89-4b1b-8b58-07148c38154f`，batchId `b105307d-f313-49ed-ad3d-fefae8d4508f`。两个 caseRunId 为 `527d0f0c-90ac-4bf4-8269-69c0feaba31a`、`70654239-7a7c-4995-b83d-e8e43a475fff`。实际配置均为 deepseek-official / deepseek-flash / headless / 0.1.2。

| 最终样本 | 已结算模型尝试 | 工具调用 | 报告 totalTokens | 运行耗时秒 |
| --- | --- | --- | --- | --- |
| repeatIndex=1 | 3 | 2 | 22531 | 约 5.719 |
| repeatIndex=2 | 4 | 3 | 30240 | 约 7.406 |

这些是同一恢复用例和配置的两个验收样本，不能推断模型提升。inputTokens / outputTokens / totalTokens 按宿主原 usage 字段保留，后者不由前两者补算。费用仍缺失。首轮实验 `64f05fc5-c751-4a6c-8161-a5a19c7c0471` 和全部原始内容继续保存在忽略目录，不覆盖、不作为公开仓库依赖。修正仅移除不参与输出指标的 step/start 边界限制，仍严格限制助手、工具事件不能跨越用户任务。

合成集成测试使用真实 Node 进程、原录制器、Python 状态和 fresh inspect，适配器是合成程序；多配置标签、人工 usage 与注入 KeyboardInterrupt 不代表真实多模型比较或手工按键验证。本批未重跑 smoke:host / check:output，未复验更早 M3 模型轨迹；历史验证不改写。

## 风险与后续

保持 evidence 和录制格式，evaluation / runtime / batch 新字段为可选兼容扩展。指标只覆盖闭合观测，adapter 内部未记录重试、未结算请求或损坏日志不能补数。runtime 计时不是签名，不是模型推理延迟或预算。实验输出不保证 fsync / 崩溃恢复；运行中或输出失败后可能保留 running，不计为成功。

下一批 M4.2 从保存的实验输入、实际配置匹配和指标覆盖出发，增加可核对配置比较、报告与不确定性说明，再进入 M5 浏览与 CI，剩两个实施批次。保留现有模型 / 来源 / 分母语义，不从本批小样本得出提升结论。

## 面试讨论点

可演示同一故障恢复环境每次重置、实际配置与计划配置分开关联、取消与普通失败分开统计、零用量与未采集用量区别。实际遇到 step/start 在输入前的宿主顺序，保留首轮结果，新增回归、修正规则并新建实验验收；测试全绿与完整录制都不能替代真实任务及指标验证。

## 文档同步

新增重复试验说明并同步 README、进度、架构、评测格式、batch 说明、样例说明、后续路线和 CHANGELOG。本地私人材料同步复现命令与下一批入口，继续忽略。公开 Markdown 相对链接、输入格式、忽略与跟踪状态、git diff 空白检查已通过，详见上表。
