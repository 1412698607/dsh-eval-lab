# dsh-eval-lab 开发进度

截至 2026 年 10 月 24 日（Asia/Shanghai），插件版本 `0.1.2`。已核实 `a239d7d` 包含 [M6.2 配置传递修复 026](changes/2026-10-23-026-m6-2-recorder-config-propagation.md) 与 [M6.3 单配置固定评测集 027](changes/2026-10-24-027-m6-3-core-evaluation.md)，`2c60b63` 包含 [审查修复 028](changes/2026-10-24-028-m6-3-assertion-constraints.md) 与 [分支整理 029](changes/2026-10-24-029-m5-m6-delivery-branch.md)。实际分支为 `20261024/feat/m6-4-web-lifecycle`，HEAD `103c090` 已包含 030 至 034。035 至 037 及 036 两项 P2 修复均保留未提交状态；本轮 [038](changes/2026-10-24-038-m6-4-ci-capture-path-normalization.md) 登录读取原云端失败堆栈，修复共享验证函数的父目录规范化缺口，完整 202 Python 回归通过，没有新增模型、提交 / 推送或云端运行。

既定 M1 至 M5 保留原本地与云端验收，历史失败不覆盖。[M6 可靠性与真实验收](plans/m6-reliability-validation.md) 的 M6.1 / M6.2 已完成本地验证；027 / 028 保持原范围。033 的四次 deepseek-flash Web 任务保留首次正常失败与旧取消工作区未知；034 按用户新授权只追加一个取消任务，完成工作区匹配、实际 README 读取、页面停止与退出复验。累计五次任务，三个最终场景均有工作区匹配的生命周期样本；取消 / 中断仍 unevaluable。双配置 / 重复扩展仍待定，本批没有新的云端 CI。

## 项目目标

围绕 DeepSeek Harness 构建 Agent 行为回归测试工具：对固定任务与环境运行 Agent，检查工具行为和最终结果，比较配置。当前成果包含录制检查、离线断言、受控单用例 / 批次、重复试验与配置报告，公开样本计数、分母、匹配 / 来源覆盖和条件配对差值；少量验收样本不能推断模型整体表现、成本或性能提升。

## 当前基线

| 项目 | 当前状态 |
| --- | --- |
| 插件版本 | `0.1.2`；M6.1 新 run.json 版本 2 / 清单版本 1，JSONL / status 仍为版本 1 |
| 当前开发分支 | `20261024/feat/m6-4-web-lifecycle` |
| 当前文档基线 | `103c090` 已包含 030 至 034；035 至 038 尚未提交，历史验证结果保留 |
| 当前云端状态 | 103c090 的运行 40075970788 保持原 Python failure；038 已读取 196 项中一项路径误判堆栈并本地修复 / 验证，新修复尚未进入云端运行 |
| 已核实基线提交 | `e47de36` 为云端路径兼容修复；`db6d572` 为 M5 审查修复；`36b4e1b` 为 M5 主体；`b0de80c` 为 M4.2；`a39e43c` 为 M4.1 指标溢出修复，`1a6cf69` 为主体；`5cdd803` 为 M3.4 启动失败修复；`bbe1b4a` 为 M3.4 主体；`3ce645d` 为 M3.3 审查修复，`302855f` 为 M3.3 主体；`31a24fa` 为 M3.2；`868529d` 为 M3.1；`4f54ddf` 为 M2.3 与路线，经 `de86bd2` 合并；`f459945` 为 M2.2 |
| 开发语言 | JavaScript 宿主接入和生命周期及浏览交互；Python 已实现离线断言、状态化环境、真实单用例 / 批次、重复统计、离线报告及只读浏览服务 |
| 实测环境 | Node.js `v24.14.0`、npm `11.9.0`、pnpm `11.25.0`、Python `3.12.0`、Windows |
| 真实组件基线 | DSH SessionStore `0.2.0-rc.2`，Cordis `4.0.4` |
| 最新复核日期 | 2026 年 10 月 24 日，Asia/Shanghai |
| 真实模型基线 | CLI `0.2.0-rc.2`；`deepseek-official / deepseek-flash`；独立 Web / headless profile |

## 功能状态

| 能力 | 实现与验证状态 | 入口 |
| --- | --- | --- |
| 原生插件入口 | 订阅事件与检查点，使用 `ctx.effect()` 清理；真实卸载后封存通过 | `src/index.js` |
| 可移植目录配置 | 显式配置 > 环境变量 > 用户目录；无效选中值报错 | `src/config.js` |
| 输出通道 | 插件诊断统一 stderr，真实正常与磁盘错误子进程 stdout 为空 | `scripts/check-output.js` |
| 组件版本检查 | 自动查找及显式路径校验固定版本 | `scripts/lib/host.js` |
| 实时事件录制 | 保持观察顺序和接收时内容，按 UUID 运行目录及会话哈希文件隔离 | `src/recorder.js` |
| 持久化会话状态 | `recording` / `sealed` / `failed`，同目录临时文件与 rename 替换 | `src/session-status.js` |
| 检查点与关闭 | flush 只保存前缀检查点；close 停止接收、排空全部队列并封存；重复关闭共享 Promise | `src/recorder.js` |
| 容量保护 | 单条完整 UTF-8 行默认 1 MiB，全录制器待写 Buffer 默认 16 MiB；独立可配置，超限使受影响会话失败，不截断证据 | `src/recorder.js`、[资源边界](recorder-resources.md) |
| 资源测量 | 长文本、超限、多会话突发 / 分批、慢写入和队列溢出；8 类各 3 个真实进程实测，有内存采样及清单 I/O 口径 | `npm.cmd run measure:recorder` |
| 离线检查 | 流式解析及原始字节 SHA-256，核对身份、计数、序号边界和摘要；退出码 0 / 1 / 2 | `src/inspect.js`、`scripts/inspect.js` |
| 运行级会话清单 | 新元信息版本 2；共享批次合并登记，替换有限重试；登记先于会话文件，close 最后封存；整对缺失可检测，旧格式覆盖未知 | [会话清单](run-manifest.md)、记录 023 / 024 |
| 序号与捕获范围 | 严格递增非负安全整数；允许非零起点，报告缺口；保持 `live-events-only` | 记录器及检查器 |
| 模拟演示 | 8 条模拟事件正常封存并通过 inspect，无模型调用 | `scripts/demo.js` |
| 真实组件接入 | 6 条人工事件原样导出，检查点仍开放，卸载后 sealed 并通过 inspect | `scripts/lib/host-smoke.js` |
| 未关闭直接退出 | 独立录制器子进程 flush 后 `process.exit(0)`，inspect 返回 2 | `scripts/fixtures/output-child.js` |
| Web / headless 真实模型联调 | 实际安装、文件读取及字段答案、工具失败后响应、取消、强停已验证 | `scripts/prepare-live.js`、`scripts/run-live.js` |
| 固定 fixture 证据检查 | Python 先重新 inspect，再核对工具结果、答案及结束事实；6 项测试通过 | `scripts/verify_live.py` |
| desktop / SDK | 尚未验证 | 后续按渠道需求验证 |
| M6.4 脚本与无模型检查 | 三个专用子进程、合成事件及 fresh inspect；中断核对版本与完整已写前缀，独立格式只接受 synthetic | `scripts/check_web_lifecycle.py`、[Web 生命周期](web-lifecycle.md) |
| M6.4 真实 Web 生命周期 | Windows / 当前 CLI 三类最终样本的历史验收保留；036 修复 035 的异常启动清理与普通退出时间关联，无模型原生 / 离线复验通过 | `scripts/web-lifecycle-live.js`、`scripts/verify_web_live.py`、记录 033 至 036 |
| 用例加载与通用离线任务断言 | 用例、证据 / 结果版本 1 / 2；三种断言、可选 after / textEquals 和三维结果，版本 2 额外核对实际请求路由 | `dsh_eval/`、`docs/evaluation-format.md` |
| 单用例真实驱动 | 独立 workspace / home / 新会话，真实路由、超时 / 取消和清理；可选用例 recorder 经冻结后传入隔离插件配置，批次 / 实验保留 | `dsh_eval/runner.py`、`scripts/case-host.js` |
| 状态化工具环境与实时桥接 | 主体与历史真实模型样例通过；监督阻塞与目录断言过窄已修复，新增七项回归 | `dsh_eval/environment.py`、`docs/stateful-tools.md`、审查记录 013 |
| 顺序批次、重置和结果清单 | 版本 1 批次 / 结果与历史真实恢复批次已验证；启动失败策略及 source / metrics 可选输出已实现 | `dsh_eval/batch.py`、[批次运行](batch-runner.md) |
| 重复试验与观测统计 | 版本 1 实验、三种分母、缺失覆盖及异常单值 / 求和保护已实现；本批历史样本复验保持原分类 | `dsh_eval/experiment.py`、`dsh_eval/metrics.py`、[重复试验](experiments.md)、修复记录 018 |
| 配置比较报告与不确定性边界 | 已实现版本 1 离线 JSON / Markdown；核对输入 / 身份 / 路由 / 来源，同用例和重复编号配对，公开范围、分母与排除；多配置验证为合成样本 | `dsh_eval/report.py`、[配置报告](configuration-reports.md)、记录 019 |
| 固定真实评测集 | 10 个用例单配置首次真实验收通过；028 补齐必要步骤顺序和精确空文本，旧录制离线检查通过；双配置比较尚未执行 | [固定评测集](core-evaluation.md)、`fixtures/evaluation/core/` |
| 结果浏览与持续集成 | 本地只读浏览及审查修复已实现；云端路径问题已修，Windows CI 的 134 Python / 44 Node / 31 文件语法、compileall 和 demo 全部通过 | [结果浏览](result-browser.md)、记录 020 / 021 / 022 |

