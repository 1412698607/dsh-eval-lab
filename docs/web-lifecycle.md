# M6.4 Web 生命周期检查

更新：2026 年 10 月 24 日，Asia/Shanghai。031 / 032 的合成检查保持独立；033 增加真实 Web 采集和离线验收，034 再追加一个取消任务补齐工作区一致性。Windows、CLI `0.2.0-rc.2`、现有 `deepseek-official / deepseek-flash` 累计五个任务，首次正常失败和旧取消样本保留；正常 / 中断及最新取消样本均有实际工作区匹配证据，旧取消样本仍为未知。

已核实 `103c090` 包含 030 至 034。[审查 035](changes/2026-10-24-035-m6-4-status-review.md) 的异常启动清理、普通退出时间关联两项 P2 已由 [修复 036](changes/2026-10-24-036-m6-4-startup-cleanup-timeline.md) 处理并补无模型回归；本轮不新增模型任务，原样本和历史验收保留。

036 在启动前拒绝旧 state / lifecycle / browser-url 输出并以 wx 创建 terminal.log；启动成功后立即监听实际退出。可捕获的初始化、输出和观察 I/O 错误保留首次原因，停止监督并回收自有正整数 PID，最多等待 10 秒取得有效 PID 和确认退出；未观察退出不能写 closed=true，最终报告若写入失败仍会报错。此期限不是任务总耗时或费用硬上限，原始证据不覆盖。

普通退出要求 task turn/end ≤ Ctrl+C 操作 ≤ SIGINT ≤ 唯一 observer/disposed；取消仍要求首流 ≤ 取消标记 ≤ 页面停止 ≤ turn/end ≤ SIGINT ≤ 唯一卸载，时间允许相等。035 的两份矛盾时间副本现已拒绝，五个原始真实任务的门禁结论保留，旧取消工作区仍未知。

[038](changes/2026-10-24-038-m6-4-ci-capture-path-normalization.md) 根据实际云端失败堆栈，在共享 verify_recorded_task 内统一解析采集父目录，再保留真实子目录包含关系检查，避免直接调用遇到 junction / 非规范化路径时误报越界。新增真实别名和逃逸回归；CLI / 协议不变，不增加模型任务，新提交的云端复验仍待执行。

## 无模型运行入口

在仓库根目录运行，需要 Node.js 与 Python，不安装 Harness、不读取模型凭据、不启动 Web 服务或调用模型：

```powershell
npm.cmd run check:web-lifecycle
# 可选：指定一个尚不存在的输出目录
npm.cmd run check:web-lifecycle -- runs/web-lifecycle/my-new-check
```

脚本为三个场景各启动一个专用 Node 子进程。事件是人工构造的，但文件读取、原录制器写入、进程退出 / SIGKILL 和 Node inspect 均实际执行。`page-cancel` 是场景名称，本阶段通过测试 IPC 请求 fixture 追加取消事件，不代表点击了页面按钮；`normal-exit` 是 fixture 关闭录制器后的自然退出，不代表普通 Web 宿主的信号关闭。

默认输出 `runs/web-lifecycle/<check-id>/`。每个场景保存独立 `case.json`、workspace、traces、stdout / stderr、`lifecycle.json` 与 `verification.json`，根目录保存 `summary.json`。运行目录已存在时拒绝覆盖。不要把这些文件作为公开夹具或凭据资料提交。

对明确的单场景目录重新离线检查：

```powershell
python -m scripts.verify_web_lifecycle 'runs/web-lifecycle/<check-id>/normal-exit'
# 可选 --output <新文件>；已存在的文件不会被覆盖
python -m unittest discover -s test -p test_web_lifecycle.py -v
```

两个检查入口的退出码均以场景规则为准：0 表示预期的检查通过，1 表示未通过，命令用法错误为 2。取消 / 中断的检查可以返回 0，其任务 outcome 仍是 unevaluable，不计任务成功。`verification.json` 始终带 `scope: synthetic-process-check` 与 `liveWebVerified: false`；本阶段严格拒绝 `source: live`，不能靠改标签升级为真实 Web 验收。

