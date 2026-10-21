# dsh-eval-lab 架构与技术取舍

当前插件版本 `0.1.2` 实现新增事件录制及离线一致性检查。Node 负责宿主 / 录制 / inspect，Python 已实现离线断言、真实单用例、状态化工具环境、M3.4 顺序批次、M4.1 重复试验与指标汇总、M4.2 独立配置报告及 M5 只读本机浏览服务。

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
| `dsh_eval/formats.py` | 严格版本 1 用例 / 证据校验，拒绝未知字段、重复键与非有限数字 |
| `dsh_eval/evaluate.py` | 重新 Node inspect、单任务证据关联、三种断言、执行 / 录制 / 断言分类 |
| `dsh_eval/__main__.py` | 评测 / 运行 / 报告 / 浏览互斥入口、UTF-8 stdout；浏览阻止执行和写入选项，原任务 0 / 1 / 2 不变 |
| `dsh_eval/runner.py` | 初始文件、新执行目录、准备 / 任务预算、控制消息、退出回收、版本 2 清单和离线评测 |
| `dsh_eval/experiment.py` | 冻结实验输入、显式展开用例 / 配置 / 重复编号，复用顺序 batch，核对样本关联并汇总 |
| `dsh_eval/metrics.py` | 闭合任务内观测计数 / usage、明确样本分母与逐指标缺失覆盖，不估算价格 |
| `dsh_eval/report.py` | 核对终态实验 / 冻结用例 / 样本关联，重新 evaluate，按实际路由与来源配对，独立 JSON / Markdown |
| `dsh_eval/browser.py`、`dsh_eval/web/` | 标准库 loopback 读取服务、目录 / 路径边界与令牌、保存结果和原始轨迹分页；HTML / CSS / JavaScript 界面不启动任务或复验 |
| `.github/workflows/deterministic.yml` | 干净 Windows 环境无模型检查，不安装 Harness / 读取模型凭据；云端首跑已执行，路径修复后待复验 |
| `scripts/case-host.js` | 实际 CLI 的独立 profile 安装与专用 headless 子进程、协议 / IPC 观察、退出报告 |
| `scripts/fixtures/case-control.js` | 复用 M2.3 生命周期控制，观察实际选择和 request/header 路由；仅专用 IPC 子进程加载 |
| `scripts/demo-eval.js`、`fixtures/evaluation/` | 两组公开合成证据，复用原记录器，独立 caseRunId / 会话；不运行模型或环境 |
| `test/` | 原功能、配置、组件版本及完整性边界测试 |

## 输出与数据格式

M5 的 `--browse` 以 `/api/catalog` 读取目录索引，以 `/api/document?id=...` 读取一个已保存 JSON / Markdown 或一页 JSONL。目录索引带 `browserFormatVersion: 1`，只是读取响应，没有新持久化结果格式；不会写入文件、刷新摘要或改变评测状态。浏览 API 不调用原 evaluate / inspect / runner，旧结果可过时，与 M4.2 的主动离线复验是两个入口。

服务固定绑定 127.0.0.1，以启动时随机令牌、Host / Origin 检查及根目录解析限制访问，扫描不跟随符号目录 / junction。内容用文本节点呈现，默认排除独立 home / workspace 和私人目录。该方案复用现有 JSON 与原证据位置，无前端依赖和数据库；代价是没有实时一致快照、远程多用户访问或编辑 / 运行功能。容量、分页和已验证边界见 [结果浏览](result-browser.md)。

关联路径先进行不跟随链接的文本范围与禁用目录检查，再解析真实路径并复核，根外引用不先做文件系统路径解析。浏览局部 JSON 包装限制对象 / 数组容器最多 128 层并隔离解析递归错误；超深文档单独报错，轨迹行保留预览及后续正常行，不改变原证据有效性。目录响应的 `sources` 以临时 `unknown` 保留缺失样本来源，供混合来源筛选使用，不回写持久化文件。修复与验证见 [记录 021](changes/2026-10-21-021-m5-review-fixes.md)。

