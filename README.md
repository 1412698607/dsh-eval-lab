# dsh-eval-lab

面向 DeepSeek Harness 的 Agent 行为回归测试项目。第一阶段实现实时会话轨迹记录，为后续测试用例、确定性断言和版本对比提供输入。

## 当前功能

- 作为 Cordis 插件订阅 `session/event`，保留原始事件，包括消息、工具调用、工具结果及轮次边界。
- 每次插件启动创建独立运行目录，每个会话写入独立 JSONL 文件。
- 使用异步写入队列保持同一会话的观察顺序，通过 `session/flush` 和插件卸载等待已排队写入完成。
- 写入失败时记录错误，后续 checkpoint 报错；失败会话停止继续录制，其他会话仍可写入。
- `0.1.2` 完成 M2.2：独立会话状态文件、计数和 SHA-256、待写入容量保护，以及离线 `inspect`；保留 M2.1 的 stderr 诊断和可移植配置。
- M2.3 已完成独立 Web / headless profile 的真实模型联调，新增固定 fixture 的 Python 证据检查；插件版本保持 `0.1.2`。
- M3.1 已实现 Python 版本化用例加载、离线证据断言及执行 / 录制 / 断言三维结果；两个公开合成用例通过，插件版本仍为 `0.1.2`。
- M3.2 已实现 Python 驱动单用例真实 headless 运行、独立文件环境和会话、实际路由采集、墙钟超时 / 取消及退出清理；证据 / 结果版本 2 兼容原版本 1。
- M4.1 已在状态化工具与顺序批次上增加重复试验、配置 / 重复编号关联、明确分母和已观测指标；缺失用量与费用保持 null。
- M4.2 已实现保存实验的离线配置报告，重新 inspect 和断言，按实际配置、用例、重复编号及来源配对，独立保存 JSON / Markdown。
- M5 已实现本地只读结果浏览：用例、实验 / 批次、配置报告、三维结果与分页证据；Windows 无模型云端 CI 已验收通过。
- M6.1 已实现运行级会话清单：新 run.json 版本 2 登记应有会话，inspect 可发现整对会话文件缺失；旧日志保留片段检查结果并明确运行级覆盖未知。

接入验证使用本机安装缓存中的 **DSH 0.2.0-rc.2 / Cordis 4.0.4**。插件声明对应的可选 peer，以供 Harness 检查版本兼容性。无需构建，也无需安装依赖即可运行模拟演示和单元测试。

## 浏览已有结果

在项目根目录运行，需要 Python 3.12 或更高版本：

```powershell
python -m dsh_eval --browse
```

打开终端输出中的完整 `url`，即可查看本地结果，按名称、任务结论和来源声明筛选，再从逐次结果进入证据与事件轨迹。默认读取 `fixtures/evaluation` 和 `runs`，仅在本机提供只读页面，不调用模型、不重新评测、不改写历史文件；终端按 Ctrl+C 停止。保存结论可能已过时，复验仍使用原来的 `--report` 或 `--case ... --evidence ...`。

目录、端口、读取限制及无模型 CI 范围见 [结果浏览](docs/result-browser.md)。[持续集成配置](.github/workflows/deterministic.yml) 将在 push、PR 和手动触发时运行确定性检查；真实模型任务仍需单独选择配置、预算并使用 `--run`。

## 本地演示

在 PowerShell 中运行：

```powershell
Set-Location 'D:\codexWorkspace\dsh-eval-lab'
npm.cmd run check
npm.cmd test
npm.cmd run demo
```

`demo` 写入 8 条模拟事件，不调用模型、不产生模型费用。它只展示日志输出，不代表完成真实 Agent 评测。`test` 在同一进程运行，避免部分 Windows 沙箱对测试子进程的限制。

真实组件接入检查：

```powershell
npm.cmd run smoke:host
npm.cmd run check:output
```

脚本自动寻找 Windows npm 缓存里的匹配版本，加载真实 Cordis 和 SessionStore，挂载插件，创建会话并提交工具调用及结果，然后验证导出的事件与原事件一致。它不启动 Web 服务、不执行真实文件工具、不调用模型，也不修改已有 Harness profile。