## 最新验证：M6.4 CI 采集目录规范化（038，2026 年 10 月 24 日）

- 登录后已读原 job 的真实堆栈：196 项 / 57.720 秒 / errors=1，失败在共享 verify_recorded_task 的目录包含关系比较，尚未进入目标检查点断言；036 未涉及此处。
- 共享函数只增加入口 Path(directory).resolve()，使父子目录以相同表示比较；真实 traces 别名逃逸仍在 inspect 前拒绝，外层固定 runDir 校验、格式版本和检查点门禁不变。
- 新增三项真实 junction / 非规范化父路径 / 逃逸回归，修复前 3 项出现 7 个错误，修复后生命周期 39 项通过；获准完整 202 Python / 48.113 秒及 compileall 通过。
- 独立合成入口三场景 verified，liveWebVerified=false；正常 passed，取消 / 中断 unevaluable。没有新增模型任务，不重复 036 的 Node / JS 检查，不改原始证据或历史记录。
- 当前修复仍在本地，未提交 / 推送或触发云端；下一入口是包含修复的新提交验收，不将原失败改写为云端通过。详见 [记录 038](changes/2026-10-24-038-m6-4-ci-capture-path-normalization.md)。

## 历史复审：M6.4 修复与云端状态（037，2026 年 10 月 24 日）