如果沙箱禁止 fork 或终止专用进程，应在获准环境或外部终端执行同一命令。EPERM、超时、无法重新 inspect 或进程退出事实不完整均不能算通过，不能用 mock 替代真实子进程结果。

## 合成场景的判定

| 场景 | 操作与进程要求 | 执行 / 录制 / 任务结果 |
| --- | --- | --- |
| page-cancel | 收到已写检查点后发送 synthetic-cancel；后续必须是当前任务的 aborted/user；子进程正常退出 | cancelled / complete / unevaluable，断言 not_run |
| normal-exit | 必须先完成当前任务，再 fixture-exit；退出码 0、无强停或兜底干预 | completed / complete / passed；必要读取结果、答案与 completed 均匹配 |
| process-interrupt | 当前任务已有输入但尚无 turn/end，磁盘检查点覆盖 afterSeq 及完整前缀后 SIGKILL 自己创建的子进程；实际 close 和 SIGKILL 均有记录 | interrupted / unverified / unevaluable，运行及会话仍 recording，断言 not_run |

三个场景不能互相替代。超时强停与预期中断有不同 intervention；旧成功后才强停、无任务 / 无会话、缺失整对日志、错误取消原因、先有结束再标记取消、已封存录制重标为中断均被拒绝。

本阶段的中断正例限定为可核对的干净开放前缀。损坏日志仍报告 invalid 并拒绝场景通过；不会因为 inspect 非 0 就将任何错误当作已验证的中断。

032 复审发现，原门禁仅检查 unverified / recording，会放过不支持的运行状态格式，以及状态检查点尚未覆盖 afterSeq 的尾部。现明确要求 run.json 的 formatVersion=2、statusFormatVersion=1、runManifestFormatVersion=1，均为整数；会话检查点 statusFormatVersion 也为整数 1。整体 inspect 的未确认原因只允许来自开放运行清单，残留 .tmp 等额外原因拒绝通过。

中断检查点还必须非空，lastSeq 等于 afterSeq，writtenCount、writtenBytes、firstSeq、lastSeq、sha256 与 fresh inspect 扫描到的完整前缀一致。fixture 在 flush 后不再追加事件，故本阶段采用完整前缀相等条件；非零起始序号仍允许。通用 inspect 可以保留有效检查点之后的未确认尾部，其规则未改；这类尾部不能证明操作前的 flush 已完成。本阶段因此拒绝空 / 落后检查点，保留 recording=unverified、verified=false、任务 unevaluable，不将其改报为日志损坏。

## 合成流程与文件约定

JavaScript 父脚本冻结 [Web 固定用例](../fixtures/evaluation/web-lifecycle.case.json)，创建新的 workspace，然后启动 fixture。子进程记录 turn/start、匹配输入及任务事件；正常场景实际读取 fixture 文件并生成合成工具结果与答案；取消 / 中断场景先 flush，再经 IPC 告知父进程 runId、sessionId 和最后已写序号。父进程保存发出操作的 afterSeq，以及专用进程的退出码、信号、closed、forceStopped、intervention 和错误。

父脚本的 10 秒兜底与 fixture 的 30 秒孤儿保护只服务于无模型检查；不执行用例中的 timeoutSeconds，也不是 Web 生命周期、费用或断电可靠性保证。父脚本不发送任何取消给真实 Agent，不通过本机 PID 扫描终止其他进程。

`lifecycle.json` 使用独立的 `webLifecycleFormatVersion: 1`，不是 M2.3 resultFormatVersion，也不是通用 evidenceFormatVersion。必需字段为 source、scenario、runId、sessionId、runDir、operation 和 process。operation 只接受本阶段的 synthetic-cancel / fixture-exit / process-kill，并记录 afterSeq 与 signal；未知字段、布尔值冒充版本 / PID / 序号、缺失进程事实均拒绝。runDir 必须是该 runId 对应的 `traces/<runId>`，解析后仍须位于本场景目录。

