# 修改记录 008 M2.3 真实任务与生命周期联调

日期：2026 年 10 月 15 日，Asia/Shanghai。类型：配置 / 测试 / 文档。插件版本：`0.1.2`。相关 Git 提交：尚未提交。

## 问题与目标

此前 36 项测试与真实 Cordis / SessionStore 检查只覆盖人工事件，没有实际 profile 安装、真实文件工具及模型任务证据。本批完成 Web / headless 的受控联调基线：关联用户输入、实际工具调用与结果、模型答案和结束原因，并区分任务取消、录制封存与进程强停。

## 文件修改

| 文件 | 修改前 | 修改后 | 原因 |
| --- | --- | --- | --- |
| `fixtures/live-read/README.md` | 无固定真实任务输入 | 提供 projectName 字段和只读任务输入 | 不让模型修改插件源码 |
| `scripts/prepare-live.js` | 只有组件检查入口 | 核对版本，经实际 CLI 离线安装独立 Web / headless profile | 验证真实安装且保留已有 profile |
| `scripts/run-live.js` | 无真实进程联调入口 | 五种模式、原始输出、版本化报告、退出后 inspect | 复现实测生命周期事实 |
| `scripts/fixtures/live-control.js` | 无测试控制适配 | IPC 通知真实流、调用 Agent 取消及启动器关闭 | Windows 正常关闭与强停分别控制 |
| `scripts/verify_live.py` | 无任务内容验证 | 重新 inspect 后检查固定任务证据 | 将新增离线断言放在 Python |
| `test/test_live_verify.py` | 无 Python 断言边界测试 | 6 项正反例测试 | 拒绝只答对字段但没有读取证据等假阳性 |
| `package.json` | 只有既有录制检查命令 | 增加 live:prepare、live:run、test:python | 提供可复现入口，版本保持 0.1.2 |
| 使用说明、方案、架构、进度与修改索引 | M2.3 未验证、Python 仅规划 | 记录本批实现与仍未验证的渠道 | 保留历史结果并更新当前状态 |

## 实现与技术取舍

1. 复用本机 DSH `0.2.0-rc.2`、dsh-session `0.2.0-rc.2` 和 Cordis `4.0.4`，不升级运行时。CLI 插件管理实际执行 `plugin --profile <mode> add link:<项目目录> --offline --ignore-scripts --store-dir <本批目录>`。生成的 profile 确认包含 `dsh-eval-lab` bundle，两个 profile 均使用独立 home 和 pnpm store。
2. 凭据配置只引用启动时原 home 的 `.credentials.yaml`，不复制密钥，不将其写入环境变量。测试使用宿主默认 `deepseek-official / deepseek-flash`，原 Web profile 未设置自定义模型配置；不把该准备脚本称为任意模型配置迁移工具。只读策略限制测试文件写入；关闭额外的模型标题请求与遥测。
3. 每次模式启动都创建独立 launch-id，保存 stdout、stderr、resultFormatVersion 1 报告及原有 JSONL / status。setup 使用 setupFormatVersion 1；插件的 run / JSONL / status 协议与版本不变，main.py 保留。
4. headless 使用官方 CLI 完成任务和关闭。Web 通过测试专用 IPC，先 cancel 活动 Agent、等待 whenIdle 和 flush，再请求 appExit。Windows child.kill 的 SIGINT 不作为优雅关闭使用；强停仅针对父脚本自己创建的专用进程。控制插件不进入发布 bundle。
5. cancel / kill 均等待真实 `agent/assistant-stream` 的首个 chunk；chunk 可能是块边界，不代表已经产生正文或执行文件工具。取消必须有 aborted/user 和退出 1，强停必须有 SIGKILL 且 inspect 非 0。超时不能冒充预期强停。
6. JavaScript 只判断进程、协议与录制生命周期。Python 先重新调用现有 Node inspect，再核对固定 fixture 的用户输入、参数、callId 关联结果、答案与结束顺序。实际工具名从事件读取，未硬编码演示中的 read_file。只处理单会话固定任务，通用用例管理与批次调度仍留在 M3。

## 验证

环境：Windows、Node.js `v24.14.0`、npm `11.9.0`、pnpm `11.25.0`、Python `3.12.0`。面向用户的批次日期按 Asia/Shanghai 记录；原始事件时间保留宿主实际值。