`check:output` 启动正常录制、真实磁盘写入失败、未关闭录制器直接退出三个独立子进程，核对输出通道及 `inspect` 的 0 / 1 / 2 结果。前两种场景加载真实宿主组件，第三种只运行独立录制器。父脚本的检查摘要正常写到 stdout。部分沙箱会以 `spawn EPERM` 禁止捕获子进程输出，此时需在获准环境或外部 PowerShell 执行同一命令，失败不能视为通过。

若 Harness 安装在其他位置，可以传入它的 `node_modules` 路径：

```powershell
npm.cmd run smoke:host -- 'D:\your-harness\node_modules'
npm.cmd run check:output -- 'D:\your-harness\node_modules'
```

## 安装到 Harness

日志目录按以下优先级选择：

1. Harness 插件配置中的 `config.outputDir`。
2. 宿主进程的环境变量 `DSH_EVAL_OUTPUT_DIR`。
3. 用户主目录下的 `.dsh-eval-lab/runs`；当前 Windows 用户对应 `C:\Users\Admin\.dsh-eval-lab\runs`。

显式配置和环境变量必须是非空绝对路径。选中的值无效时直接报错，不退回下一项。分发用 `cordis.patch.yml` 保持空配置，不再绑定开发机盘符；`demo` 与验证脚本仍显式写入项目内的 `runs/`。已有 profile 若保存了旧的显式 `outputDir`，它仍优先于环境变量，需要通过该 profile 的配置方式更改或移除。

插件配置还支持 `maxPendingBytes`，默认 `16777216`（16 MiB），必须是正安全整数。它限制整个录制器尚未完成写入的 UTF-8 文本字节总量；超限会使受影响会话失败，其他会话可继续。该设置不是进程总内存上限，不通过环境变量配置。

例如在启动 CLI 的同一个 PowerShell 窗口中，将真实任务日志写入本项目：

```powershell
$env:DSH_EVAL_OUTPUT_DIR = 'D:\codexWorkspace\dsh-eval-lab\runs'
```

该设置只影响当前窗口及其后续启动的进程，已运行的桌面应用不会因此改变环境。

以下命令适用于 CLI 的 **web profile**，需要安装版 CLI 所使用的 pnpm 可执行文件可用：

```powershell
Set-Location 'D:\codexWorkspace\dsh-eval-lab'
npx.cmd @deepseek-ai/dsh@0.2.0-rc.2 plugin --profile web add 'D:/codexWorkspace/dsh-eval-lab'
npx.cmd @deepseek-ai/dsh@0.2.0-rc.2 web
```

插件加载后，服务端终端的 stderr 会显示 `[eval-lab] 日志目录：...`。在 Harness 中创建新会话，提交一个需要读取文件的任务；完成后在该目录检查 JSONL 文件中的 `tool/call` 和 `tool/result`。模型凭据使用你已有的 Harness 配置。

如果你运行的是 Harness 桌面版，应使用它实际使用的版本和 **desktop profile**。这里尚未执行桌面版安装；M2.3 验证的是 CLI 的独立 Web / headless profile，`smoke:host` 仍只验证会话组件和插件事件接入。

## M2.3 真实任务联调

需要已安装的 DSH `0.2.0-rc.2`、可用的 pnpm、Node.js 和 Python（本次为 `3.12.0`）。准备命令通过实际 CLI 插件管理入口，离线安装两个独立 profile，不修改原有 profile，不升级宿主：

```powershell
npm.cmd run live:prepare
# 若无法自动找到匹配缓存：
# npm.cmd run live:prepare -- 'D:\your-harness\node_modules'
```

命令复制 [README fixture](fixtures/live-read/README.md) 到 `runs/live/<check-id>/workspace`，并打印联调目录。独立 home 的凭据配置只引用启动时原 `DSH_HOME`（未设置时为用户 `.dsh`）中的 `.credentials.yaml`，不复制密钥。测试使用宿主默认的 `deepseek-official / deepseek-flash`，不导入原 profile 的自定义模型配置；使用只读文件策略，关闭额外的模型标题请求与遥测。环境变量凭据仍按宿主规则生效。

把输出目录填入以下命令；真实任务会调用模型：

