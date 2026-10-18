# dsh-eval-lab 开发进度

截至 2026 年 10 月 18 日（Asia/Shanghai），插件版本 `0.1.2`。M3.4 已实现 Python 顺序批次、全部输入快照、逐次独立会话 / 环境、进度与结果清单、继续 / 停止策略。真实三项恢复批次 passed，重复读取故障重置和实际异常策略分别验证；详情见 [记录 015](changes/2026-10-18-015-m3-4-sequential-batches.md)。已核实 M3.3 审查修复提交 `3ce645d`，本批尚未提交。

下一批为 M4.1 重复试验与指标口径；剩 M4、M5 两个主要阶段，按 M4.1 / M4.2 / M5 拆为三批。渠道补充和录制加固另按需求安排。见 [M3 与后续计划](plans/m3-regression-evaluation.md)。

## 项目目标

围绕 DeepSeek Harness 构建 Agent 行为回归测试工具：对固定任务与环境运行 Agent，检查工具行为和最终结果，比较配置。当前成果包含录制检查、离线断言和受控单用例真实闭环，不能据此报告模型任务通过率、成本或性能提升。

## 当前基线

| 项目 | 当前状态 |
| --- | --- |
| 插件版本 | `0.1.2`；本批不改变录制器及日志协议 |
| 当前开发分支 | `20261015/feat/eval-workflow` |
| 已核实基线提交 | `3ce645d` 为 M3.3 审查修复，`302855f` 为 M3.3 主体；`31a24fa` 为 M3.2；`868529d` 为 M3.1；`4f54ddf` 为 M2.3 与路线，经 `de86bd2` 合并；`f459945` 为 M2.2 |
| 开发语言 | JavaScript 宿主接入和生命周期；Python 已实现离线断言、状态化环境及真实单用例 / 顺序批次调度 |
| 实测环境 | Node.js `v24.14.0`、npm `11.9.0`、pnpm `11.25.0`、Python `3.12.0`、Windows |
| 真实组件基线 | DSH SessionStore `0.2.0-rc.2`，Cordis `4.0.4` |
| 最新复核日期 | 2026 年 10 月 18 日，Asia/Shanghai |
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
| 容量保护 | 全录制器 UTF-8 待写入字节上限，默认 16 MiB；超限使受影响会话失败 | `src/recorder.js` |
| 离线检查 | 流式解析及原始字节 SHA-256，核对身份、计数、序号边界和摘要；退出码 0 / 1 / 2 | `src/inspect.js`、`scripts/inspect.js` |
| 序号与捕获范围 | 严格递增非负安全整数；允许非零起点，报告缺口；保持 `live-events-only` | 记录器及检查器 |
| 模拟演示 | 8 条模拟事件正常封存并通过 inspect，无模型调用 | `scripts/demo.js` |
| 真实组件接入 | 6 条人工事件原样导出，检查点仍开放，卸载后 sealed 并通过 inspect | `scripts/lib/host-smoke.js` |
| 未关闭直接退出 | 独立录制器子进程 flush 后 `process.exit(0)`，inspect 返回 2 | `scripts/fixtures/output-child.js` |
| Web / headless 真实模型联调 | 实际安装、文件读取及字段答案、工具失败后响应、取消、强停已验证 | `scripts/prepare-live.js`、`scripts/run-live.js` |
| 固定 fixture 证据检查 | Python 先重新 inspect，再核对工具结果、答案及结束事实；6 项测试通过 | `scripts/verify_live.py` |
| desktop / SDK、Web 页面手动取消及普通进程信号关闭 | 尚未验证 | 后续按渠道需求验证 |
| 用例加载与通用离线任务断言 | 用例、证据 / 结果版本 1 / 2；三种断言和三维结果，版本 2 额外核对实际请求路由 | `dsh_eval/`、`docs/evaluation-format.md` |
| 单用例真实驱动 | 独立 workspace / home / 新会话，真实路由、超时 / 取消、清理与新建结果；受控真实任务及异常通过 | `dsh_eval/runner.py`、`scripts/case-host.js` |
| 状态化工具环境与实时桥接 | 主体与历史真实模型样例通过；监督阻塞与目录断言过窄已修复，新增七项回归 | `dsh_eval/environment.py`、`docs/stateful-tools.md`、审查记录 013 |
| 顺序批次、重置和结果清单 | 已实现版本 1 批次 / 结果，输入冻结及独立执行，实际恢复批次和异常策略通过 | `dsh_eval/batch.py`、[批次运行](batch-runner.md) |
| 重复试验统计 / 指标比较 | 尚未实现 | M4 及后续 |

## 最新验证：M3.4（2026 年 10 月 18 日）

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
- 没有运行级会话清单，删除整对会话文件无法检测；SHA-256 不是签名，不能抵御日志与摘要同时被改写。
- 检查器不提供在线一致快照，应检查停止写入后的目录或稳定副本；开放检查点之后的完整追加允许存在，但残缺末行仍会报告损坏。
- 队列上限只计算待写文本字节，不涵盖序列化临时对象、会话状态或系统缓存。没有日志轮转、会话淘汰或性能基准。
- 状态替换验证限定当前 Windows 本地文件系统；没有验证所有网络盘、占用行为或操作系统强杀、断电场景。
- 固定组件检查、真实 headless 和 Web 验证分别记录；本批只证明上述独立 profile 与固定任务。原有自定义模型配置没有导入测试 profile。
- Web 使用测试专用 IPC 正常关闭，尚未验证页面手动取消、普通 Web 进程信号关闭、desktop 或 SDK。
- `scripts/verify_live.py` 仍限定 M2.3 固定 fixture。`dsh_eval` 的 --run 已实现受控单会话单任务 headless；离线入口仍不执行环境 / 预算。实时 Python 工具桥接已在 M3.3 实现，M3.4 已补顺序批次；并发、崩溃续跑和重复统计尚未实现。
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
| M4 | 优先 Python 实现多次重复配置比较、指标汇总与报告 | 报告样本数、配置和原始结果；缺失指标保持缺失 |
| M5 | 可视化与持续集成 | 浏览用例与结果，自动执行检查 |

## 文档导航

- [M3 与后续计划](plans/m3-regression-evaluation.md)：M3.1 / M3.2 已完成范围，M3.4 已完成范围、M4.1 下一批入口及后续待办。
- [单用例运行](single-case-runner.md) 与 [修改记录 011](changes/2026-10-17-011-m3-2-single-case-runner.md)：当前真实执行入口与验证依据。
- [M3.1 评测格式](evaluation-format.md) 与 [修改记录 010](changes/2026-10-16-010-m3-1-offline-evaluation.md)：当前离线入口与验证依据。
- [M2.3 真实任务联调](changes/2026-10-15-008-m2-3-live-integration.md)：本批安装、真实模型和生命周期证据，以及固定 Python 检查范围。
- [Python 评测分工决策](changes/2026-10-14-007-python-evaluation-plan.md)：已明确规划，未新增 Python 功能；现有 inspect 和运行方式保持不变。
- [M2 方案](plans/m2-reliable-recording.md)
- [架构与技术取舍](architecture.md)
- [修改记录](../CHANGELOG.md)
- [修改记录模板](templates/change-record.md)

公开文档足以接续开发；本机交接和个人准备保存在被忽略的私人目录。隔离说明见 [修改记录 005](changes/2026-10-11-005-public-repository-filter.md)。