| 命令或操作 | 结果 | 证明的范围 |
| --- | --- | --- |
| `npm.cmd run check` | 21 个 JS 文件通过 | 联调入口语法及既有文件 |
| `npm.cmd test` | 36 项通过 | 录制、配置、完整性等既有回归 |
| `python -m unittest discover -s test -p 'test_*.py'` | 6 项通过 | 工具名不固定；无结果、错 callId、失败读取、错误字段、错误顺序、错误取消原因不能通过 |
| `npm.cmd run demo`，对本次 demo 目录执行 inspect | 8 条、2073 字节，inspect 0 | 模拟数据回归，无模型调用 |
| `npm.cmd run smoke:host` | 6 条真实组件人工事件通过 | 没有真实模型调用 |
| `npm.cmd run check:output` | normal / write-error / abrupt-exit 通过 | 获准环境真实子进程的既有 0 / 1 / 2 结果；abrupt-exit 仍为 process.exit 场景 |
| `npm.cmd run live:prepare` | 两个独立 profile 安装通过 | CLI 实际安装与版本兼容性；未改原 profile |
| 五种 live:run 模式及各自 Python verify_live.py | 以下最终版证据均通过 | 真实模型与专用进程，和模拟 / 组件检查分开 |
| 复制已通过的 read 启动目录，截断副本末行，保留旧成功快照后执行 Python 检查 | 拒绝，提示 Recording did not pass fresh inspect | 证明重新检查磁盘，不信任旧报告；原始日志未改 |
| `npm.cmd run test:python` | 同样 6 项通过 | 新增 npm 入口可复现 |
| Markdown 本地链接与 Git 忽略检查、`git diff --check` | 16 份公开和 2 份私人 Markdown 的 47 个本地链接有效；diff 检查通过；runs / private-notes 被忽略且无已跟踪内容 | 公开链接不依赖运行目录或私人材料 |

最终版联调目录：`runs/live/110a2d07-3788-4483-9177-7a43ff5095fb`。在项目根目录实际执行 `npm.cmd run live:run -- 'runs/live/110a2d07-3788-4483-9177-7a43ff5095fb' <mode>`；对下表每个明确的 `<mode>/<launch-id>` 目录执行 `python scripts/verify_live.py <该启动目录>`，均返回 verified true。

| 模式 | launch-id / run-id | 最终结果 |
| --- | --- | --- |
| read | `eef68906-8333-4857-ae5f-de0520af2aef` / `951b31dc-2d26-473a-94f4-6d7d47be4fc0` | 实际 read，callSeq 17 → resultSeq 18 → answerSeq 22；答案 dsh-eval-live-fixture；completed；25 条、43312 字节、sealed、inspect 0 |
| missing | `c9c21f17-39cb-44e9-9d6b-c625cb0b1c82` / `9934a395-b698-40c2-9445-8028c2f9927c` | 实际 read 返回 isError，后续回答文件不存在；25 条、42651 字节、sealed、inspect 0 |
| cancel | `9ec9facd-7232-4bfc-b310-b157dba252e1` / `08ebe2fd-488b-4617-92aa-219520a66c9a` | 真实流后程序化取消；aborted/user；Harness 退出 1；19 条、36230 字节、sealed、inspect 0 |
| kill | `197d6651-bf82-432e-adfa-97141dec9975` / `5c230bee-32b1-4fc6-a3e6-22e2549ee43f` | 专用进程 SIGKILL；16 条、35430 字节、recording、inspect 2 |
| web | `8aa00d0c-0586-46fe-a206-04c152cb7003` / `80fa4b77-68f2-4c18-af73-b201f1b049bb` | 页面提交读取任务并看到正确答案，终端输入 stop；实际 read；25 条、49741 字节、sealed、inspect 0 |

Web 与 headless 的读取任务输入均为 README 中的完整英文任务，用户输入、工具结果和答案已在 Python 中关联；工具实际名为 read，其他探索调用不作为唯一正确工具名。Web 完成页面截图只保存在被忽略的本次启动目录，不作为公开资料依赖。

首次 Node fork 在沙箱内报 spawn EPERM，未计为通过；获准环境执行同一入口后取得真实结果。首次 cancel / kill 触发器把 `{ agent, frame }` 当作两个位置参数，未触发干预，两次任务正常完成；脚本返回检查失败。修正接口后重新验证，表中只列最终版符合条件的证据，旧原始输出保留。

## 风险与后续

- 本批完成的是上述版本、默认模型路由和固定任务的 Web / headless 联调基线；不能据此报告模型通过率、成本降低或性能提升。
- Web 正常关闭验证使用测试 IPC；普通 Web 进程直接信号退出、页面手动点击停止、desktop 和 SDK 未验证。程序化取消确实在真实模型流中执行。
- OS 强停仅证明本次专用进程的开放状态没有被接受；没有断电实验、fsync 或崩溃恢复承诺。inspect complete 与任务正确分别检查。
- 原始轨迹与 Web stdout 可能含会话内容、本地认证 URL，均留在 runs；公开文档不链接这些文件。准备脚本不复制凭据。
- Python 检查器限定一个会话和固定 fixture，没有通用用例格式、状态化工具环境、批次调度、重复统计或实时跨语言工具桥接。下一批进入 M3 设计与实现。

## 面试讨论点

组件接入检查为何不能替代真实模型端到端证据；为何 headless 退出 1 的取消任务仍可拥有有效 sealed 片段；如何用 callId 关联真实文件结果与答案；为何 Windows 强停和正常关闭要分别控制；为何 Python 重新 inspect 而不信任报告中的旧检查快照。

## 文档同步

已同步 README、开发进度、架构、M2 方案与 CHANGELOG；本机存在的私人面试材料及交接说明同步本批状态。既有历史验证记录保留；本批不自动提交或推送。