根目录预检同时登记显式配置的路径写法和对应真实根，兼容 Windows 短路径或目录别名；解析后的引用仍须落在相应真实根内。其他未配置前缀仍按原范围限制处理，不通过先解析外部位置来发现别名。云端差异与回归见 [记录 022](changes/2026-10-21-022-cloud-ci-path-aliases.md)。

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

Python 固定检查器读取版本化联调报告定位明确目录，并重新调用 Node inspect，避免旧快照掩盖磁盘损坏。录制通过后核对用户输入、文件参数、callId 关联的实际工具结果、结果在答案之前、字段值和 turn/end；工具名来自事件。缺失文件要求真实 isError 和后续响应；取消检查 aborted/user；强停检查 SIGKILL 与非完整录制。它限定单会话与固定 fixture，不承担通用用例格式、批次调度或统计。M3.1 使用下述独立包，不修改该历史验证器。

## M3.1 用例与离线断言

`python -m dsh_eval --case <case.json> --evidence <evidence.json> [--output <新文件>]` 使用 Python 标准库。只在仓库根目录运行，不改变 main.py 或 npm 插件分发内容。M3.1 引入 caseFormatVersion / evidenceFormatVersion / evaluationFormatVersion，当时均为 1；当前用例仍为 1，证据 / 结果兼容 1 / 2，扩展见下节和 [评测格式](evaluation-format.md)。

```text
版本化用例 + 证据清单
  → 校验输入 / 环境 / 配置 / 预算 / 断言及 caseRunId
  → 调用既有 Node inspect，核对 JSON 与退出码
  → 非 complete：保留录制原因，断言 not_run
  → complete：复核 runId / 单会话 sessionId / 插件版本，读取稳定片段
  → 比较执行声明与结束 / 退出事实；非 completed 不判断普通任务成败
  → 唯一用户输入与结束、最终答案，callId → toolCallId 关联
  → final_text / tool_result / turn_end 必需断言
  → 保留三维状态、逐条证据及 passed / failed / unevaluable
```

caseRunId 是一次用例执行的 UUID，与插件 runId 分开，复验沿用；首版一个用例一个新主会话，拒绝额外会话、多轮任务、恢复 / fork / 子 Agent 范围。任务内序号缺口、已知事件结构错误、孤立 / 重复 / 倒序结果或缺乏必要证据时，保守报告无法评测。未知事件保留并跳过；不改变 Node inspect 允许非零序号与缺口的规则。

工具断言按用例声明匹配实际名称和参数键，不猜测工具或路径。需要调用先于关联结果、结果先于最终答案；明确值不符为 failed，缺关联证明为 insufficient_evidence。预期 isError 可以通过工具断言，不能直接作为宿主运行错误。只有执行 completed、录制 complete 且证据充分才判断任务 passed / failed。

清单记录配置、预算实施和执行干预事实，离线模块只能核对声明与已有证据；provider / model / profile、超时 / 进程错误由后续适配器负责采集。环境文件与预算本批只校验和保留，未执行。source=synthetic 的两组公开样例经过实际录制器与检查器，但不代表真实工具 / 模型或顺序批次已执行。Python 不复制录制摘要算法，也不读取旧检查快照代替本次 inspect；输出用例快照与明确关联路径，缺失指标不填零。

独立版本格式先由 Python 校验器落实，避免为当前离线范围增加 schema 依赖。后续驱动需要扩展字段时使用显式版本或更新兼容约定；本批不预建实时工具协议。文件输出以新建模式写入，保留历史结果；尚未实现结果文件原子发布或在线一致快照。

## M3.2 真实单用例与进程边界

`--run` 使用新 caseRunId 子目录，保存用例快照，Python 实际写入初始文件后调用 `case-host.js prepare`。后者按已验证 CLI 的离线 link 安装方式创建独立 headless home / store，设置 read-only workspace、凭据路径引用、请求的默认路由和禁用额外标题请求；不会复制密钥、修改原 profile 或安装未知版本。

Python 的准备期限为 150 秒。`case-host.js run` 使用 Node fork + IPC 启动实际 CLI，Python 通过单独 JSONL 控制流实施任务墙钟预算和取消；任务预算从适配进程创建后开始，包括宿主启动，准备与清理另计。控制插件复用 M2.3 的 agent.cancel / idle / flush / appExit 路径；独立观察 actual selection 和 request/header，不将请求配置直接当作实际模型调用事实。