```powershell
$liveCheck = 'D:\your-project\runs\live\<check-id>'
npm.cmd run live:run -- $liveCheck read
npm.cmd run live:run -- $liveCheck missing
npm.cmd run live:run -- $liveCheck cancel
npm.cmd run live:run -- $liveCheck kill
npm.cmd run live:run -- $liveCheck web
```

`read` 要求实际文件工具读取 README 并返回 `projectName`；`missing` 要求读取不存在的文件并报告。`cancel` 收到首个模型流 chunk 后调用实际 Agent 取消接口；`kill` 在同一时点强制停止本次专用子进程。chunk 可以是块边界，不保证已生成正文或执行文件工具。headless 最长运行 120 秒，超时强停算检查失败。

`web` 打印本地认证 URL，在该页面的测试 workspace 提交以下任务。看到完成后，在启动命令的终端输入 `stop` 并回车。控制插件先取消活动 Agent、等待 idle 和 flush，再请求官方启动器关闭；15 秒未退出会强停并报告失败。本次没有验证普通 Web 进程直接信号关闭或页面手动点击停止。

```text
Read README.md using the actual filesystem tool. Return only the value of projectName. Do not modify any files or delegate.
```

每次启动都打印明确的 `<check-id>/<mode>/<launch-id>` 输出目录，保存 stdout、stderr、`result.json` 和 `traces/<run-id>/`。headless stdout 按 JSON 帧检查；Web stdout 为普通日志，可能包含本地认证 URL。原始输出均留在被忽略的 `runs/`，不作为公开样例。

`live:run` 退出 0 表示生命周期达到预期：正常任务退出 0 且录制可检查；取消任务退出 1、保留 `aborted/user` 且正常封存；强停收到 `SIGKILL` 且 inspect 非 0。它还不等于任务内容正确。对本次明确的启动目录检查任务证据：

```powershell
python scripts/verify_live.py 'D:\your-project\runs\live\<check-id>\read\<launch-id>'
npm.cmd run test:python
```

Python 检查器也支持其他四种模式：先重新调用 Node inspect，再核对用户输入、实际工具参数、callId 关联的结果、助手答案及结束原因；工具名不硬编码。它只处理 M2.3 的单会话固定 fixture，输出 `verified: true` 表示该场景证据通过。通用用例管理、状态化工具环境和批次评测仍留在 M3。

沙箱若以 EPERM 阻止真实子进程，应在获准环境或外部终端执行同一命令，不能将失败计为通过。实际结果见 [修改记录 008](docs/changes/2026-10-15-008-m2-3-live-integration.md)。

## 输出结构

插件统一生成 `<outputDir>/<runId>/`。以下是本地演示和检查使用的项目目录，检查脚本额外使用唯一的 `check-id` 隔离本次验证：

```text
runs/
  <run-id>/
    run.json
    <sha256(session-id)>.jsonl
    <sha256(session-id)>.status.json
  host-smoke/
    <check-id>/
      <run-id>/
        run.json
        <sha256(session-id)>.jsonl
        <sha256(session-id)>.status.json
  output-check/
    <check-id>/
      normal/<run-id>/...
      write-error/<run-id>/...
      abrupt-exit/<run-id>/...
```

新 `run.json` 使用 `formatVersion: 2`，包含原插件版本、运行 ID、启动时间及 `runManifestFormatVersion: 1` 的会话清单、运行状态。JSONL 每行仍使用 `formatVersion: 1`，包含 `runId`、`sessionId` 和完整 `event`。哈希文件名避免会话 ID 被当成路径，原始 ID 仍保存在每条记录和清单中。详细字段见 [运行会话清单](docs/run-manifest.md)。

状态文件使用独立的 `statusFormatVersion: 1`，包含 `recording` / `sealed` / `failed`、接收与写入计数、UTF-8 字节数、首尾序号及 SHA-256。首次会话文件写入必须等待清单登记成功；`flush()` 保存选中检查点但不封存运行，`close()` 停止接收、排空会话队列，最后封存运行清单。插件使用 Cordis 的 `ctx.effect()` 注册关闭清理。

