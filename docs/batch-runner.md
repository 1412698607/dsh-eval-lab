# M3.4 顺序批次回归

更新：2026 年 10 月 19 日，Asia/Shanghai。Python 顺序调度复用单用例 runner、状态化环境和 Node 宿主；插件保持 0.1.2。批次输入 / 结果格式为版本 1，用例 / 证据 / 单项结果继续支持既有版本。

## 运行

在仓库根目录执行，以下批次会调用真实模型三次，每项都有自己的准备和任务预算：

```powershell
python -m dsh_eval --batch fixtures/evaluation/recovery.batch.json --run
```

公开清单按顺序运行 stale-path、retry-first、retry-reset；后两项引用同一个 retry-read 用例，分别从一次暂时读取故障重新开始。现有 `--case --run` 和 `--case --evidence` 命令保持。匹配宿主、凭据路径引用和固定组件要求见 [单用例运行](single-case-runner.md)。

`--batch` 必须同时提供 `--run`，不能组合 `--case`、`--evidence` 或 `--output`。`--runs-root` 为新批次目录的父目录，默认 `runs/batches`；每次追加新的 UUID 子目录。`--host-modules` 传给每一次宿主准备。可选 `--cancel-after-stream` 是验收控制，会对每个实际启动项的首流触发取消；默认不使用，配合 stop 策略可检查取消后跳过剩余项。

stdout 输出批次 JSON。退出码：0 表示整批 passed；1 表示已明确存在普通任务 failed 且没有无法评测项或基础设施错误；2 表示 unevaluable、输入错误或输出失败。停止后尚未执行的项保持 skipped 和空结果，不推定任务成功或失败。

## 输入：batchFormatVersion 1

```json
{
  "batchFormatVersion": 1,
  "batchName": "stateful-recovery",
  "failurePolicy": "continue",
  "cases": [
    { "entryId": "first", "casePath": "retry-read.case.json" },
    { "entryId": "reset", "casePath": "retry-read.case.json" }
  ]
}
```

| 字段 | 约束 |
| --- | --- |
| batchFormatVersion | 整数 1，拒绝布尔值和未知版本 |
| batchName | 非空名称，不用作文件路径 |
| failurePolicy | 必填 continue 或 stop |
| cases | 非空有序数组；每项仅含 entryId / casePath |
| entryId | 批内唯一非空标识；不是文件名，允许同一 caseId / casePath 多次出现 |
| casePath | 相对清单所在目录解析的 POSIX 路径；拒绝绝对路径、盘符、反斜杠、空或点分量；可用 .. 引用上级目录中的用例 |

批次开始前读完并校验所有用例的格式、headless 和插件版本，失败时不启动模型。实际文件名和环境准备等运行期检查仍由单用例 runner 执行。所有输入在首次任务前保存快照，后续修改原始用例不会改变本批剩余项；每项自己的 configRef 决定请求配置，没有隐式全局配置覆盖。

每个用例可以独立声明可选 recorder.maxEventBytes / recorder.maxPendingBytes，批次预检同样拒绝非法值，并原样保存在 inputs 与各执行 case.json 中；不是 batch 清单的顶层字段。后续原文件修改不改变已冻结的录制配置；省略时各自使用内置默认值。准备阶段和实际 run.json 的核对方式见 [单用例运行](single-case-runner.md)。

## 隔离、关联与进度文件

054 为实验绑定增加内部 API 的可选 batch_id：有效 UUID 在启动前确定并使用，新目录仍不覆盖；未指定时保留原自动生成行为。实验预留身份不代表已创建批次或调用模型；绑定的实际结果仍需 [实验预检](experiment-resume.md) 核对。

[058](changes/2026-10-27-058-resume-lock-report-version.md) 增加内部 _lock_stack 参数，由实验的 ExitStack 保留 run_batch 取得的同一锁，直到实验最终 checkpoint 完成。普通调用省略该参数时仍自行取得 / 释放批次锁；没有跳过锁或先释放再重取。命令和保存格式不变。

2026 年 10 月 26 日新增 [批次级安全续跑](batch-resume.md)：新批次额外保存 resumeSupportVersion=1、完整冻结输入的 inputFingerprint 和 `.batch-execution.lock`。原进程运行时持有内核锁；续跑复核后只对明确未开始的项创建新批次，原进度 / 终态不覆盖。旧批次不补造协调元信息，执行未知项不自动重跑；原失败策略继续有效。该范围不代表会话恢复、断电可靠或实验汇总自动整合。

```text
runs/batches/<batchId>/
  batch.json                  路径改写为 inputs/ 的可再次运行清单
  inputs/0001.case.json        启动前冻结的全部输入
  inputs/0002.case.json
  cases/<caseRunId>/           原有独立用例执行目录
    case.json                 该项实际使用的用例快照
    home/ workspace/ pnpm-store/
    traces/<runId>/
    evidence.json evaluation.json runtime.json
  batch-result.json           本批进度及终态
```

每次调用 run_case 都新建 caseRunId、workspace、home、安装 store、Harness 会话及 Python 环境；不复用上一项的故障计数或请求缓存。batchId 写入 evidence / evaluation，清单以 entryId + caseRunId 映射重复用例，runId / sessionId 继续来自实际宿主和录制。开始前失败时可以没有这些实际身份。

本批运行期间在开始项和结束项后更新 batch-result.json：在同目录新建独立临时 JSON，再 replace 当前快照。它是活动进度文件，允许本批更新；终态不再写，后续运行使用新目录。普通运行不提供 fsync 或任意崩溃恢复保证；052 的受限批次续跑见上文，不能恢复正在执行的模型会话。进程被强杀或磁盘写入失败时，文件可能保留 running 状态和临时文件；running 不是成功，写进度失败会停止后续启动。

