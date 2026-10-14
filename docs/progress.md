# dsh-eval-lab 开发进度

截至 2026 年 10 月 15 日（Asia/Shanghai），插件版本 `0.1.2`。M2.3 的独立 profile 安装、Web / headless 真实模型任务、程序化取消和专用进程强制停止已验证。新增 Python 固定 fixture 证据检查；通用 M3 自动评测尚未实现。本批改动尚未提交。

同日维护后续路线：下一批先做 M3.1 用例格式与离线断言，再推进单用例运行、状态化工具桥接和顺序批次。见 [M3 与后续计划](plans/m3-regression-evaluation.md)。本次计划维护只改文档，以下功能验证仍来自 M2.3 批次。

## 项目目标

围绕 DeepSeek Harness 构建 Agent 行为回归测试工具：对固定任务与环境运行 Agent，检查工具行为和最终结果，比较配置。当前成果是录制与一致性检查层，不能据此报告模型任务通过率、成本或性能提升。

## 当前基线

| 项目 | 当前状态 |
| --- | --- |
| 插件版本 | `0.1.2`；本批不改变录制器及日志协议 |
| 当前开发分支 | `20261014/feat/m2.3-real-model-integration` |
| 已核实基线提交 | `f459945` 为 M2.2，`4c8982f` 为语言规划；M2.1 为 `f92733b`，第一版为 `8c1b53a` |
| 开发语言 | 宿主与生命周期继续 JavaScript；M2.3 固定任务证据检查已使用 Python |
| 实测环境 | Node.js `v24.14.0`、npm `11.9.0`、pnpm `11.25.0`、Python `3.12.0`、Windows |
| 真实组件基线 | DSH SessionStore `0.2.0-rc.2`，Cordis `4.0.4` |
| 最新复核日期 | 2026 年 10 月 15 日，Asia/Shanghai |
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
| 通用任务断言、状态化工具环境、重复试验和指标比较 | 尚未实现 | M3 及后续 |

## 最新验证

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
- `runId` 是一次记录器启动批次，尚不是一次评测编号。inspect 的 complete 表示找到的片段通过一致性检查，不表示任务成功。
- record 返回 true 只表示入队；flush 和 sealed 都没有 fsync 或断电可靠保证。写入失败也可能导致 failed 状态无法保存，此时保留 recording、缺失或损坏状态均不接受为完整。
- 没有运行级会话清单，删除整对会话文件无法检测；SHA-256 不是签名，不能抵御日志与摘要同时被改写。
- 检查器不提供在线一致快照，应检查停止写入后的目录或稳定副本；开放检查点之后的完整追加允许存在，但残缺末行仍会报告损坏。
- 队列上限只计算待写文本字节，不涵盖序列化临时对象、会话状态或系统缓存。没有日志轮转、会话淘汰或性能基准。
- 状态替换验证限定当前 Windows 本地文件系统；没有验证所有网络盘、占用行为或操作系统强杀、断电场景。
- 固定组件检查、真实 headless 和 Web 验证分别记录；本批只证明上述独立 profile 与固定任务。原有自定义模型配置没有导入测试 profile。
- Web 使用测试专用 IPC 正常关闭，尚未验证页面手动取消、普通 Web 进程信号关闭、desktop 或 SDK。
- Python 验证器只接受 M2.3 的单会话固定 fixture 和版本 1 报告，不是通用任务评测引擎；尚无实时跨语言工具桥接。

## 后续里程碑

| 阶段 | 状态与内容 | 验收依据 |
| --- | --- | --- |
| M1 | 已完成当前组件范围的实时轨迹记录 | 原有 6 项功能测试及组件检查 |
| M2.1 | 已完成输出与配置，`0.1.1` | 历史 18 项测试及两种真实子进程输出检查 |
| M2.2 | 已完成状态、容量和 inspect，`0.1.2` | 36 项测试、真实组件封存及三种子进程场景 |
| M2.3 | 已完成 Web / headless 受控联调基线 | 实际安装、字段读取与缺失文件响应、真实流取消、专用进程强停；Node inspect + Python 固定证据检查 |
| M3.1 | 下一批，未实现：Python 用例格式、caseRunId、离线证据断言和结果分类 | 合成轨迹正反例；先复用 inspect，损坏 / 开放日志不能判任务通过 |
| M3.2 | 未实现：Python 驱动单用例受控 headless 运行 | 正常真实任务闭环；启动错误、超时 / 取消正确分类与清理 |
| M3.3 | 未实现：Python 状态化工具环境核心与 JavaScript 实时桥接 | 状态单测、真实宿主桥接及路径过时 / 工具失败后恢复两个真实模型用例分别验证 |
| M3.4 | 未实现：Python 顺序批次回归、环境隔离与结果清单 | 新会话和 caseRunId 独立，初始状态重置，逐项关联配置与录制证据 |
| M4 | 优先 Python 实现多次重复配置比较、指标汇总与报告 | 报告样本数、配置和原始结果；缺失指标保持缺失 |
| M5 | 可视化与持续集成 | 浏览用例与结果，自动执行检查 |

## 文档导航

- [M3 与后续计划](plans/m3-regression-evaluation.md)：下一批入口、分批验收、结果分类，以及 M4/M5 和渠道 / 录制加固待办；均未实现。
- [M2.3 真实任务联调](changes/2026-10-15-008-m2-3-live-integration.md)：本批安装、真实模型和生命周期证据，以及固定 Python 检查范围。
- [Python 评测分工决策](changes/2026-10-14-007-python-evaluation-plan.md)：已明确规划，未新增 Python 功能；现有 inspect 和运行方式保持不变。
- [M2 方案](plans/m2-reliable-recording.md)
- [架构与技术取舍](architecture.md)
- [修改记录](../CHANGELOG.md)
- [修改记录模板](templates/change-record.md)

公开文档足以接续开发；本机交接和个人准备保存在被忽略的私人目录。隔离说明见 [修改记录 005](changes/2026-10-11-005-public-repository-filter.md)。