- 036 的四份代码 / 测试差异和相关文档复审未发现新的可确认代码问题；本轮不改实现，不重复完整回归，036 的 199 Python / 85 Node 等结果保留为历史。
- 新执行 demo:eval，并用真实离线 CLI / fresh inspect 检查 read-project、missing-file 两份新合成输出，均 completed / complete / passed；无模型任务。
- [现有云端运行 40075970788](https://github.com/1412698607/dsh-eval-lab/actions/runs/40075970788) 的 head SHA 精确匹配 103c090：JS 语法 / Node 步骤通过，Python 步骤失败，后续 Python 编译 / 示例跳过，不能验收为通过。
- check-run 仅提供退出码 1；日志 API 返回 403，网页要求登录，未取得失败测试名 / 堆栈，根因仍未知。该运行未包含本地 035 / 036，不能从其状态判断本地修复是否解决了云端问题。
- 下一入口：取得失败堆栈再定位；035 至 037 保留未提交状态，没有推送、重跑云端或新模型。详见 [记录 037](changes/2026-10-24-037-m6-4-final-review-ci-status.md)。

## 历史验证：M6.4 启动清理与退出时间关联修复（036，2026 年 10 月 24 日）

- 启动前拒绝旧输出，启动成功后立即注册退出观察；初始化 / I/O 可捕获错误统一回收自有正整数 PID，最多十秒等待有效 PID 与实际退出，不将 PID 0 传入 kill，失败事实不伪装为正常关闭。
- 普通退出要求 turn/end ≤ Ctrl+C 操作 ≤ SIGINT ≤ 唯一卸载；取消检查点 / 页面停止保留原时间顺序，允许同一毫秒相等。
- 新增三项 Python / 三项 Node 回归。修复前 Python 出现 14 个反例失败，两项 Node 启动检查失败；修复后定向 36 Python / 6 Node 通过。
- 实际原生 ConPTY 无模型 fixture 验证旧输出预拒绝、启动后写入冲突回收和真实退出；首轮因输入管道关闭导致 fixture 未启动的失败保留，保持输入打开后新目录通过。
- 八份明确保存场景经 fresh inspect / 独立 CLI 核对：五份应通过样本通过，初始失败及两份时间矛盾反例拒绝；原证据未改，旧取消环境未知保留，新增模型任务为零。
- 获准完整 199 Python / 85 Node（无失败 / 跳过）、41 份 JS 语法及 compileall 通过，未新增模型任务。文档 / 摘要收尾结果见 [记录 036](changes/2026-10-24-036-m6-4-startup-cleanup-timeline.md)。本轮不提交、推送或运行云端 CI，后续当前提交的云端验收 / 扩展范围另定。

## 历史审查：文档状态与 M6.4 交付（035，2026 年 10 月 24 日）

- 已核实 `103c090` 包含 030 至 034；同步当前提交与完成范围，旧记录中的未提交和失败均保留。
- 两项 P2 待修：ConPTY 启动后证据文件写入失败未回收子进程；普通退出的 operation / 卸载时间未关联原生任务结束与 SIGINT，矛盾时间副本仍通过。
- 无模型复现：实际原生专用子进程验证清理遗漏后已按自有 PID 回收；已有正常样本的两份独立时间副本经 fresh inspect / CLI 均误通过，原证据未改。
- 获准环境现有 33 项 Python、3 项 Node、41 份 JS 语法通过；首次沙箱 spawn / 管道 EPERM 均不计通过。本轮未修改代码 / 测试，未运行真实模型、完整回归或云端 CI。
- 下一批先修上述两项并补回归，再做当前提交的无模型云端验收或扩大配置 / 重复范围。详见 [记录 035](changes/2026-10-24-035-m6-4-status-review.md)。

## 历史验证：取消工作区一致性（034，2026 年 10 月 24 日）

- 按用户新授权，仍用 deepseek-official / deepseek-flash，只追加一个 page-cancel 任务；提交前实际任务数为 0，录制中恰有一个 source.kind=user 输入。没有重跑正常或中断，累计为五任务（正常两次、取消两次、中断一次），原样本和历史记录未改。
- 提交前工作区注册表、隔离配置、原生 cwd 与冻结 fixture 一致；实际 read README 的 callSeq=17 / resultSeq=18 返回正确 projectName，早于取消检查点 afterSeq=21。CUA 在同任务中真实点击停止，turn/end 为 aborted/user；之后原生 Ctrl+C、SIGINT / 卸载和 exit130，无强停或错误。
- 新样本 25 条 sealed，fresh inspect=complete，全部 25 条原生事件 cwd 匹配；environment.workspaceMatch 与 workspaceObservationAvailable 均为 true。结果 cancelled / complete / unevaluable，主断言 not_run；单独读取证据检查 passed 仅说明取消前读取成功，不代表任务完成。
- 新样本独立 CLI 复验通过；错误工作区副本被拒绝；缺 cwd 副本和原取消样本仍只得到未知，不能通过文档中的工作区覆盖门禁。原取消样本的生命周期通过与工作区未知两项事实均保留。
- 本轮未改生产代码、测试或协议，定向复验现有 9 Python / 3 Node 通过；228 份受保护代码 / 历史记录 / 旧证据、18 份新原始证据摘要不变，自有 CLI PID 再查不存在。033 的 196 Python / 82 Node / 41 文件语法及 compileall 是历史全量结果，本轮不重复执行或记作新成绩。

唯一追加任务额度已使用，运行指标为 modelCalls=2 / toolCalls=1，取消后的不完整 token 与费用仍为 null。当前 Windows / CLI 范围的取消工作区缺口已由新样本补齐；旧样本不升级，其他平台 / 配置 / 重复仍待新范围。详见 [记录 034](changes/2026-10-24-034-m6-4-cancel-workspace-validation.md)。

## 历史验证：M6.4 真实 Web（033，2026 年 10 月 24 日）

- 新增独立 Web 准备 / ConPTY 监督器、纯观察插件及 live 协议验证器，CUA 实际提交任务和点击停止。普通退出实际触发 SIGINT、插件卸载和 exitCode=130；任务中断使用自有 PID 强停，本机实际 exitCode=1 / signal=null，录制不补造封存。
- 首轮正常任务实际读取了错误的默认工作区，README 不存在，读取与答案断言失败；监督器又误把上下文消息当成第二个任务，最终超时强停。原始报告中的 PID=0 等缺陷事实完整保留，不能重标为通过。修复实际工作区绑定、source.kind=user 计数、就绪后 PID 捕获和结束后撤销计时器后，只追加正常任务，未重跑取消 / 中断。
- 最终正常任务为 completed / complete / passed，实际 README 读取与答案匹配；取消为 cancelled / complete / unevaluable；中断为 interrupted / unverified / unevaluable，后两项断言 not_run。取消样本在 cwd 观测加入前采集，workspaceMatch=null，原读取失败；其通过仅说明页面取消与退出成立。正常与中断工作区均匹配。
- 原两项审查修复已用于真实录制：未知状态版本、空检查点及未覆盖 afterSeq 的检查点副本均被拒绝。真实中断原始 16 条事件、检查点覆盖 14 条截至 seq=13，操作 afterSeq=13，最后两条保持未确认；合成 fixture 继续严格要求覆盖完整前缀。
- 新增 11 Python / 3 Node 回归，最终完整 196 Python（57.089 秒）、82 Node（无失败 / 跳过）、41 文件 JS 语法和 compileall 通过。独立 CLI 复验四样本保留一拒绝 / 三通过，八组负例副本均拒绝；38 份本批原始证据及 77 份受保护源文件 / 历史证据摘要不变。四个实际 CLI PID 和最终控制台预检 PID 再查均不存在。

本批四次模型任务额度已使用，三类生命周期各有通过样本不等于首次 3 / 3 或四次任务成功。取消 fixture 一致性、其他平台 / 版本、双配置 / 重复均未补验；不再自动新增模型任务。详见 [修改记录 033](changes/2026-10-24-033-m6-4-live-web-validation.md)。

## 历史验证：M6.4 中断门禁修复（032，2026 年 10 月 24 日）

- 复审发现 031 的 unverified / recording 条件不足以排除不支持的运行状态格式，也不能证明状态检查点已经覆盖操作 afterSeq。本次新增版本门禁，并比较磁盘检查点与 fresh inspect 的完整前缀；空 / 落后检查点和残留 .tmp 均拒绝场景通过，通用 inspect 的未确认分类及历史验证结果保留。
- 新增 5 项回归，旧实现在其中 4 个方法触发 11 个反例失败；修复后 22 项生命周期测试通过（1.956 秒）。非零序号起点、正常 / 取消 / 中断三正例保持通过，断言和任务分类不变。
- 获准完整 185 Python（49.510 秒）、79 Node（无失败 / 跳过）、38 文件 JS 语法及 dsh_eval / scripts / test compileall 通过。真实进程回归直接在获准环境执行，本批没有新增沙箱失败样本。
- 独立无模型入口三个场景均 verified，正常为 completed / complete / passed，取消和中断仍为 unevaluable / 断言 not_run。另由独立 Python CLI 重查三正例、拒绝未知状态版本 / 空检查点 / 落后检查点 / 残留替换文件四反例，所有 liveWebVerified 均 false；77 份受保护源文件及历史证据、28 份本批原始采集文件摘要保持不变。

本批仅修改专用 Python 生命周期验收器、回归和文档，原 recorder / inspect、通用评测包及文件格式不变，没有模型任务或云端运行。下一步仍为真实 Web 启动和操作来源采集，模型任务配置与数量另定。详见 [修改记录 032](changes/2026-10-24-032-m6-4-interruption-gates.md)。

## 历史验证：M6.4 脚本与无模型阶段（031，2026 年 10 月 24 日）

- 新增 Web 固定用例、合成子进程采集、独立 Python 验收器及 npm 检查入口。生命周期捕获 / 验证使用独立版本 1，不改原 run / JSONL / status 或通用评测格式；真实录制器、文件读取、close / SIGKILL 和 fresh inspect 均实际执行，不启动 Harness 或模型。
- 新增 17 项回归，获准环境通过；完整 180 Python（48.692 秒）、79 Node、38 文件 JS 语法及 dsh_eval / scripts / test compileall 通过。初次沙箱检查仅 7 项事件规则通过，真实 fork EPERM 未计通过，随后获准复验通过。
- `npm.cmd run check:web-lifecycle` 的三项实际进程检查均 verified：正常任务 completed / complete / passed，取消 cancelled / complete / unevaluable，中断 interrupted / unverified / unevaluable；后两项断言 not_run。所有结果保持 synthetic / liveWebVerified=false，拒绝将 source 改为 live；不把场景 verified 算作任务成功或真实 Web 验收。
- 回归覆盖错误取消原因 / 输入 / 顺序、缺失工具结果、错误答案 / 参数、损坏后保留旧成功、整对会话消失、已封存成功重标中断、超时兜底、进程未关闭、inspect 不可用及输出不可覆盖。无模型 CI 的 compileall 范围加入 scripts，本批未触发云端运行。

下一步接入真实 Web 启动、操作来源与生命周期观察，再安排实际页面取消、普通退出和处理中断；新增模型配置与数量另定。详见 [Web 生命周期](web-lifecycle.md) 和 [记录 031](changes/2026-10-24-031-m6-4-no-model-lifecycle.md)。

## 历史验证：M6.3 审查修复（028，2026 年 10 月 24 日）

- 六个顺序用例声明 11 条 after 关系，一个空文件用例声明 textEquals=""。后继调用必须晚于先行结果，独立重试路径仍可交错；非空或空白工具返回不能算空文件。
- 新增 5 项固定集回归先在旧实现出现 9 个反例 subTest 失败，修复后固定集 11 项通过；新增 8 项格式 / 依赖 / 文本边界测试。完整 163 Python（获准环境，45.800 秒）、79 Node、36 文件语法及 compileall 通过。
- 对已有 10 项真实录制另按当前用例离线 evaluate，全部 passed；标准 report 按原冻结用例复验仍 10 verified / matched / passed，changedFields 全空。新报告 ID `c1a95bab-f3c9-4f1c-9dcd-2a33bd98ef36`，原 125 份 JSON / JSONL 摘要不变。七个当前用例仅断言变化，未改写历史快照。
- README 与当前里程碑状态已同步。本次没有新模型任务、云端 CI 或宿主 / 资源测量重跑；下一批仍是 M6.4，双配置与重复扩展仍待预算。详见 [记录 028](changes/2026-10-24-028-m6-3-assertion-constraints.md)。

## 历史验证：M6.3 单配置固定评测集（027，2026 年 10 月 24 日）

- 新增 10 个版本 2 固定用例、一个单配置单轮实验清单和 6 项无模型回归。30 份参考正例 / 无工具 / 错误答案轨迹经过真实录制与 fresh inspect，另验证 22 项必要工具证据删除以及 4 组替代目录 / 状态重置。
- 完整 150 Python（获准环境，44.706 秒）、79 Node、36 文件 JS 语法及 compileall 通过。本批未修改生产执行代码，保留上一批未提交配置修复，没有运行云端 CI、资源基线或旧模型任务。
- 经用户明确选择，现有 deepseek-official / deepseek-flash 顺序执行 10 个用例各一次。planned / attempted / finished 为 10 / 10 / 10，skipped / errors 为 0 / 0，10 项均 completed / complete / passed。独立离线报告均 verified / matched、source=live、changedFields 为空，单配置 comparisons 为空。
- 32 次已结算模型调用、24 次工具调用、已报告 totalTokens 合计 242085，数值指标覆盖 10 / 10，费用 10 项均缺失。耗时合计约 56.795 秒包含准备 / 执行 / 清理，不是整个命令墙钟或纯模型延迟；缓存用量字段与 totalTokens 边界见 [固定评测集](core-evaluation.md)。
- 原实验 125 份 JSON / JSONL 摘要复验前后不变，10 个录制 run 均 sealed；10 项 childClosed=true、准备进程退出、stdinWriterStopped=true，10 个保存的专用 CLI PID 再查均不存在。没有将这些事实扩张为任意进程树保证。

本批按用户选择完成单配置范围，未追加任何模型重跑；原建议的第二配置与重复扩展仍待预算，下一批入口为 M6.4 实际页面取消 / 退出 / 中断。详细证据、可复现命令及局限见 [记录 027](changes/2026-10-24-027-m6-3-core-evaluation.md)。

## 历史验证：M6.2 录制配置传递（2026 年 10 月 23 日）

- 新增四项 Node 回归在旧实现全部失败，修复后全部通过；最初五项 Python 回归中四项因 recorder 被拒失败，修复后通过，再补一项省略 / 显式默认冻结回归，最终新增六项通过。
- 完整 79 Node、获准环境完整 144 Python、36 文件 JS 语法及 compileall 通过；离线评测单独 36 项通过。没有重跑八类资源基线、旧输出四场景或历史模型样本，不继承历史结果作为本次实测。
- 真实 CLI 离线安装生成隔离 profile，由真实 --dump-config 合并安装 bundle / profile，再从合并后的 eval-lab 条目挂载真实 Cordis / SessionStore。同一 1.25 MiB 正文：默认 1 / 16 MiB 报 EVENT_BYTES_LIMIT、inspect / 1；4 / 8 MiB sealed / complete / 0；4 / 1 MiB 报 PENDING_BYTES_LIMIT、inspect / 1。输入 / setup / 合并树 / run.json 的两值一致，没有模型调用。
- 配置合并子进程首次沙箱 spawnSync EPERM 未计通过，获准环境重跑原验收通过。Python冻结测试明确在准备阶段停止，单元安装边界替身只验证生成文件；真实安装、配置合并和组件验证另行记录，未冒充模型端到端。

默认值不变，不在 configRef / 实际路由中混入录制设置，不修改历史快照；独立 case.recorder 是用例属性，没有 CLI 或实验 configurations 覆盖。原格式、上限和测量局限保持，详见 [记录 026](changes/2026-10-23-026-m6-2-recorder-config-propagation.md)。本批未提交 / 推送 / 运行云端 CI。

## 历史验证：M6.2 单条事件限制与资源基线（2026 年 10 月 22 日）

- 新增 10 项 Node 回归，改动前 8 失败 / 2 通过，最终全部通过；覆盖 UTF-8 等号边界、换行和包装、配置、toJSON、错误状态、健康会话、队列释放和重入关闭。新增 1 项 Node 录制 / Python 集成回归，正确任务前缀也不能掩盖后来超限；离线评测 36 项通过。
- 完整 75 Node、获准环境完整 138 Python（39.524 秒）、35 文件 JS 语法及 Python compileall 通过；demo 8 条模拟事件，真实 Cordis / SessionStore 6 条人工事件通过。
- 获准环境四种真实子进程通过，inspect 为 0 / 1 / 2 / 1，stdout 均为空。新超限用例保留原 6 行，超限会话 failed、健康会话 sealed；首次 fixture 缺少 surfaceOp 被宿主拒绝，修正后验证通过，历史失败输出保留。
- 最终资源基线为 8 类 × 3 次、24 个独立 Node 进程，全部满足各自预期状态。600 会话突发与分六批均 complete；后者清单累计写入 629041 字节，突发为 279456 字节。16 次 2 MiB 正文拒绝场景的采样堆增量仍达 24.94～24.97 MiB，未宣称总内存硬上限或性能提升。
- 资源入口首次普通沙箱 spawn EPERM 未计通过，获准运行使用真实进程与文件；慢写只在真实 append 前加延迟。完整规模、采样口径与局限见 [资源边界](recorder-resources.md)，不把预期录制失败计成健康任务成功。

本批无新模型、历史模型复验或云端运行。新默认上限会拒绝原先可接收的大行，可显式配置；同步序列化临时内存、会话总量、清单重写、轮转仍有边界。剩余两批见 [M6 方案](plans/m6-reliability-validation.md)。

## 历史验证：M6.1 登记可靠性修复（2026 年 10 月 22 日）

- 新增七项 Node 回归，旧实现六失败 / 一通过，修复后全部通过；覆盖暂时替换恢复、六次耗尽、非重试错误、合并 / 交错、各自登记屏障、close / flush、错误回调重入和健康已登记会话排空。
- 完整 65 Node、33 文件 JS 语法、35 离线评测 Python、17 浏览 Python，以及获准环境完整 137 Python 通过；真实 Cordis / SessionStore 六事件通过。真实输出检查首次沙箱 spawn EPERM 未计通过，获准环境三个真实子进程通过。
- 获准环境五轮各 600 个模拟小会话均 close 成功、sealed / complete / 0，无上报的永久录制错误；没有统计底层重试次数。maxPendingBytes=1 的 300 / 600 个全部拒绝会话保留堆增量为 471976 / 887024 字节，只是指定输入、单次 GC 采样观察，不是完整 benchmark 或总内存硬上限。
- 记录和状态格式不变，原验证结果保留；本批没有复验历史模型样本、调用新模型或运行云端 CI。下一批仍 M6.2，大事件、轮转和完整资源基线未在本批实施。

详情见 [记录 024](changes/2026-10-22-024-m6-1-registration-reliability.md)。重试上限是六次尝试和累计 310 ms 计划退避，不约束单次底层 I/O 的耗时；持续错误仍保持运行失败语义。

## 历史验证：M6.1 运行会话清单（2026 年 10 月 22 日）

- 新增 14 项 Node 先在旧实现失败，最终完整 58 项通过；覆盖清单 / 成员集合、整对与全部缺失、清单开放、登记 / 最终写入真实失败、健康会话隔离、重入、未来版本与旧格式覆盖局限。
- 新增三项 Python 门禁回归，离线评测 35 项、获准环境完整 137 Python 通过；新版清单异常不能继承旧 passed，旧格式保留任务判断并标明运行级覆盖未知。浏览器已接受 run.json 1 / 2，真实合成实验 / 报告递归浏览回归保持通过。
- 32 个 JS 文件语法、compileall、八条事件 demo、真实 Cordis / SessionStore 六事件与卸载封存通过。输出检查首次沙箱 spawn EPERM，获准环境正常 / 写入失败 / 未关闭退出三场景通过；最终格式再次复验通过。
- 新格式完整 / 缺一组 / 缺全部 / 清单开放 / 旧格式合成验收分别为 0 / 1 / 1 / 2 / 0，旧格式覆盖未知；基线旧 inspect 拒绝新元信息版本，原完整副本摘要不变。
- 两个既有真实实验的四个样本以新 inspect 离线复验，保持 passed / completed / complete / 断言 passed，原 80 份 JSON / JSONL 摘要不变。没有新模型调用，不把历史证据补写成清单格式，也未重复更早 M3 模型验收。

本批没有提交、推送或触发云端 CI。M5 已通过的历史云端运行不代表本批新改动已上云通过；格式和技术取舍见 [记录 023](changes/2026-10-22-023-m6-1-run-manifest.md)。

## 云端 CI 历史验收（2026 年 10 月 21 日）

- 已读取 push 运行 `39623812949`（`db6d572`）的真实作业日志：31 文件语法 / 44 Node 通过，133 Python 中两项路径检查失败，compileall / demo 被跳过。云端为 Windows 镜像 `20261007.264.1`、Node `24.21.0`、Python `3.12.10`。
- 新增真实目录别名回归先复现再通过。浏览服务同时接受显式配置前缀和真实根，保持外部引用先拒绝；报告迁移测试比较解析后的复制目录。
- 浏览 17 项、报告 17 项、获准环境完整 134 Python、compileall 与差异检查通过。
- 修复 `e47de36` 已推送，run `39625366038` / job `119309057123` / attempt 1 最终 `success`。实际日志为 31 文件语法、44 Node、134 Python 通过，compileall 与 demo 成功，`modelCalled: false`；北京时间 23:24:24 开始，23:25:44 已完成。成功环境为镜像 `20261018.275.1`、Node `24.22.0`、Python `3.12.10`，与原失败环境分别记录，不作性能比较。见 [记录 022](changes/2026-10-21-022-cloud-ci-path-aliases.md)。

## M5 审查修复历史验证（2026 年 10 月 21 日）

- 先加入四项 Python 与两项前端回归复现问题，再修复路径预检、深层 JSON 隔离、混合来源缺失筛选及结构化异常显示。浏览 JSON 容器最多 128 层，超深文档单独报错，超深轨迹保留错误 / 原行号 / 预览和后续正常行。
- 浏览 16 项与前端 2 项通过；获准环境完整 133 项 Python、44 项 Node、31 个 JavaScript 文件语法及 compileall 通过。前端检查使用最小 DOM 替身执行原页面事件与渲染逻辑，本批未重做实际浏览器视觉验收。
- 新增回归包含真实本机 HTTP，核对超深文件不影响其他内容且原输入摘要不变。根外 / 私人 / UNC 引用的测试在 `resolve()` 前拦截，不实际连接测试网络位置；原真实合成实验关联集成仍通过。

本批无新模型调用，不改变录制器、调度、评测 / 报告算法及历史文件，未重验历史模型任务或触发 / 核对托管 CI。修复尚未提交；详情与复现命令见 [记录 021](changes/2026-10-21-021-m5-review-fixes.md)。

## M5 结果浏览与 CI 历史验证（2026 年 10 月 21 日）

- 新增 `test_browser.py` 12 项通过：目录索引、读取时不运行 / 复验、历史文件摘要、缺失 / 非法版本 / 超大内容、目录穿越、符号目录 / Windows junction 与循环、认证 / Host / Origin / 写请求、真实 HTTP、CLI 和真实合成实验 / 报告关联。两配置合成样本使用原录制器和实际 Node / Python 进程，未调用模型。
- `npm.cmd run test:python`：首次沙箱 129 项中四项既有进程强停受限，未计通过；获准环境完整 129 项通过（原 117 + 新 12），最终版本再次完整通过。42 项 Node、30 个 JavaScript 文件语法、Python compileall、CLI help 和 `demo:eval` 通过。
- 真实本机 HTTP 遍历既有 5 个用例、8 个批次、3 个实验、9 份报告及 31 份逐次结果，连同关联文件共读取 292 份，含 28 份轨迹 / 691 行，无读取错误；608 份原 JSON / JSONL 前后摘要一致。这是保存内容的浏览，不是重新验证历史模型表现。
- 实际页面检查覆盖分类、名称搜索、结论 / 来源筛选、实验 / 报告详情、证据跳转和轨迹分页。额外扩展公开合成事件用于超过一页的浏览验收，仍为 synthetic，不是新的模型任务。
- `.github/workflows/deterministic.yml` 已配置 Windows、Node 24 / Python 3.12 的无模型检查及只读仓库权限。没有提交、推送、触发 GitHub 工作流或上传日志；云端执行结果待首次实际运行后补录。

本批不改录制器、任务调度、原评测 / 报告算法或 main.py。无新模型调用，未重跑固定 Harness 组件 smoke；历史结果保留。运行入口与限制见 [结果浏览](result-browser.md)。

## M4.2 配置报告历史验证（2026 年 10 月 21 日）

- `python -m unittest discover -s test -p test_report.py -v`：17 项新增检查通过。使用真实 Node 子进程、原录制器 / inspect 与 Python 状态化工具，适配器和配置标签为合成；覆盖独立报告、新旧差异、任务 / 环境 / 预算 / 断言快照、实际请求头、来源隔离、同配置别名、不同用例、目录迁移、损坏 / 缺失日志、停止跳过、取消、启动错误、数值缺失 / 溢出及 CLI。独立 Python 命令行还先复现 cp936 重定向导致中文 JSON 不能按 UTF-8 解码，再固定模块 stdout UTF-8；强制旧代码页的真实子进程回归通过。
- `npm.cmd run test:python`：首次沙箱 117 项中四项既有真实进程树强停被权限阻挡，未计通过；获准环境完整 117 项通过（原 100 + 新 17）。`npm.cmd test` 42 项、`npm.cmd run check` 29 个 JavaScript 文件及 `python -m compileall -q dsh_eval test` 通过。
- 两个 M4.1 既有实验的四个真实样本通过新 `--report` 入口，保持 passed / completed / complete / 断言 passed 与实际配置匹配。首轮旧实验新报告取得 modelCalls 3 / 3、totalTokens 22512 / 22750，原汇总仍保持旧指标；最终实验指标与原报告一致，modelCalls 3 / 4、totalTokens 22531 / 30240。
- 两个历史实验各 40 份 JSON / JSONL 前后摘要一致。另新建一个两配置标签 × 两重复的合成实验，四项 passed，产生一个 synthetic 比较、两个共同配对；其 50 份 JSON / JSONL 摘要同样不变。报告的独立生成不等于真实多模型验收或模型表现结论。

本批没有新模型调用，没有重复 `smoke:host` / `check:output` / `smoke_bridge`，没有复验更早 M3 模型轨迹。原任务与录制实现未改，历史验证保留；本批验证范围及取舍见 [记录 019](changes/2026-10-21-019-m4-2-configuration-reports.md)。

## M4.1 指标溢出修复历史验证（2026 年 10 月 21 日）

- 新增五项回归先复现超大耗时导致 OverflowError、有限单值相加后产生 Infinity，以及超大 token 字段和未被排除。修复后 `test_metrics.py` 11 项、`test_evaluation.py` 32 项通过，异常耗时不改变 passed / complete / 断言结果，CLI 返回 0。
- `npm.cmd run test:python`：获准环境 100 项通过（原 95 + 新 5）；`npm.cmd test`：42 项通过；`npm.cmd run check`：29 个 JS 文件通过；`python -m compileall -q dsh_eval test` 通过。
- `python -m scripts.smoke_bridge`：获准环境真实工具注册 / IPC 四次请求通过，无模型调用。新增指标反例是合成数值；原录制器、fresh inspect 和 CLI 检查不等于新的模型任务。
- 两个历史实验的四个真实样本用各自保存 case / evidence 离线复验，三维分类与 passed 均保持。最终新实验的两个样本指标与原报告一致；首轮旧报告仍缺指标，复验可取得计数，未覆盖原文件。复验前后全部实验 JSON / JSONL SHA-256 相同。

本批无新模型调用，未重复 smoke:host / check:output，未复验更早 M3 模型轨迹。详见 [修复记录 018](changes/2026-10-21-018-m4-1-metric-overflow.md)，以下主体与历史验证保留。

## M4.1 主体历史验证（2026 年 10 月 21 日）

- `npm.cmd run test:python`：获准环境 95 项通过（原 76 + 新 19）。新增实验 / 指标检查覆盖配置展开、输入冻结、状态重置、身份关联、停止与跳过、取消、启动失败、分母、usage 缺失、损坏日志和计时身份；最后一项回归允许真实宿主在用户输入前打开 step。
- `npm.cmd test`：42 项通过；`npm.cmd run check`：29 个 JS 文件通过；`python -m compileall -q dsh_eval test` 通过。首次沙箱完整 Python 运行中四项自有进程树强停检查被权限拒绝，未计为通过；获准环境分别重跑 94 项及补齐边界回归后的 95 项均通过。
- `python -m scripts.smoke_bridge`：获准环境真实工具注册 / IPC 四次请求通过，无模型调用。
- `python -m dsh_eval --experiment fixtures/evaluation/recovery.experiment.json --run`：修正指标边界后，新实验两个真实恢复任务均 passed / completed / complete；每次 project.md 读取先 Error 后成功，状态重置有效。已结算模型尝试分别 3 / 4 次，工具调用 2 / 3 次，报告的 totalTokens 分别 22531 / 30240，运行耗时约 5.719 / 7.406 秒，均包含准备 / 执行 / 清理；费用 null。这是一个配置、一个用例、两次重复的验收，不是配置优劣或性能结论。
- 首轮两个真实任务也 passed，但将 step/start 纳入输出边界导致计数和 token 留空，原文件完整保留。修复后四次实际执行用各自保存 case / evidence 重新 inspect 和断言，均保持 passed；新实验指标与复验一致，首轮新复验恢复指标但没有覆盖旧报告。验证前后所有实验 JSON / JSONL 摘要一致。
- 四个真实宿主 childClosed=true、forceStopped=false，写线程退出且适配进程退出 0；专用宿主 PID 查询均无进程。本批没有重复 smoke:host / check:output，也未复验更早 M3 历史模型轨迹；下列历史验证保留。

确定性实验测试使用原录制器、fresh inspect、真实 Node 进程和 Python 状态，但适配器为合成程序；模拟配置标签、usage 与注入中断不等于真实多模型比较或手工按键验收。完整依据见 [记录 017](changes/2026-10-21-017-m4-1-repeated-experiments.md)。

## M3.4 启动失败修复历史验证（2026 年 10 月 19 日）

- `python -m unittest discover -s test -p test_batch.py`：18 项通过；修复前新增回归复现 continue / stop 均被误归清理未知，修复后符合策略。新增三项覆盖启动失败、启动事实缺失 / null 与启动期 KeyboardInterrupt，原已启动进程清理未知的停止检查继续通过。
- `npm.cmd run test:python`：获准环境 76 项通过（原 73 + 新 3）；`npm.cmd test`：42 项通过；`npm.cmd run check`：29 个 JS 文件通过；`python -m compileall -q dsh_eval test` 通过。
- `python -m scripts.smoke_bridge`：获准环境真实工具注册 / IPC 四次请求通过，未调用模型。启动失败与中断通过注入异常验证，后续成功项使用真实 Node 子进程和合成适配器，不代表实际模型任务或手工按键验收。

本批未新增模型运行、未复验历史模型轨迹，未重复 smoke:host / check:output；下列历史验证及其边界保留。详见 [修复记录 016](changes/2026-10-19-016-m3-4-launch-failure-policy.md)。

## M3.4 主体历史验证（2026 年 10 月 18 日）

- `npm.cmd run test:python`：获准环境 73 项通过（原 58 + 新 15）；格式和预检、冻结输入、重复状态重置、配置隔离、结果关联、失败 / 取消 / 超时策略、人工中断注入、清理未知和进度写入错误均覆盖。合成适配器使用真实 Node 进程与原录制器，未调用模型。
- `npm.cmd test` / `npm.cmd run check`：42 项 / 29 个 JS 文件通过；Python compileall 通过。`python -m scripts.smoke_bridge` 无模型实际 Cordis / Tools / IPC 四次请求通过。
- `python -m dsh_eval --batch fixtures/evaluation/recovery.batch.json --run`：新快照批次 completed / passed，stale-path / retry-first / retry-reset 均 passed；41 / 37 / 37 条、55889 / 50166 / 50783 字节。后两项 project.md 的读取结果各为一次失败后一次成功，状态不串用。
- 实际未注册路由 + 正常用例：continue 保存 runtime_error 后继续得到 passed；stop 跳过后项。实际首流取消 + stop：cancelled 后跳过后项；跳过项身份和任务结论为 null。
- 五个验证批次的十个实际启动项均使用保存的 case / evidence 离线复验，保持原结论；宿主 childClosed=true、forceStopped=false、写线程已退出，十个专用 PID 查询均不再存在。

首次旧提示批次的路径过时用例先列目录，未实际读取旧路径，答案正确但必要证据不足，保留为 unevaluable。任务说明明确“先尝试引用路径再选择替代文件”后，新批次通过，旧日志和快照未改。实际模型结果、合成回归和人工中断注入分别记录，不据此报告成功率或成本变化。详见 [批次运行](batch-runner.md) 与 [记录 015](changes/2026-10-18-015-m3-4-sequential-batches.md)。

## M3.3 历史修复验证（2026 年 10 月 18 日）

- `npm.cmd run test:python`：获准环境 58 项通过（原 51 + 新 7）；阻塞响应下超时 / 首流取消可触发清理并收回进程与写线程，完整 Unicode 返回、写入错误分别验证。
- `npm.cmd test` / `npm.cmd run check`：42 项 / 28 个 JS 文件通过；Python compileall 通过。
- `python -m scripts.smoke_bridge`：获准环境实际 Cordis / Tools 注册、fork IPC 与 Python 状态四次请求通过，不调用模型。
- 新版 stale-path 用例的根目录 / docs 两种合成轨迹均经过原记录器及 fresh inspect，评测 passed；错误工具、列表不含目标、isError 和缺结果反例不能通过；版本 1 仍拒绝空参数。
- 原审查记录 013 的一秒预算 / 大响应复现现在保留 intervention=timeout、stdinWriterStopped=true，并归 timed_out；目标进程在清理宽限内自行退出，未强停。新增阻塞回归另用短清理宽限验证实际强停。
- 三次历史模型执行以各自 case.json / evidence.json 离线复验，两个成功仍 passed，取消保持 cancelled / complete / unevaluable。本批没有新的模型调用，也未重复旧的输出子进程回归；其历史结果保留。

实现及兼容说明见 [修复记录 014](changes/2026-10-18-014-m3-3-review-fixes.md)。下一步恢复 M3.4 入口。

## M3.3 历史复查（2026 年 10 月 18 日）

28 文件语法、42 项 Node、获准环境 51 项 Python 和无模型真实桥接四次请求均复验通过；旧成功 / 取消轨迹离线复验保持原分类。本次未重新调用模型。新增两项可复现审查发现：大文本同步写回阻塞监督循环、根目录发现轨迹被用例误拒绝。当时的结论是先修这两项再进入 M3.4；随后本批修复见上节及记录 014，历史问题和复现保留。复现与边界见 [审查记录 013](changes/2026-10-18-013-m3-3-review.md)。

## M3.3 原验收验证（2026 年 10 月 18 日）

- `npm.cmd run check`：28 个 JavaScript 文件通过；`npm.cmd test`：42 项通过。
- `npm.cmd run test:python`：获准环境 51 项通过；首次沙箱强停权限失败保留为验证限制，复验后通过。
- `python -m scripts.smoke_bridge`：真实 Cordis / Tools 注册、fork IPC 与 Python 状态完成四次请求，不调用模型；工具体直接调用，不代表 Agent 循环验证。
- `python -m dsh_eval --case fixtures/evaluation/stale-path.case.json --run`：passed / completed / complete；43 条、54879 字节。
- `python -m dsh_eval --case fixtures/evaluation/retry-read.case.json --run`：passed / completed / complete；37 条、50862 字节。
- 同一 retry-read 入口加 `--cancel-after-stream`：cancelled / complete / unevaluable，断言 not_run。上述三个宿主 childClosed=true、forceStopped=false，专用 PID 查询均已退出。
- `npm.cmd run smoke:host`：六条组件事件通过；`npm.cmd run check:output`：三种真实子进程场景通过。Python compileall 通过。

真实任务和子进程验收在获准环境执行；首次状态化运行沙箱 fork EPERM，没有算作通过。两个成功样例各一次，不是通过率估计；没有新增统计、批次或完整会话恢复能力。详见 [修改记录 012](changes/2026-10-18-012-m3-3-stateful-tools.md) 与 [桥接协议](stateful-tools.md)。

## M3.2 历史验证

2026 年 10 月 17 日在项目根目录执行，模型场景在获准环境运行：

| 命令或操作 | 结果 | 验证边界 |
| --- | --- | --- |
| `npm.cmd run check` / `npm.cmd test` | 25 个 JS 文件 / 39 项测试通过 | 新增 headless 协议测试，原录制器保持不变 |
| `npm.cmd run test:python` | 获准环境 44 项通过（原 30 + 新 14） | 版本兼容、实际文件准备、真实子进程监督 / 强停、合成路由反例；不触发模型调用 |
| `python -m dsh_eval --case fixtures/evaluation/live-read.case.json --run` | passed / completed / complete / passed；25 条、42626 字节 | 实际 read 的 file_path 参数、结果、答案和结束均满足；实际配置来自 request/header |
| 同入口，明确不存在的 `--host-modules` | runtime_error / unverified / unevaluable | 无录制和会话 ID，保持 null，未调用模型 |
| 同入口，用例副本 provider 改为未注册值 | NO_ADAPTER，Harness 退出 1；runtime_error / complete / unevaluable | 路由错误，不计普通任务断言失败 |
| 同入口，用例副本 timeoutSeconds=2 | timed_out、aborted/user、complete、unevaluable | 本次在流 chunk 前超时，IPC 停止并正常封存；不是 token 上限 |
| 同入口加 `--cancel-after-stream` | cancelled、aborted/user、complete、unevaluable | 真实请求流 chunk 后程序化取消，不保证已执行工具 |
| 对正常、路由、超时、取消的专用子进程 PID 查询 | 均已退出，host childClosed=true | 当前受控任务的进程清理；未推定任意外部工具树和其他平台 |
| `npm.cmd run smoke:host` / `npm.cmd run check:output` | 6 条组件事件 / 三种真实输出子进程回归通过 | 后者在获准环境执行 |
| `python -m compileall -q dsh_eval test/test_runner.py test/test_evaluation.py` | 通过 | Python 语法 |

首次 fork 受沙箱 EPERM 限制，不能计为真实任务通过；一项强停测试因沙箱拒绝终止进程树失败，获准环境重跑通过。首次正常任务 fixture 把工具参数写成 path，录制 / 答案正确但断言证据不足；修正为实际 file_path 后新运行通过，旧结果保留。详见 [修改记录 011](changes/2026-10-17-011-m3-2-single-case-runner.md) 与 [单用例运行](single-case-runner.md)。

## M3.1 历史验证（2026 年 10 月 16 日）

2026 年 10 月 16 日在项目根目录执行：

| 命令或操作 | 结果 | 验证边界 |
| --- | --- | --- |
| `npm.cmd run check` | 22 个 JavaScript 文件通过 | 新增合成证据生成脚本；未修改 src |
| `npm.cmd test` | 36 项通过，0 失败 / 跳过 | 原有 Node 回归 |
| `npm.cmd run test:python` | 30 项通过 | 原有 6 项 + 新增 24 项；格式、断言、真实 Node inspect / 记录器与 CLI 边界 |
| `npm.cmd run demo:eval`，分别执行 `python -m dsh_eval --case <casePath> --evidence <evidencePath> --output <新结果文件>` | read-project / missing-file 均 passed，执行 completed，录制 complete，断言 passed | 两个公开合成轨迹，不是模型执行或状态化环境验收 |
| `npm.cmd run smoke:host` | 6 条人工组件事件，封存检查通过 | 真实 Cordis / SessionStore，无模型调用 |
| `npm.cmd run check:output` | 首次沙箱 spawn EPERM；获准环境复验 normal / write-error / abrupt-exit 均通过 | 真实子进程，未用 mock 替代 |

负例包括无工具结果、错误 callId、重复 / 倒序结果、答案不符、错参数 / 工具名、输入和配置不匹配、取消 / 超时 / 运行错误分类、关联错误 / 额外会话、缺结束、已知事件结构错误、任务内序号缺口、开放 / 缺失日志和旧成功后截断。进程不可用 / inspect 超时错误路径另用模拟异常验证；正反录制检查直接调用真实 Node。详见 [修改记录 010](changes/2026-10-16-010-m3-1-offline-evaluation.md)。

## M2.3 历史验证（2026 年 10 月 15 日）

2026 年 10 月 15 日在项目根目录执行：

| 命令或操作 | 结果 | 验证边界 |
| --- | --- | --- |
| `npm.cmd run check` | 21 个 JavaScript 文件通过 | 包含三个联调脚本 |
| `npm.cmd test` | 36 项通过 | 录制器等既有功能回归 |
| `python -m unittest discover -s test -p 'test_*.py'` | 6 项通过 | 错误字段、无真实读取结果、错误 callId、失败读取、结果顺序及取消原因等检查 |
| `npm.cmd run demo` 与对本次目录执行 inspect | 8 条模拟事件，inspect 0 | 没有模型调用 |
| `npm.cmd run smoke:host` | 6 条人工组件事件，卸载后检查通过 | 真实组件，不是模型任务 |
| `npm.cmd run check:output` | normal / write-error / abrupt-exit 通过 | 获准环境执行真实子进程，既有 0 / 1 / 2 边界 |
| `npm.cmd run live:prepare` | CLI 实际安装独立 headless / web profile | 本地 link、离线安装；现有 profile 未修改 |
| `npm.cmd run live:run -- <check-dir> read` | 实际 read 返回字段；25 条、43312 字节、sealed、inspect 0 | 最终版的单次受控真实任务 |
| 同入口 `missing` | 工具 isError 后模型报告缺失；25 条、42651 字节、sealed、inspect 0 | 工具失败不等于任务失败 |
| 同入口 `cancel` | Harness 退出 1，aborted/user；19 条、36230 字节、sealed、inspect 0 | 首个真实流 chunk 后程序化取消，不是页面手动点击 |
| 同入口 `kill` | 专用子进程 SIGKILL；16 条、35430 字节、recording、inspect 2 | 操作系统强停本次进程，没有断电实验 |
| 同入口 `web`，页面提交读取任务，终端输入 `stop` | 页面返回正确字段；25 条、49741 字节、sealed、inspect 0 | 控制插件先停止 Agent，再请求官方启动器关闭 |
| 对五个明确启动目录分别执行 `python scripts/verify_live.py <launch-dir>` | 均返回 verified true | 重新 inspect 后检查固定场景证据，不是模型通过率 |
| 截断已通过 read 日志的副本，保留旧成功报告后复验 | Python 拒绝 | 原始日志未改；旧报告不能掩盖磁盘损坏 |

首次 Node fork 在沙箱报 EPERM，获准环境执行后才取得真实证据。首次取消 / 强停触发器误用了事件参数形式，未命中；修正为 `{ agent, frame }` 后重新验证，不将之前的正常结束当作取消或强停通过。详见 [修改记录 008](changes/2026-10-15-008-m2-3-live-integration.md)。

## 历史验证（2026 年 10 月 12 日）

2026 年 10 月 12 日在项目根目录执行：

| 命令 | 结果 | 验证边界 |
| --- | --- | --- |
| `npm.cmd run check` | 通过，18 个 JavaScript 文件 | 语法检查 |
| `npm.cmd test` | 36 项通过，0 失败、0 跳过 | 原有 18 项持续通过；新增 1 项容量配置及 17 项完整性测试，不是模型任务数 |
| `npm.cmd run demo` | 通过，8 条模拟事件 | 未调用模型 |
| `npm.cmd run inspect -- --run 'runs/b0a3e7e4-df5a-43cc-bec6-2087dc028c48'` | 退出码 0，sealed，8 条，2073 字节 | 本次模拟输出的字节与状态一致 |
| `npm.cmd run smoke:host` | 通过，6 条事件且卸载后 inspect 为 0 | 固定版本真实组件；未执行真实工具或调用模型 |
| `npm.cmd run check:output` | 沙箱内 spawn EPERM；获准沙箱外运行后通过 | 正常 / 磁盘失败 / 未关闭直接退出，inspect 分别为 0 / 1 / 2 |

本次通过的组件批次为 `runs/host-smoke/d3188c8d-caca-4d81-98de-8a2e832adfa1/79e29e71-d057-4bc5-b2ec-ae7f328ebaf0/`，子进程检查批次为 `runs/output-check/cecb5448-e719-420c-9cbe-bc273af1067c/`。这些原始输出已被 Git 忽略，不作为公开夹具依赖。

历史验证继续保存在 [修改记录 004](changes/2026-10-11-004-m2-1-output-config.md)。本批修正一个历史判断：旧 `ctx.on("dispose")` 未在 Cordis 4.0.4 卸载时执行关闭，旧组件检查只验证了 flush 后事件内容，没有验证真正关闭。2026 年 10 月 12 日增加卸载后状态断言后复现，改为 `ctx.effect()` 清理并验证 sealed。Cordis 仍会捕获清理错误，宿主卸载完成仍不能代替 inspect。详见 [修改记录 006](changes/2026-10-12-006-m2-2-recording-integrity.md)。

## 已知限制

- 仅记录新增事件，不补齐加载前、恢复会话或 fork 历史；不是完整会话备份或确定性重放系统。
- `runId` 是一次记录器启动批次；M3.1 用独立 caseRunId 表示一次用例执行并显式关联会话。inspect 的 complete 表示找到的片段通过一致性检查，不表示任务成功。
- record 返回 true 只表示入队；flush 和 sealed 都没有 fsync 或断电可靠保证。写入失败也可能导致 failed 状态无法保存，此时保留 recording、缺失或损坏状态均不接受为完整。
- 新格式可发现保留清单中登记的整对会话文件缺失；旧格式没有成员集合，仍无法检测这类删除，报告明确覆盖未知。SHA-256 不是签名，清单、版本、日志和摘要同时改写或整个运行目录删除均不在检测保证内。
- 检查器不提供在线一致快照，应检查停止写入后的目录或稳定副本；开放检查点之后的完整追加允许存在，但残缺末行仍会报告损坏。
- 队列上限只计算待写文本字节，不涵盖序列化临时对象、会话状态或系统缓存。没有日志轮转、会话淘汰或性能基准。
- 状态替换验证限定当前 Windows 本地文件系统；没有验证所有网络盘、占用行为或操作系统强杀、断电场景。
- 固定组件检查、真实 headless 和 Web 验证分别记录；本批只证明上述独立 profile 与固定任务。原有自定义模型配置没有导入测试 profile。
- M2.3 Web 基线仍使用测试专用 IPC；033 另行验证 Windows 当前 CLI 的页面实际取消、普通 ConPTY Ctrl+C 清理及处理中断。033 旧取消样本缺工作区观测，034 已用一个新取消任务补齐匹配 / 实际读取，旧证据仍未知；desktop / SDK、其他平台 / 版本仍未验证。
- `scripts/verify_live.py` 仍限定 M2.3 固定 fixture。`dsh_eval` 的 --run 已实现受控单会话单任务 headless；离线入口仍不执行环境 / 预算。M3.3 / M3.4 已补桥接和顺序批次，M4 已实现重复统计和单实验离线报告，M5 已实现本地浏览；并发、崩溃续跑及跨实验合并尚未实现。浏览是保存文件的读取，不是实时一致快照或新复验。指标只反映闭合录制和已报告 usage，运行耗时不是纯模型延迟，缺失与费用不补零。配对覆盖不足有选择偏差，没有置信区间、显著性或真实多配置表现结论。
- 版本 2 由真实适配器采集请求路由 / 退出 / 干预，离线再核对日志请求头；来源字段本身不是签名。准备和清理另有期限，不把任务 timeoutSeconds 说成总退出硬上限，不支持 token / 步骤预算；本批只验证 Windows 与当前组件。

## 后续里程碑

| 阶段 | 状态与内容 | 验收依据 |
| --- | --- | --- |
| M1 | 已完成当前组件范围的实时轨迹记录 | 原有 6 项功能测试及组件检查 |
| M2.1 | 已完成输出与配置，`0.1.1` | 历史 18 项测试及两种真实子进程输出检查 |
| M2.2 | 已完成状态、容量和 inspect，`0.1.2` | 36 项测试、真实组件封存及三种子进程场景 |
| M2.3 | 已完成 Web / headless 受控联调基线 | 实际安装、字段读取与缺失文件响应、真实流取消、专用进程强停；Node inspect + Python 固定证据检查 |
| M3.1 | 已完成：Python 版本化用例与结果、caseRunId、离线证据断言和三维分类 | 两个合成用例、正反例及真实 Node inspect；损坏 / 开放日志不能判任务通过 |
| M3.2 | 已完成：Python 单用例受控 headless、初始文件、实际配置与预算事实、版本 2 证据 | 真实读取 passed；启动 / 路由错误、超时 / 取消、专用子进程退出分别验证 |
| M3.3 | 已完成当前范围；复查两项问题已修复 | 原有状态 / 宿主 / 模型样例有效；新增管道与发现方式回归、58 项 Python 及无模型真实桥接通过，见记录 014 |
| M3.4 | 已完成当前范围：Python 顺序批次、输入冻结与环境隔离、结果清单 | 真实恢复批次与故障重置通过，实际路由错误继续 / 停止及取消停止通过，73 项 Python 回归 |
| M4.1 | 已完成当前范围：Python 重复试验、样本 / 配置关联、明确分母与已观测指标 | 95 项 Python、无模型真实桥接、两个真实重复样本及离线复验通过 |
| M4.2 | 已完成当前范围：单实验离线复验、配置配对与 JSON / Markdown，公开不确定性边界 | 17 项新增 / 全量 117 Python；合成双配置重复与历史四真实样本报告通过，原证据摘要不变 |
| M5 | 当前范围已实现；审查及云端路径兼容修复已完成验收 | `e47de36` 的 Windows CI 全部通过：134 Python / 44 Node / 31 文件语法、compileall 和 demo；历史页面验证保留 |
| M6.1 | 当前范围完成，登记可靠性两项审查问题已修复 | 原 14 新 Node / 3 新 Python 与历史验证保留；修复新增七 Node、完整 65 Node / 137 Python、33 文件语法、真实组件与获准子进程 / 五轮 600 会话通过；本批云端未运行 |
| M6.2 | 当前范围完成，任务入口录制配置传递已修复 | 原资源 / 输出验收保留；配置修复新增四 Node / 六 Python、完整 79 Node / 144 Python、真实配置合并和三组无模型组件验证通过；本批云端未运行 |
| M6.3 | 单配置范围及三项审查修复完成；双配置 / 重复扩展待定 | 原 10 个真实任务结果保留；028 无模型回归 163 Python / 79 Node / 36 文件语法，旧录制按新断言及原冻结断言分别复验通过 |
| M6.4 | Windows / 当前 CLI 历史交付保留；036 两项修复及 038 CI 路径缺口本地已验证，新提交云端待验收 | 038 完整202 Python、39生命周期、compileall与独立三场景通过；036的85 Node / 41 JS为历史，原103c090云端失败不覆盖 |

## 文档导航

- [M3 与后续计划](plans/m3-regression-evaluation.md)：M3 至 M5 已实现范围、云端验收和按需后续事项。
- [M6 方案](plans/m6-reliability-validation.md)、[运行会话清单](run-manifest.md) 与 [录制资源边界](recorder-resources.md)：当前格式、写入 / 检查顺序、字节限制、单配置验收和后续 Web 范围。
- [Web 生命周期](web-lifecycle.md)：M6.4 合成与真实入口、采集协议、进程 / 页面证据及覆盖局限。
- [结果浏览](result-browser.md)：本地入口、保存结论的边界、文件范围、分页和无模型 CI。
- [重复试验](experiments.md)：显式配置、重复编号、分母与指标覆盖及运行入口。
- [配置报告](configuration-reports.md)：冻结输入与来源 / 实际路由核对、独立复验、配对差值和不确定性。
- [固定评测集](core-evaluation.md)：10 个用例、显式模型规模、单配置首次验收、分母 / 用量和复验结果。
- [单用例运行](single-case-runner.md) 与 [修改记录 011](changes/2026-10-17-011-m3-2-single-case-runner.md)：当前真实执行入口与验证依据。
- [M3.1 评测格式](evaluation-format.md) 与 [修改记录 010](changes/2026-10-16-010-m3-1-offline-evaluation.md)：当前离线入口与验证依据。
- [M2.3 真实任务联调](changes/2026-10-15-008-m2-3-live-integration.md)：本批安装、真实模型和生命周期证据，以及固定 Python 检查范围。
- [Python 评测分工决策](changes/2026-10-14-007-python-evaluation-plan.md)：已明确规划，未新增 Python 功能；现有 inspect 和运行方式保持不变。
- [M2 方案](plans/m2-reliable-recording.md)
- [架构与技术取舍](architecture.md)
- [修改记录](../CHANGELOG.md)
- [修改记录模板](templates/change-record.md)

公开文档足以接续开发；本机交接和个人准备保存在被忽略的私人目录。隔离说明见 [修改记录 005](changes/2026-10-11-005-public-repository-filter.md)。