新会话共用待执行登记批次，批次开始才生成完整清单，写入期间新增成员等待下一批。清单与状态替换只对 rename 的 EPERM / EACCES / EBUSY 最多尝试六次，计划退避合计 310 ms，不约束底层 I/O 耗时；持续错误仍使检查点 / 关闭失败。没有增加总内存硬上限，详见 [修复记录 024](docs/changes/2026-10-22-024-m6-1-registration-reliability.md)。

## 离线检查

显式指定一次运行目录，不自动选择最新批次：

```powershell
npm.cmd run inspect -- --run 'D:\codexWorkspace\dsh-eval-lab\runs\<run-id>'
```

命令输出 JSON 报告：

| 退出码 | outcome | 含义 |
| --- | --- | --- |
| `0` | `complete` | 找到的会话片段均已封存，身份、结构、计数、字节数、序号与摘要一致 |
| `1` | `invalid` | 存在明确失败或损坏，包括截断、空日志、摘要不匹配和非法序号 |
| `2` | `unverified` | 仍开放、旧日志缺少状态、版本不支持、无片段或文件无法读取 |

新格式还必须通过清单与目录对照；清单未封存时不能 complete，sealed 清单中登记的日志 / 状态缺失或出现未登记会话均为 invalid。旧版本 1 元信息仍按原片段规则检查，但报告新增 `runManifest.outcome=unverified`，明确其无法确认运行级会话覆盖。必须使用升级后的 inspect 读取新格式，旧 inspect 会拒绝版本 2。

序号必须是严格递增的非负安全整数，允许从非零开始；缺口显示在 `gaps` 中（最多 100 项，完整数量在 `gapCount`），不补造历史。未知事件类型保留可读。旧 JSONL 可以诊断，但不能自动变成已封存片段。开放状态仅复核已保存的检查点前缀，后续完整追加不会被误判为摘要损坏。

请在写入停止后或稳定副本上检查；工具不提供与在线写入并发的一致快照。退出码表示录制片段可校验程度，不代表 Agent 任务通过，也不证明完整会话历史或断电可靠。

日志包含原始会话及工具内容。`runs/` 已加入 `.gitignore`；作品集展示可使用 `demo` 的模拟数据。

## 通用用例离线评测（M3.1）

在仓库根目录运行，使用 Python 标准库及现有 Node inspect：

```powershell
npm.cmd run test:python
npm.cmd run demo:eval
python -m dsh_eval --case 'fixtures/evaluation/read-project.case.json' --evidence 'runs/eval-demo/<demo-id>/<runId>/evidence.json' --output 'runs/eval-demo/<demo-id>/<runId>/evaluation.json'
```

`demo:eval` 输出读取项目名称、报告缺失文件两组 casePath / evidencePath，分别代入评测命令。它用原有记录器生成合成日志，不调用模型，也不执行用例环境。评测先重新运行 Node inspect，再核对输入、工具参数、callId 结果关联、答案和结束顺序。结果文件必须不存在，复验请省略 `--output` 或使用新文件名。

退出码 `0` / `1` / `2` 分别对应任务 passed / failed / unevaluable（输入或输出错误也为 `2`）。仅执行正常且录制有效才判断任务通过或失败；缺工具证据、取消、超时、运行错误和录制损坏分别保留原因。完整字段、预算声明和单任务限制见 [评测格式](docs/evaluation-format.md) 与 [合成样例](fixtures/evaluation/README.md)。

## 单用例真实运行（M3.2）

以下命令会调用用例指定的真实模型，使用本机匹配版本宿主和已有凭据引用：

```powershell
python -m dsh_eval --case 'fixtures/evaluation/live-read.case.json' --run
python -m dsh_eval --case 'fixtures/evaluation/live-read.case.json' --run --cancel-after-stream
```

每次生成 `runs/evaluation/<caseRunId>/`，独立 home / workspace / 新会话，保存 case.json、evidence.json、evaluation.json 与私有运行证据。第二条是首个请求流 chunk 后程序化取消验收。任务预算包含宿主启动与任务执行，安装准备和清理另计；正常、启动 / 路由错误、两秒超时和取消已实际验证。预算、可空事实、参数和平台范围见 [单用例运行](docs/single-case-runner.md)。

