# dsh-eval-lab 架构与技术取舍

当前版本 `0.1.2` 实现新增事件录制及离线一致性检查。插件适配宿主，记录器负责队列和封存，检查器读取磁盘证据；M2.3 已有固定 fixture 任务检查，通用任务评测仍属于 M3。

## 执行流程与模块

```text
apply(ctx, config)
  → 路径优先级解析、maxPendingBytes 校验
  → 创建 UUID 运行目录和 run.json
session/event
  → 接收时序列化、序号和容量校验
  → 会话独立 Promise 队列：recording 状态 → JSONL 追加
session/flush
  → 在选定会话队尾插入检查点状态更新 → 等待并报告错误
ctx.effect 清理
  → close 停止接收 → 排空所有队列 → 各正常会话 sealed
inspect --run <目录>
  → 元信息与状态校验 → 流式解析、原始字节摘要及前缀/最终比较
```

| 模块 | 职责 |
| --- | --- |
| `src/index.js` | Cordis 插件依赖、事件与检查点监听、`ctx.effect()` 异步关闭清理；诊断走 stderr |
| `src/config.js` | 显式目录 > 环境变量 > 主目录；选中值无效报错；容量正安全整数校验 |
| `src/metadata.js` | 从 package.json 读取版本及支持的会话组件基线 |
| `src/recorder.js` | 运行目录、会话队列、接收与写入统计、字节容量、检查点、错误和封存 |
| `src/session-status.js` | 状态文件命名及同目录临时文件、rename 替换与临时文件清理 |
| `src/inspect.js` | 只读磁盘检查，区分 complete / invalid / unverified |
| `scripts/inspect.js` | 显式 --run 参数、JSON 报告及退出码 |
| `scripts/demo.js` | 8 条模拟事件 |
| `scripts/lib/host.js` | 固定组件版本检查和加载 |
| `scripts/lib/host-smoke.js` | 真实组件事件比较、检查点状态、卸载后封存与 inspect |
| `scripts/check-output.js` | 三个真实子进程场景，检查输出和持久化证据 |
| `scripts/prepare-live.js` | 通过实际 CLI 离线安装两个独立 profile，复制受控 fixture，只引用已有凭据文件 |
| `scripts/run-live.js`、`scripts/fixtures/live-control.js` | 专用 CLI 子进程、真实流取消 / 强停、Web 停止 Agent 后退出及 inspect |
| `scripts/verify_live.py` | 先重新调用 Node inspect，再检查固定 fixture 的任务证据 |
| `test/` | 原功能、配置、组件版本及完整性边界测试 |

## 输出与数据格式

```text
<outputDir>/<runId>/
  run.json
  <sha256(sessionId)>.jsonl
  <sha256(sessionId)>.status.json
```

run.json 和 JSONL 的 `formatVersion: 1` 保持不变。run.json 新增 `statusFormatVersion: 1` 和 `maxPendingBytes`，保留插件版本、运行 ID、启动时间、捕获范围与命名规则。`captureScope` 始终为 `live-events-only`。

每条 JSONL 为 `{ formatVersion: 1, runId, sessionId, event }`，event 保留序列化的原始内容。记录器要求序列化后的 `event.seq` 是严格递增非负安全整数；不排序、不去重、不解析工具参数，不校验业务事件 schema。未知事件类型仍可记录和检查，非零起点及序号缺口不代表自动补齐历史。

独立会话状态包含：

| 字段 | 含义 |
| --- | --- |
| `statusFormatVersion` | 当前为 1，独立于 JSONL 版本 |
| `runId`、`sessionId`、`traceFile`、`captureScope` | 运行和会话身份，检查器同时核对哈希文件名 |
| `state` | recording / sealed / failed |
| `receivedCount` | 尚未失败期间的接收尝试数，含触发序列化、序号或容量失败的那次；失败后拒绝的调用不再累计 |
| `acceptedCount` | 成功进入写入队列的条数 |
| `writtenCount`、`writtenBytes` | 追加成功的条数及 UTF-8 字节数，含每条末尾换行 |
| `firstSeq`、`lastSeq` | 成功写入的首尾序号，空前缀为 null |
| `sha256` | 成功写入的原始 JSONL 字节摘要；空前缀为空字节摘要 |
| `updatedAt`、`error` | 更新时间及第一次错误的 message / code；正常状态 error 为 null |

recording 的统计只保证状态保存时的检查点前缀，可能落后于 JSONL。sealed 必须 received = accepted = written > 0，并在离线重新核对后才可接受。failed 即使留下部分可解析内容，也不能被接受为完整。