```text
Python：校验用例 → UUID 目录 / case 快照 / workspace
  → Node prepare：实际 CLI 安装新 headless profile（独立准备期限）
  → Node run → 专用 Harness 子进程（任务墙钟预算）
       IPC：实际选择 / 请求路由 / 首 chunk → Python 监督器
       控制：cancel / timeout → Agent 停止 / idle / flush / 正常退出
       超清理期限：尝试强停自己创建的进程 / 进程树
  → 保存实际退出 / 清理观察及版本 2 evidence
  → fresh Node inspect → 路由与任务断言 → evaluation.json
```

Node 清理请求 10 秒后尝试终止专用 CLI；Python 15 秒后尝试终止仍在运行的自有适配进程树，Windows 按确切 PID 使用 taskkill /T /F，权限失败不能宣称清理成功。Python 异常细节只写私有 runtime.json，公开 JSON 原因引用相应文件。实测正常 / 路由错误 / 超时 / 流后取消的专用 CLI 均已退出；进程树兜底用无模型的真实子进程测试验证，未对任意外部工具树或其他平台作保证。

启动失败时 recorder / session / 路由可能尚不存在，故新增 evidenceFormatVersion / evaluationFormatVersion 2：保留 caseFormatVersion 1，允许实际 runId / sessionId / runDir / configuration 为 null，可选 runtimeReport；原版本 1 继续严格兼容。结果只保留已经观察到的实际身份。版本 2 正常任务重新核对日志全部 request/header 路由与清单配置，缺少或冲突无法评测。raw run / JSONL / status 版本不变。

host-result.json 为 adapterFormatVersion 1，保存 CLI 版本、实际选择 / 路由、流通知、PID、退出码 / 信号、干预和关闭事实；runtime.json 为 runtimeFormatVersion 1，保存 Python 阶段、监督器和异常。文件随执行私有保存，不作为签名或完整历史。模型端实现不由本地 provider / model 字段独立证明。详细命令和预算边界见 [单用例运行](single-case-runner.md)。

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
| 用例加载、通用离线任务断言 | M3.1 已使用 Python 实现，合成正反例验证通过；M2.3 固定检查仍保留 |
| 单用例真实驱动与预算 / 退出事实 | M3.2 已使用 Python 调度和 JavaScript 宿主适配；受控文件任务与异常分别通过 |
| 状态化工具环境核心逻辑、批次调度 | M3.3 Python 核心及 JavaScript 实时注册桥接、M3.4 Python 顺序批次均已实现 |
| 重复试验与指标聚合 | M4.1 已由 Python 实现，复用原 batch；缺失指标保持缺失 |
| 配置比较与报告 | M4.2 已由 Python 实现，核对冻结任务、样本关联、实际路由 / 来源和共同指标覆盖 |

跨语言离线边界复用现有版本化 run.json、JSONL、status 和 inspect 的 JSON 报告及退出码。M3.1 Python 先调用现有 Node 检查入口，仅在录制检查通过后执行任务断言；录制失败或无法确认与任务断言失败分别报告。Node 进程不可用、检查超时和协议不一致映射为录制 unverified。

状态化工具环境需要向运行中的 Agent 返回结果，不能仅靠离线日志完成。若核心用 Python 实现，必须补充并验证请求、响应、错误与生命周期接口；M3.3 已实现版本 1 请求 / 响应，Python 与 Node 适配器通过 JSONL，适配器与专用 Harness 子进程通过 IPC。已有 main.py 是示例文件，保持不变。2026 年 10 月 14 日的语言决策见 [修改记录 007](changes/2026-10-14-007-python-evaluation-plan.md)；10 月 15 日增加 M2.3 固定证据检查，10 月 16 日完成 M3.1 离线用例断言。

后续分批设计见 [M3 与后续计划](plans/m3-regression-evaluation.md)。M3.1 / M3.2 已区分三维状态并建立真实单用例闭环；M3.3 已实现状态化环境与实时工具桥接，M3.4 已补批次隔离，M4 已实现重复试验与离线配置报告，下一批为 M5 结果浏览与持续集成。