## 状态化工具用例（M3.3）

```powershell
python -m scripts.smoke_bridge
python -m dsh_eval --case fixtures/evaluation/stale-path.case.json --run
python -m dsh_eval --case fixtures/evaluation/retry-read.case.json --run
```

第一条验证实际 Cordis 工具注册、fork IPC 和 Python 状态，不调用模型；后两条调用真实模型。版本 2 用例通过 `environment.stateful.transientReadFailures` 声明每条路径的暂时读取失败次数；虚拟文件留在 Python 内存，工作区为空，工具为 `eval_read` / `eval_list`。详见 [状态化工具与桥接](docs/stateful-tools.md)。

## 顺序批次回归（M3.4）

```powershell
python -m dsh_eval --batch fixtures/evaluation/recovery.batch.json --run
```

会调用真实模型，顺序执行路径过时恢复、暂时读取失败恢复及同用例重置三项。每项新建 home / workspace / 会话和状态，输出 `runs/batches/<batchId>/batch-result.json` 及逐项证据。清单中的 failurePolicy 显式选择 continue / stop；人工中断或无法确认清理时停止后续任务。格式、状态与退出码见 [批次运行](docs/batch-runner.md)。

## M4.1 重复试验

```powershell
python -m dsh_eval --experiment fixtures/evaluation/recovery.experiment.json --run
```

该清单将暂时读取失败恢复用例执行两次真实模型任务，各自从初始状态开始。实验配置完整替换用例的 configRef；可在清单中显式增加配置或重复次数。新结果写入 `runs/experiments/<experimentId>/experiment-result.json`，保留逐次证据与分组统计。取消、无法评测和 skipped 分别计数；token 与计时只汇总有观测的样本。格式、分母、计时范围及限制见 [重复试验](docs/experiments.md)。

## M4.2 配置比较报告

对已经结束的实验运行以下命令，不调用模型：

```powershell
python -m dsh_eval --report 'runs/experiments/<experimentId>/experiment-result.json'
```

新建 `runs/reports/<reportId>/report.json`、`report.md` 及逐项复验结果，原实验不覆写。报告先核对冻结任务 / 环境 / 预算 / 断言、身份、实际请求路由和来源，再按同用例与重复编号计算右侧减左侧的描述性差值。保留全部计划分母、匹配覆盖、缺失及溢出原因，不混用合成 / live 来源。只有一个配置也可生成报告，但没有配置间差值；不同 ID 指向同一 configRef 也不视为不同模型。

`--reports-root` 可指定新报告目录的父目录。命令行 JSON stdout 固定 UTF-8。退出码 0 只表示报告生成成功，任务分类在报告中分别保留；输入或输出错误为 2。当前支持一个实验，不计算置信区间、显著性或赢家。格式、配对条件和不确定性范围见 [配置报告](docs/configuration-reports.md)。

## 当前边界

- 只录制插件观察到的新增事件；不会补齐加载前、恢复会话或 fork 继承的历史。`run.json` 明确标注 `live-events-only`，这些日志不能直接作为完整会话恢复文件。
- 已完成异步写入和封存不代表断电时绝对可靠；没有 fsync、跨进程恢复或日志轮转。状态替换使用同目录临时文件与 rename，当前 Windows 本地文件系统检查通过。
- SHA-256 用于一致性校验，不是签名。新版本 2 元信息可发现保留的清单中登记的整对会话文件缺失；旧格式仍无法检测这类删除。清单、版本、日志与摘要同时被改写，或整个运行目录被删除，均不在检测保证内。
- 已验证 M2.3 固定基线、M3.1 合成离线断言和 M3.2 受控真实单用例闭环；M3.3 状态化工具、M3.4 顺序批次、M4 重复试验 / 离线报告及 M5 本地浏览已完成当前范围。Windows 无模型云端 CI 已通过；配置差值由合成重复样本验证，历史真实任务只验证单配置报告，少量验收样本不构成模型表现或性能提升结论。

## 下一阶段

M2 基线与 M3 至 M5 已完成当前实现范围、本地验证和 Windows 无模型云端 CI 验收：