Python 每次读取当前磁盘，调用原 Node inspect，不读取旧 verification 作为通过依据；再核对运行 / 会话身份、清单及会话状态、单任务输入和连续序号。正常任务复用现有 task_view / check_assertions，取消与中断按各自结束条件检查，不要求取消任务拥有完整答案。原 run.json / JSONL / status、用例格式、通用 runner / evaluate / report 和 M2.3 脚本均保持原协议。

## 真实 Web 运行入口

此入口需要本机已安装的 CLI / SessionStore `0.2.0-rc.2`、Cordis `4.0.4`、pnpm 和宿主可解析的 `node-pty`；本次使用 `1.2.0-beta.15`。准备阶段仅离线安装本地插件、冻结用例和配置，不提交模型任务。实际提交会调用模型，取消 / 中断用例请求持续输出以保留操作窗口，一次任务可能有多次请求；再次运行需自行确定任务数量。

```powershell
New-Item -ItemType Directory -Force runs/web-lifecycle-live | Out-Null
# 无模型：验证真实 ConPTY Ctrl+C 能触发 SIGINT
npm.cmd run live:web-lifecycle -- check-console runs/web-lifecycle-live/console-new
# 使用全新场景目录；可换为 page-cancel 或 process-interrupt
npm.cmd run live:web-lifecycle -- prepare runs/web-lifecycle-live/normal-new normal-exit
npm.cmd run live:web-lifecycle -- run runs/web-lifecycle-live/normal-new
```

每个目录使用独立 home、Web profile、pnpm store 和 fixture。凭据只引用启动时已有 `DSH_HOME`（默认用户 `.dsh`）的 `.credentials.yaml`，不复制密钥；禁用额外模型标题请求和遥测。只读沙箱与 `workspace-controller.documentsDirectory` 同时配置，Web 首个工作区指向本目录的 `documents/deepseek-harness/default-workspace`。仅设置 CLI cwd 不能绑定实际 Web Workspace；提交前应核对独立 home 的工作区注册表及 `state.json.observedWorkspace`。

目前页面步骤由外部 CUA 浏览器操作完成，仓库命令不自动提交或点击停止，也不是一条命令完成三个场景。CUA 打开本场景 `browser-url.txt` 的认证地址，按冻结 `case.json.input` 点击发送一次；保存真实操作时间、页面截图与 `ui-actions.json`。地址中的本地令牌仅保存在忽略目录，报告只保存无令牌的 loopback origin。当前验证器只接受 CUA 来源，不支持把人工 / Agent API 操作改写标签后验收。

| 场景 | 实际操作顺序 | 已验证结果 |
| --- | --- | --- |
| normal-exit | 提交一次；实际工具读取和答案完成后，在监督器 stdin 输入 `{"type":"shutdown"}`；监督器向自己的 ConPTY 写入 Ctrl+C | completed / complete / passed，exitCode=130、signal=null、无强停，SIGINT 与插件卸载均被观测 |
| page-cancel | 首个模型 chunk 后输入 `{"type":"mark-page-cancel"}` 保存已有磁盘检查点，再由 CUA 点击页面“停止生成”；确认 aborted/user 后输入 shutdown | cancelled / complete / unevaluable，断言 not_run；之后同样经 Ctrl+C 清理 |
| process-interrupt | 提交一次；监督器在首个模型 chunk 后读取已有检查点并对自己创建的精确 PID 执行 SIGKILL | interrupted / unverified / unevaluable，断言 not_run；本机实际 exitCode=1、signal=null、forceStopped=true，不补造 SIGKILL 返回值或 sealed |