组件版本固定为 dsh-session `0.2.0-rc.2` / Cordis `4.0.4`；FiberState 是 const enum，检查脚本使用有来源注释的本地常量。插件 stdout 保持协议通道，诊断走 stderr。当前 42 项 Node、117 项 Python 测试；真实组件、模型和子进程检查范围见 [进度](progress.md)，当前少量样本不构成模型表现或性能改善结论。

## M3.3 实时状态化工具边界

`environment.py` 保存虚拟文本与每路径暂时失败计数；`runner.supervise` 在进程运行期间处理请求。`case-control.js` 用真实 Tools 服务注册 `eval_read` / `eval_list`，共享 `tool-bridge.js` 实现请求等待、取消、5 秒响应期限与卸载清理。`case-host.js` 只转发桥接数据，基础设施错误触发专用宿主关闭。协议身份、重复请求和提交后取消语义见 [状态化工具与桥接](stateful-tools.md)。环境测试、真实注册及跨进程检查、真实模型轨迹三层分别验收，不修改 src 或录制协议。

## M3.3 审查修复：管道写入与超时监督

Python `supervise` 使用专用写线程串行输出工具响应和控制帧，监督主循环只入队，继续观察退出、取消和任务期限；stdin 的关闭也由写线程负责，避免主循环被同一 TextIO 锁阻塞。写入错误经内部事件回传并归为运行错误；已经触发的 timeout / cancel 不被后续管道错误覆盖。干预后尚未开始写入的工具响应会跳过，已经提交的环境状态仍不回滚。

若整条响应正在写入时管道堵塞，控制命令不能插入半条 JSONL，可能无法正常送达；监督器仍会在原清理期限后尝试终止自有进程树，随后等待 I/O 线程退出，报告 stdinWriterStopped。未结束的线程会记录清理错误；没有把任务预算改成总退出硬上限，权限拒绝仍按实际失败记录。

版本 2 用例允许空 arguments 匹配任意参数，结合工具名和结果内容检查发现行为；版本 1 保持非空约束。根目录 / docs 两条合成恢复路径均经过原有记录器及 fresh inspect，真实宿主桥接也已复验；本批未新增模型调用。详见 [修复记录 014](changes/2026-10-18-014-m3-3-review-fixes.md)。

## M3.4 批次边界

batch.py 在调用模型前校验并保存全部输入，逐项分配 caseRunId，调用原 run_case 后核对保存结果、batchId / caseId / caseRunId，记录配置和证据路径。runner 补批次身份透传、准备进程是否退出、执行适配器启动和人工中断事实，原录制协议不变。每项完成进程与写线程清理后才进入下一项；不能确认时停止，即使 failurePolicy=continue。

2026 年 10 月 19 日修复未创建适配器时的误停：runtime.adapterProcessStarted 明确为 false 时，运行错误按批次策略处理；Popen 成功后为 true，创建过程尚未确认时为 null。缺失或未知值继续走原清理事实检查，不把空 supervisor 当成未启动。人工中断优先停止整批，既有实际身份缺失仍保持 null；格式兼容与回归依据见 [修复记录 016](changes/2026-10-19-016-m3-4-launch-failure-policy.md)。

batch-result.json 是本批唯一活动进度快照，以同目录临时 JSON + replace 更新；已有单项结果不覆写。每个新批次使用新 UUID 目录，冻结后的 batch.json 可重新执行新任务，不是重放或恢复。普通失败 / 无法评测、调度中断 / 异常和 skipped 分开；其精确定义、字段和退出码见 [批次运行](batch-runner.md)。没有并发批次调度、崩溃续跑或性能 / 成本统计。

## M4.1 实验与指标边界

`experiment.py` 严格加载版本 1 清单，校验全部用例与配置组合，冻结原输入，再按重复 / 用例 / 配置顺序生成标准 batch；没有另写一套调度和清理逻辑。sampleId 对应 batch entryId，以 caseEntryId + configurationId + repeatIndex 表示计划位置，再关联实际 caseRunId / runId / sessionId。configuration 保留真实观察，requestedConfiguration 和匹配分布另列。结束后核对样本关联并生成总表及分组 JSON，不提供配置优劣判断。