后续语言分工：JavaScript 继续负责 Harness 插件、实时录制、宿主适配和现有 inspect；Python 已实现用例加载与离线断言、状态化环境、顺序批次、重复统计及配置报告。实时跨语言工具桥接已实现，具体边界见 [架构说明](docs/architecture.md) 与 [修改记录 007](docs/changes/2026-10-14-007-python-evaluation-plan.md)。

1. M3.1 已完成：版本化用例、caseRunId、三维结果与 Python 离线证据断言；验证为合成轨迹。
2. M3.2 已完成：Python 驱动受控真实 headless 用例，验证正常完成、启动 / 路由错误、超时 / 取消及专用进程退出。
3. M3.3 已完成：Python 状态化工具环境与 JavaScript 实时桥接，两个真实模型恢复用例通过。
4. M3.4 已完成：顺序批次、环境重置和逐项结果清单，真实恢复批次与异常策略验证通过。
5. M4.1 已完成：实验清单、配置与重复编号、明确统计分母及已观测指标；95 项 Python 检查与新实验两个真实恢复任务通过。
6. M4.2 已完成：冻结输入核对、独立复验、来源与路由匹配配对、JSON / Markdown；117 项 Python 检查及四个历史真实样本报告通过，本批没有新模型调用。
7. M5 已验收：本机只读结果与证据浏览、保存分母 / 配对覆盖、JSONL 分页及 Windows 无模型 CI；`e47de36` 的云端运行中 134 Python、44 Node、31 文件语法、compileall 与合成 demo 均通过，历史页面验证保留。

M1 至 M5 主路线保留原验收。新增 [M6 扩展](docs/plans/m6-reliability-validation.md) 分四批，当前已完成 M6.1 的本地实现与验证；下一批是 M6.2 单条事件限制和资源基线，余三批。本批没有触发新的云端 CI 或模型调用，不把 M5 云端通过作为新改动的验证。原交付范围见 [M3 与后续计划](docs/plans/m3-regression-evaluation.md)。

## 开发文档

- [M2 开发方案](docs/plans/m2-reliable-recording.md)：M2.1、M2.2 和 M2.3 受控联调基线已完成。
- [M3 与后续计划](docs/plans/m3-regression-evaluation.md)：从固定 fixture 检查推进到用例、单次运行、实时工具环境和批次评测。
- [开发进度](docs/progress.md)：当前已实现和已验证的能力、限制及后续验收目标。
- [M6 方案](docs/plans/m6-reliability-validation.md) 与 [运行会话清单](docs/run-manifest.md)：运行级成员、写入顺序、新旧版本和剩余三批。
- [架构与技术取舍](docs/architecture.md)：插件接入、日志格式、Promise 队列、错误和关闭逻辑。
- [评测格式](docs/evaluation-format.md)：版本 1 / 2 用例、证据与结果、离线命令。
- [单用例运行](docs/single-case-runner.md)：真实 headless 入口、环境、预算、退出事实和验证边界。
- [批次运行](docs/batch-runner.md)：顺序执行、输入快照、状态重置、失败策略与结果清单。
- [重复试验](docs/experiments.md)：实验清单、样本与实际配置关联、统计分母及指标缺失口径。
- [配置报告](docs/configuration-reports.md)：冻结实验复验、实际配置 / 来源配对、差值、覆盖与不确定性。
- [修改记录](CHANGELOG.md)：按开发批次索引修改内容和验证依据。
- [修改记录模板](docs/templates/change-record.md)：后续改动使用的记录格式。

后续每批修改同步维护对应文档，规则见 [开发约定](AGENTS.md)。当前状态随开发更新，历史修改和验证结果保留在批次记录中。最新复核日期为 2026 年 10 月 21 日（Asia/Shanghai）。

公开仓库保留源码、测试和技术文档。原始日志、依赖缓存、个人笔记及本地凭据由 `.gitignore` 排除；环境变量示例只包含占位值。

官方接口参考：[会话事件](https://deepseek-harness.github.io/deepseek-harness/en/reference/subsystems/session)、[扩展插件](https://deepseek-harness.github.io/deepseek-harness/en/reference/cookbook/extension-cookbook)。