观察插件只追加原生事件元信息、实际 session cwd / user source、请求路由、首次模型 chunk、SIGINT 与卸载记录。它不 cancel Agent、不要求 SessionStore flush，也不调用 appExit。mark-page-cancel 只记检查点，不能代替页面点击；shutdown 只在任务结束后接受。任务输入仅统计 `user/message.source.kind=user`，runtime-context / skill-catalog 仍保留在序号链中。

监督器从真实用户提交开始设 120 秒兜底，收到 turn/end 即撤销；Ctrl+C 后 10 秒未退出才强停并记录 shutdown-timeout，不能算正常退出。上述时间均不是模型费用或 token 硬限制。ConPTY 初始 PID 可能为 0，监督器在服务就绪时捕获实际 PID，并等待 native onExit 后保存退出事实；本版本 CLI 接收 SIGINT 后正常清理的退出码为 130。

## 真实采集协议与离线复验

新增文件独立于 `lifecycle.json`，不修改旧合成格式或通用评测协议：

| 文件 / 版本 | 内容 |
| --- | --- |
| setup.json / webLiveSetupVersion=1 | 冻结配置、CLI / 组件版本、独立 home / workspace 和观察插件路径 |
| lifecycle-live.json / liveWebLifecycleFormatVersion=1 | source=live、scenario、runId / sessionId / runDir、operation、真实进程事实、平台 / CLI / node-pty 版本、起止时间、干净 URL |
| observations.jsonl / observationVersion=1 | 原生观察的 kind / at / pid；事件序号、会话身份、cwd / sourceKind / 路由等关联字段 |
| ui-actions.json / webUiActionsVersion=1 | driver=cua、actions；每次包含 kind / at / url / control，正常及中断只有 submit，取消为 submit 后 cancel |
| verification.json / liveWebVerificationVersion=1 | scope=live-web-lifecycle、verified / liveWebVerified、三维结果、environment、指标及拒绝原因 |

operation 包含 kind、afterSeq、at、requestedSignal。Python 核对观察时间、真实模型流、原生事件与录制的序号和会话、实际请求路由、页面动作与进程退出，调用原 Node inspect 读取当前磁盘，不使用旧 verification 的成功作为依据。普通退出必须有任务结束之后的 SIGINT 和卸载；超时 / 兜底、错误来源或缺退出事实均拒绝。工作区不匹配会拒绝；正常 / 中断还要求观测可用。取消允许缺工作区观测，但显式报告 `workspaceMatch=null` 和 `workspaceObservationAvailable=false`，不能据此声明 fixture 一致或读取成功。后置路由 / 环境门禁失败时，即使独立任务断言 passed，整体 outcome 仍为 unevaluable。

验收目标包含“取消场景工作区一致性”时，还必须明确检查 fresh 结果的 `liveWebVerified=true`、`environment.workspaceMatch=true` 和 `environment.workspaceObservationAvailable=true`。仅生命周期通过、工作区未知的旧样本不能满足该目标；保留兼容行为不等于补写旧证据。034 在提交前另核对工作区注册表、隔离配置和 fixture 字节，在取消前确认相对路径实际 read 的正确结果，停止后再独立读取稳定录制复验。

真实中断沿用 032 的版本门禁和非空检查点要求，必须 `status.lastSeq >= operation.afterSeq`。与合成 fixture 不同，真实事件在观测和强停之间可能继续追加，因此允许已验证检查点之后的有效未确认尾部；摘要仍由 fresh inspect 核对。空 / 未覆盖操作的检查点、缺失或损坏字节、额外 .tmp、已完成任务重标中断都不能通过。当前实测为检查点截至 seq=13、原始有效字节截至 seq=15，保留未确认分类，未补造 flush 或封存。

```powershell
# 只读离线复验，不启动 Web 或模型；输出文件必须为全新路径
python -m scripts.verify_web_live runs/web-lifecycle-live/normal-new --output runs/web-lifecycle-live/normal-new/fresh.json
python -m unittest discover -s test -p test_web_live.py -v
```