已保存的 batch.json 可再运行，仍会创建全新批次与会话；这会重新执行任务和模型请求，不是轨迹重放。离线复验单项时使用其自身 case.json / evidence.json：

```powershell
python -m dsh_eval --case 'runs/batches/<batchId>/cases/<caseRunId>/case.json' --evidence 'runs/batches/<batchId>/cases/<caseRunId>/evidence.json'
```

## 结果：batchResultFormatVersion 1

| 字段 | 含义 |
| --- | --- |
| batchId / batchName / failurePolicy / mode | 本次 UUID、名称、明确策略；mode 固定 sequential |
| batchDirectory / sourceManifest / manifestPath | 当前绝对输出目录、原始清单路径及保存的 batch.json 路径 |
| startedAt / finishedAt | 实际观察的 UTC 时间；活动文件 finishedAt 为 null；不是性能统计 |
| status / stopReason / outcome | 调度状态、停止原因与批次结论，分别解释 |
| entries | 保留输入顺序的逐项结果，不丢弃失败或 skipped 项 |

每项保存 entryId、caseId、原始用例路径、冻结 casePath、requestedConfiguration，以及 status。开始执行时分配 caseRunId / caseDirectory；尚未启动项保持 null。caseRunId 可以表示已安排但尚未产生会话的尝试，不等于已经调用模型。

有单项结果后保存相对批次目录的 evaluationPath / evidencePath / runtimeReport / runDir、实际 runId / sessionId / configuration，以及 executionStatus / recordingOutcome / assertionOutcome / outcome。原始 evaluation.json 是详细断言依据；调度器核对保存结果与返回值、batchId、caseRunId 和 caseId。异常时保留 error，可能已有部分执行目录，但不假造缺失结果路径。

## 失败、取消与清理策略

| 情况 | 后续行为 |
| --- | --- |
| continue 且单项非 passed | 保存结果、确认专用进程和写线程退出后继续；包括普通失败、超时、受控取消、运行错误和证据不足 |
| stop 且单项非 passed | 剩余项标 skipped；status=stopped、stopReason=failure_policy。若已无剩余项，调度状态为 completed |
| 人工 KeyboardInterrupt | 无论策略如何都停止后续；status=interrupted、stopReason=user_interrupt；保留已完成和可取得的当前结果 |
| 无法确认清理 | 无论策略如何都停止；status=error、stopReason=cleanup_unconfirmed，保留单项实际结论 |
| runner 意外异常、结果丢失或关联错误 | status=error、stopReason=runner_error，当前项 error，其余 skipped |
| 快照 / 进度落盘失败 | 抛出错误并停止启动；保留已有单项结果及最后可用的进度，不补造终态 |

准备阶段记录专用准备进程是否启动 / 退出。执行阶段由 runtime.adapterProcessStarted 区分启动事实：尚未尝试创建或 Popen 以 OSError 启动失败时为 false，成功取得适配进程时为 true，创建过程被中断等未确认情况为 null。明确 false 时没有执行适配进程待清理，运行错误按 continue / stop 处理；runId / sessionId / 实际配置保持 null，不补造身份或退出码。

已启动或启动事实缺失 / 未知时，仍核对适配进程退出码、stdinWriterStopped，以及宿主 childClosed、未创建 child 的事实或成功返回的自有进程树强停路径；不能从空 supervisor 推断未启动。人工中断始终先停止整批。当前受控 Windows 宿主范围内确认后才进入下一项，不推定任意外部工具进程树或其他平台可靠。

batch status=completed 仅说明排定项都执行完，不代表任务全部通过。outcome 规则：基础设施错误、人工中断或任一单项 unevaluable 优先得到 unevaluable；否则有明确任务 failed 则为 failed（即使 stop 跳过后项）；只有全部项完成且都 passed 才为 passed。批次本身不计算通过率或配置比较；M4.1 实验入口复用此调度，在上层记录重复编号和指标汇总，见 [重复试验](experiments.md)。

2026 年 10 月 21 日起，版本 1 逐项结果增加可选 source / metrics，来自该次 evaluation，不改变 status、清理门槛和失败策略。尚未执行项为 null；历史结果缺少指标仍保持缺失，不补为零。

## 验证范围

2026 年 10 月 19 日修复适配器未创建时误报 cleanup_unconfirmed 的审查问题：18 项批次检查、完整 76 项 Python、42 项 Node、29 文件语法与无模型真实桥接通过。启动失败 / 中断为异常注入，未新增实际模型任务；缺失启动事实不放行后项。详见 [修复记录 016](changes/2026-10-19-016-m3-4-launch-failure-policy.md)。以下保留主体历史验证。

2026 年 10 月 18 日，73 项 Python（原 58 + 新 15）、42 项 Node、29 文件 JavaScript 语法和无模型真实注册 / 桥接检查通过。确定性批次测试使用真实 Node 子进程、Python 状态与原录制器 / fresh inspect，但宿主适配器为合成测试程序，不算模型任务。人工中断以注入 KeyboardInterrupt 检查，未进行手工按键验收。

实际模型批次已验证 stale-path、retry-first、retry-reset 三项 passed，独立会话与状态关联正确；另验证未知路由后继续 / 停止、真实首流取消后停止及专用进程退出。第一次旧提示批次缺少旧路径失败证据，保留为 unevaluable；明确任务必须先尝试引用后，新快照批次 passed，未覆盖旧日志。完整依据见 [修改记录 015](changes/2026-10-18-015-m3-4-sequential-batches.md)。下一阶段是 M4.1 重复试验与指标口径。