## 队列、检查点与容量

各会话在 Map 中保存队尾 Promise、错误、计数、序号及增量哈希。首次观察建立状态任务，首条 JSONL 追加前必须完成 recording 状态写入。记录在入队前转成 UTF-8 Buffer，以固定观察时内容并按真实字节记账；同步序列化仍消耗 CPU 与临时内存。

每次追加成功后更新写入统计和哈希。失败保存首次错误，后续该会话停止接收，已排队但尚未开始的写入被跳过；其他会话继续。队列捕获错误并尽力保存 failed 状态，检查点和关闭通过 AggregateError 报告。报告回调抛错不会替换原错误。

`maxPendingBytes` 是录制器级上限，默认 16 MiB。包括所有会话排队及正在追加的 Buffer；追加完成或跳过时在 finally 释放。超限的那条不入队，受影响会话失败。没有阻塞宿主等待容量的背压接口，没有进程内存总量保证。

flush 在调用时选定会话队尾插入状态写入任务，并捕获该检查点的 received / accepted 计数。状态任务在此前追加之后、此后追加之前执行，所以统计及哈希都属于同一个前缀。后续事件不属于此次等待范围；错误仍是会话级持续状态，检查点不是独立错误版本。flush 不封存，也不执行 fsync。

close 先禁止接收，然后为每个会话排队 sealed 更新；一个失败会话不妨碍其他会话封存，但整体关闭仍拒绝。重复 close 共享同一 Promise；关闭期间或之后的 flush 等待该关闭，不会把 sealed 状态重新写成 recording。

## 状态替换与宿主生命周期

状态更新先写同目录 UUID 临时文件，再 rename 到固定状态路径，最后清理临时文件。Windows 本地测试覆盖多次替换与目录占用导致的真实失败。此流程没有 fsync，也不承诺所有文件系统的原子持久性。写入 failed 本身可能失败；残留 recording、缺失或损坏状态都不能被视为完整。

2026 年 10 月 12 日真实卸载检查发现旧 `ctx.on("dispose")` 在 Cordis 4.0.4 没有执行关闭，旧测试只证明 flush 后内容一致。本批改用 `ctx.effect(() => () => recorder.close())` 显式注册所属 fiber 的清理，并验证卸载后 sealed 和 inspect 通过。普通函数 apply 还可能被该版本按构造函数执行，因此不能只依赖它返回的函数作为清理。

Cordis 卸载仍会捕获清理错误，fiber.dispose 完成不等于日志有效。宿主应先停止 Agent 事件，再卸载插件。2026 年 10 月 15 日已验证 headless 等待任务 idle / flush 后的启动器关闭；Web 由测试控制插件先 cancel、等待 idle / flush，再调用 appExit 走官方关闭。普通 Web 进程信号关闭、SDK 和桌面仍未验证。历史判断修正见 [修改记录 006](changes/2026-10-12-006-m2-2-recording-integrity.md)。

## M2.3 联调边界

准备目录为 `runs/live/<check-id>/`，`home` 包含独立 headless / web profile，`workspace` 是 README fixture 副本，`setup.json` 使用 `setupFormatVersion: 1`。安装通过匹配版本的实际 CLI `plugin add link:<项目目录> --offline --ignore-scripts`，使用独立 pnpm store。凭据配置只引用原 home 的凭据文件路径，不复制密钥，不导入原 profile 的模型配置。宿主默认路由为 `deepseek-official / deepseek-flash`。

每次启动保存 `<mode>/<launch-id>/result.json`，使用 `resultFormatVersion: 1`，包含 profile、CLI 版本、固定输入、子进程退出码与信号、干预事实、headless 协议检查和 inspect 结果。原有 run / JSONL / status 协议没有改变。stdout / stderr 与真实轨迹保存在同一启动目录下；Web stdout 可能含本地认证 URL，均不公开。

控制插件仅由专用 IPC 子进程加载，不加入分发 bundle。它按实际 `{ agent, frame }` 接口，在首个模型流 chunk 后通知父进程；取消调用 `agent.cancel({ kind: 'user' })`，强停由父进程终止自己创建的进程。Windows 的 child.kill 不作为正常 SIGINT 关闭使用；Web 的 `stop` 通过 IPC 请求停止 Agent 后 appExit。headless 有 120 秒超时，Web 正常关闭有 15 秒超时，超时强停不计为成功。