检查取消样本的工作区覆盖时，可对它的新复验文件执行以下门禁：

```powershell
python -m scripts.verify_web_live runs/web-lifecycle-live/cancel-new --output runs/web-lifecycle-live/cancel-new/fresh.json
$cancelCheck = Get-Content -LiteralPath 'runs/web-lifecycle-live/cancel-new/fresh.json' -Raw | ConvertFrom-Json
if ($cancelCheck.liveWebVerified -ne $true -or $cancelCheck.environment.workspaceMatch -ne $true -or $cancelCheck.environment.workspaceObservationAvailable -ne $true) {
    throw 'Cancellation workspace consistency was not verified'
}
```

退出码 0 表示生命周期规则通过，1 表示未通过，参数错误为 2。取消 / 中断即使 liveWebVerified=true，任务仍 unevaluable。中断日志指标保持 null；取消缺失的 token 用量与所有费用不补零。elapsedSeconds 覆盖服务启动到关闭、含页面等待，不是纯模型延迟。离线元信息与 SHA-256 不是签名，不能独立证明任意外部来源。

## 累计范围与历史

033 经授权执行三场景各一任务，再追加一次正常任务，共四次：首次正常任务因默认 Web Workspace 未指向 fixture、监督器误计上下文消息而失败；该样本的原始 PID / 超时强停事实和失败断言全部保留。修复工作区绑定、用户消息计数、实际 PID 捕获与结束后撤销计时器后，追加正常任务读取成功、答案匹配并真实 Ctrl+C 退出。页面取消与处理中断不重跑。

033 的三类生命周期最终均有通过样本，不能表述为首次 3 / 3 通过或四次任务均成功。其取消样本在工作区观测加入前采集，原 README 读取失败；当时只验收取消与退出，完整 fixture 一致性未知。该原始样本和历史判断保持不变。

034 经用户另行授权，只追加一个同配置取消任务，累计五次任务（正常两次、取消两次、中断一次）。提交前注册表及原生 cwd 指向本场景隔离工作区，fixture 字节与冻结用例一致；模型实际 read README 的 callSeq=17 / resultSeq=18，成功返回正确 projectName，先于取消检查点 afterSeq=21。随后 CUA 实际点击停止，同任务 turn/end 为 aborted/user；再经真实 Ctrl+C 收到 SIGINT / 卸载并 exit130，无强停。fresh inspect 的 25 条事件完整封存，全部 25 条原生事件 cwd 匹配，`workspaceMatch=true` / `workspaceObservationAvailable=true`，因此补齐新取消样本的工作区一致性。

补充的单条读取证据检查 passed 只证明取消前的读取，不执行取消任务的完整答案 / completed 断言；主结果仍 cancelled / complete / unevaluable、断言 not_run。离线副本验证错误工作区会拒绝，删去 cwd 仅能得到未知、不能宣称覆盖；旧取消样本 fresh 复验仍为未知。运行指标 modelCalls=2、toolCalls=1，不等于两次任务；不完整 token / 费用保持 null。

本次追加一个任务已执行，不再自动补任务或重跑其他场景。其他平台 / CLI / desktop / SDK、双配置和重复试验仍需另定范围。033 的 196 Python / 82 Node 是原历史全量结果；034 未改生产代码 / 协议，仅定向复验现有 9 Python / 3 Node、真实样本、证据摘要和文档，没有新的云端 CI。

初始合成检查见 [记录 031](changes/2026-10-24-031-m6-4-no-model-lifecycle.md)，原两项中断门禁修复见 [记录 032](changes/2026-10-24-032-m6-4-interruption-gates.md)，真实接入和失败修正见 [记录 033](changes/2026-10-24-033-m6-4-live-web-validation.md)，取消工作区补验见 [记录 034](changes/2026-10-24-034-m6-4-cancel-workspace-validation.md)。旧结果保持历史，原录制格式与 M2.3 入口未迁移。