`metrics.py` 在 evaluate 重新 inspect 和核对身份后，从连续闭合任务片段提取已结算 assistant/message / assistant/attempt 和 tool/call 数量；request/header 是配置段事件，不能用作调用次数。step/start 可以早于 user/message，不能把生命周期开放事件当作任务输出越界。usage 逐字段检查覆盖，失败尝试或任一步缺失则 token 保持 null，不由 input / output 补造 total。任务失败与取消不抹掉合法观测；指标缺失不改变三维结论。

同日审查修复为指标单值和求和增加有限范围检查，超大数值视为缺失，不将有效整数转成浮点数。token 某字段的单值或总和超范围仅使该字段缺失；实验汇总溢出时保留观测 / 缺失数量，总和与均值为 null，并给出可选 reason。该处理在指标层完成，不使异常 runtime 计时中断任务，也不输出 Infinity / NaN。详见 [修复记录 018](changes/2026-10-21-018-m4-1-metric-overflow.md)。

runner 在保存 case 快照后启动单调时钟，到保存 runtime 前记 elapsedSeconds，包含准备 / 执行 / 清理，排除离线 inspect 与断言。runtime 身份不符或无字段时计时缺失。新 metrics、批次行 source / metrics、runtime.elapsedSeconds 都是原版本可选扩展；recording / evidence 协议不变。实验初始计划与终态使用独立临时文件 replace，批次执行中仍查看原 batch 检查点，没有 fsync 或 resume。

统计明确 planned / attempted / finished / skipped / errors、三维分类以及可评测通过比例、全尝试通过比例和可评测覆盖。指标总和与均值只计算已观测子集并公开 missingSamples；费用恒为 null。完整字段与验证限制见 [重复试验](experiments.md) 和 [记录 017](changes/2026-10-21-017-m4-1-repeated-experiments.md)。

## M4.2 离线报告边界

`report.py` 只读一个已结束实验，从传入结果旁定位冻结清单及批次，不信任旧绝对目录。核对计划展开、样本数、批次关联和执行 / 录制身份唯一性，路径保持在实验 / 批次目录内。每项以原用例加实验配置构造完整期望输入，比较批次及执行快照，覆盖任务、环境声明、预算、断言和版本；除 configRef 外规范 JSON 的 SHA-256 作为 taskFingerprint，不能代替签名或证明实际环境创建过程。

逐项核对 evidence 身份、来源、实际配置及路径，复用原 evaluate 的 fresh inspect / 三维断言与指标采集。Windows 原生证据路径兼容后再核对；新报告各自保存复验结果，原实验和旧评测不覆写。旧 summary / 样本字段只作为 savedSummary / saved 留存，changedFields 解释新旧结果差异。样本快照或证据冲突降为 rejected / unevaluable 并留在原计划分母；全局计划 / 关联冲突拒绝整份输入。

configurationMatch 还独立检查实际请求头，不仅比较选择声明。完整关联录制中的全部 provider / model 与请求配置一致且 evidence 全 configRef 匹配才 matched；其他为 mismatched / unknown。source=live / synthetic 仍是声明，并非签名。组汇总公开全部计划、匹配子集、来源、三维分类和三个分母，不能把请求分组直接当作模型成绩。

比较按用例、配置对和来源分开，以同 repeatIndex 的双方 verified / matched 样本配对；指标进一步使用两侧都有值的共同子集。报告右减左的比例差、观测均值差及单对范围，同时列原计划对数、排除与缺失。沿用 metrics 的溢出 reason，均值不可表示时差值同样缺失。没有随机化、置信区间、显著性或自动赢家；单配置或同 configRef 别名不构造模型优劣。

新 `comparisonReportFormatVersion=1` 与原 experiment / evidence / evaluation 格式独立；报告命令不调用模型，成功退出码表示生成报告，样本任务分类另看。结果写入新 UUID 目录，可能在磁盘错误时留下不完整目录，没有原子发布、fsync 或在线一致快照。字段、参数和限制见 [配置报告](configuration-reports.md) 与 [记录 019](changes/2026-10-21-019-m4-2-configuration-reports.md)。