Python 固定检查器读取版本化联调报告定位明确目录，并重新调用 Node inspect，避免旧快照掩盖磁盘损坏。录制通过后核对用户输入、文件参数、callId 关联的实际工具结果、结果在答案之前、字段值和 turn/end；工具名来自事件。缺失文件要求真实 isError 和后续响应；取消检查 aborted/user；强停检查 SIGKILL 与非完整录制。它限定单会话与固定 fixture，不承担通用用例格式、批次调度或统计。

## 离线检查

检查器只读显式指定的目录，发现 JSONL 与 status 文件的并集，不读取“最新运行”。流式读取日志，按换行分隔 Buffer，对原始字节计算 SHA-256，再严格解码 UTF-8、解析包装身份和序号。只保留当前行、摘要、计数及最多 100 项缺口详情；完整缺口数量仍报告。单行很大时仍需保留该行，未实现单行大小限制。

sealed 比较整个文件的计数、字节、首尾序号和摘要。recording / failed 校验已持久化的前缀检查点，后续完整追加不会被当成摘要错误；开放状态仍不接受为完整。空日志、残缺末行、非法 JSON / UTF-8、非法序号、身份或摘要不一致给出损坏原因。旧日志缺状态、不支持状态版本、无片段或访问错误保持未验证。

| 退出码 | 含义 |
| --- | --- |
| 0 | 找到的片段全部 sealed，结构和摘要一致，运行元信息支持当前状态版本 |
| 1 | 任一片段 failed 或明确损坏 |
| 2 | 仍开放、缺状态、未知版本、没有片段或无法确认；参数错误也返回 2 |

检查对象应停止写入或使用稳定副本；不提供与在线写入并发的一致快照。SHA-256 不是签名，无法检测日志和摘要一起重写；缺少运行级清单，整对会话文件被删除也无法检测。complete 不是任务 passed，也不代表整个会话历史完整。

## 选择与验证边界

使用 JavaScript ES Module 直接接入 Cordis，无新增运行时依赖。JSONL 和独立 status 避免把内部状态混入 Harness 事件；保留旧数据可读性，但旧日志不自动获得封存资格。Promise 队列保留原顺序，容量限制减少待写文本无限增长风险，尚无轮转、会话淘汰、数据库或跨进程修复。原有 main.py 保持不变。

2026 年 10 月 14 日按用户决定，后续采用 JavaScript 接入与录制、Python 评测与分析的分工：

| 部分 | 语言与当前状态 |
| --- | --- |
| Harness/Cordis 插件、会话监听、写入队列、状态封存、宿主清理 | 已实现，继续使用 JavaScript |
| M2.2 inspect 及宿主组件检查 | 已实现，继续使用 JavaScript；后续 Python 可调用现有 Node 检查入口 |
| 用例管理、通用任务断言、状态化工具环境核心逻辑、批次调度 | 计划在 M3 优先使用 Python；M2.3 固定 fixture 检查已实现，宿主内工具注册与必要适配按实际接口实现 |
| 重复试验、轨迹分析、指标聚合、配置比较与报告 | 计划优先使用 Python；缺失指标保持缺失 |

跨语言边界先复用现有版本化 run.json、JSONL、status 和 inspect 的 JSON 报告及退出码。Python 评测应先调用现有 Node 检查入口，仅在录制检查通过后执行任务断言；录制失败或无法确认与任务断言失败分别报告。调用 Node 脚本时直接消费其 JSON 输出，具体进程控制和错误映射在 M3 实现并验证。

状态化工具环境需要向运行中的 Agent 返回结果，不能仅靠离线日志完成。若核心用 Python 实现，必须补充并验证请求、响应、错误与生命周期接口；当前未实现该桥接，也未指定具体传输方式。已有 main.py 是示例文件，保持不变。2026 年 10 月 14 日的语言决策见 [修改记录 007](changes/2026-10-14-007-python-evaluation-plan.md)；10 月 15 日新增 Python 功能仅为上述 M2.3 固定证据检查，通用评测仍为计划。

后续分批设计见 [M3 与后续计划](plans/m3-regression-evaluation.md)。计划先区分执行状态、录制有效性和断言结论，建立 caseRunId 与 sessionId / runId 的关联；再验证单用例、实时工具桥接和批次隔离。此处只记录待实现的职责边界，没有新增 schema、工具协议或运行接口。

组件版本固定为 dsh-session `0.2.0-rc.2` / Cordis `4.0.4`；FiberState 是 const enum，检查脚本使用有来源注释的本地常量。插件 stdout 保持协议通道，诊断走 stderr。36 项 Node 测试、6 项 Python 测试及真实组件、模型和子进程检查的范围见 [进度](progress.md)，没有模型成功率或性能改善数据。
