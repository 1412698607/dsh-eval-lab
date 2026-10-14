# dsh-eval-lab

面向 DeepSeek Harness 的 Agent 行为回归测试项目。第一阶段实现实时会话轨迹记录，为后续测试用例、确定性断言和版本对比提供输入。

## 当前功能

- 作为 Cordis 插件订阅 `session/event`，保留原始事件，包括消息、工具调用、工具结果及轮次边界。
- 每次插件启动创建独立运行目录，每个会话写入独立 JSONL 文件。
- 使用异步写入队列保持同一会话的观察顺序，通过 `session/flush` 和插件卸载等待已排队写入完成。
- 写入失败时记录错误，后续 checkpoint 报错；失败会话停止继续录制，其他会话仍可写入。
- `0.1.2` 完成 M2.2：独立会话状态文件、计数和 SHA-256、待写入容量保护，以及离线 `inspect`；保留 M2.1 的 stderr 诊断和可移植配置。
- M2.3 已完成独立 Web / headless profile 的真实模型联调，新增固定 fixture 的 Python 证据检查；插件版本保持 `0.1.2`。

接入验证使用本机安装缓存中的 **DSH 0.2.0-rc.2 / Cordis 4.0.4**。插件声明对应的可选 peer，以供 Harness 检查版本兼容性。无需构建，也无需安装依赖即可运行模拟演示和单元测试。

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

`run.json` 包含格式版本、插件版本、运行 ID 和启动时间。JSONL 每行包含 `formatVersion`、`runId`、`sessionId` 和完整 `event`。哈希文件名避免会话 ID 被当成路径，原始 ID 仍保存在每条记录中。

状态文件使用独立的 `statusFormatVersion: 1`，包含 `recording` / `sealed` / `failed`、接收与写入计数、UTF-8 字节数、首尾序号及 SHA-256。`flush()` 保存检查点但保持 `recording`；`close()` 停止接收、排空队列后封存。插件使用 Cordis 的 `ctx.effect()` 注册关闭清理。

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

序号必须是严格递增的非负安全整数，允许从非零开始；缺口显示在 `gaps` 中（最多 100 项，完整数量在 `gapCount`），不补造历史。未知事件类型保留可读。旧 JSONL 可以诊断，但不能自动变成已封存片段。开放状态仅复核已保存的检查点前缀，后续完整追加不会被误判为摘要损坏。

请在写入停止后或稳定副本上检查；工具不提供与在线写入并发的一致快照。退出码表示录制片段可校验程度，不代表 Agent 任务通过，也不证明完整会话历史或断电可靠。

日志包含原始会话及工具内容。`runs/` 已加入 `.gitignore`；作品集展示可使用 `demo` 的模拟数据。

## 当前边界

- 只录制插件观察到的新增事件；不会补齐加载前、恢复会话或 fork 继承的历史。`run.json` 明确标注 `live-events-only`，这些日志不能直接作为完整会话恢复文件。
- 已完成异步写入和封存不代表断电时绝对可靠；没有 fsync、跨进程恢复或日志轮转。状态替换使用同目录临时文件与 rename，当前 Windows 本地文件系统检查通过。
- SHA-256 用于一致性校验，不是签名；同时篡改日志与摘要、删除整对会话文件都不在检测保证内。没有运行级会话清单，不能由磁盘上剩余片段推断所有会话都曾被保存。
- 当前仅验证 M2.3 的固定 fixture，不执行通用评测或生成通过率；尚未实现状态化工具 mock、通用任务断言、A/B 重跑和评测界面。

## 下一阶段

M2.1、M2.2 和 M2.3 的 Web / headless 受控联调基线已完成。下一步为 M3：

后续语言分工：JavaScript 继续负责 Harness 插件、实时录制、宿主适配和现有 inspect；用例管理、任务断言、状态化工具环境核心、批次调度，以及统计分析和报告优先 Python。M2.3 已实现固定 fixture 的 Python 证据检查，通用评测和实时跨语言工具桥接仍未实现，具体边界见 [架构说明](docs/architecture.md) 与 [修改记录 007](docs/changes/2026-10-14-007-python-evaluation-plan.md)。

1. M3.1：定义版本化用例、caseRunId 与结果分类，先实现 Python 离线证据断言。
2. M3.2：驱动一个受控真实 headless 用例，验证正常完成、运行错误和超时 / 取消。
3. M3.3：实现 Python 状态化工具环境与 JavaScript 实时桥接，覆盖路径过时、工具失败后恢复。
4. M3.4：实现顺序批次回归、环境重置和逐项结果清单。
5. M4/M5：在上述闭环完成后做重复配置比较、统计报告、结果浏览和持续集成。

这些均为待开发，具体交付、验收及渠道补充事项见 [M3 与后续计划](docs/plans/m3-regression-evaluation.md)。下一批入口是 M3.1；当前没有新增通用评测命令。

## 开发文档

- [M2 开发方案](docs/plans/m2-reliable-recording.md)：M2.1、M2.2 和 M2.3 受控联调基线已完成。
- [M3 与后续计划](docs/plans/m3-regression-evaluation.md)：从固定 fixture 检查推进到用例、单次运行、实时工具环境和批次评测。
- [开发进度](docs/progress.md)：当前已实现和已验证的能力、限制及后续验收目标。
- [架构与技术取舍](docs/architecture.md)：插件接入、日志格式、Promise 队列、错误和关闭逻辑。
- [修改记录](CHANGELOG.md)：按开发批次索引修改内容和验证依据。
- [修改记录模板](docs/templates/change-record.md)：后续改动使用的记录格式。

后续每批修改同步维护对应文档，规则见 [开发约定](AGENTS.md)。当前状态随开发更新，历史修改和验证结果保留在批次记录中。最新复核日期为 2026 年 10 月 15 日（Asia/Shanghai）。

公开仓库保留源码、测试和技术文档。原始日志、依赖缓存、个人笔记及本地凭据由 `.gitignore` 排除；环境变量示例只包含占位值。

官方接口参考：[会话事件](https://deepseek-harness.github.io/deepseek-harness/en/reference/subsystems/session)、[扩展插件](https://deepseek-harness.github.io/deepseek-harness/en/reference/cookbook/extension-cookbook)。
