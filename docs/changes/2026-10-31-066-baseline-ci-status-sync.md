# 修改记录 066 基线与 CI 状态同步

日期：2026 年 10 月 31 日，Asia/Shanghai。类型：文档。插件版本：`0.1.2`。已核实实现基线：`9252c3e6dd245c533c0b0aec701c06d35413bf12`；本次文档修改尚未提交。

## 问题与目标

063–065 已提交并推送，但进度页仍将当前 HEAD 写为 3f22926，并把任务边界停止、六任务真实连续续跑和双配置八任务比较列为未提交。README 仍将旧 CI 称为最新实现验收，早期路线图也未说明后来完成的范围。本批核对实际本地 / 远端 SHA 和当前提交的无模型 CI，再同步当前状态与后续入口。

## 文件修改

| 文件 | 修改前 | 修改后 | 原因 |
| --- | --- | --- | --- |
| docs/progress.md | 当前 HEAD、063–065 提交状态与 CI 落后 | 更新当前基线、已提交范围、CI 证据及复核日期 | 当前状态与 Git / Actions 一致 |
| README.md | 版本 2 / 3 浏览仅标本地验证，旧 CI 被称为最新 | 指向 9252c3e 的 push / PR 无模型 CI 验收 | 使用者能找到当前验证依据 |
| docs/plans/m3-regression-evaluation.md | 当前入口停在早期双配置准备 | 增加当前补记并指向 M6 顺序，保留历史阶段 | 区分已完成范围与候选扩展 |
| docs/plans/m6-reliability-validation.md | 当前功能范围已记录，但提交 / CI 未同步 | 补充精确基线与两次 CI 验收 | 明确前四项完成范围与后续入口 |
| CHANGELOG.md、本记录 | 缺少本次状态修正依据 | 增加 066 导航与可复核结果 | 保留同步日期、范围和限制 |

## 实现与技术取舍

- 本地 HEAD、远端同名分支均为 `9252c3e6dd245c533c0b0aec701c06d35413bf12`，父提交为 3f22926。该提交包含 063–065 的 23 份代码、测试、清单和文档；同步前工作区干净。
- 只修正当前状态，并新增日期明确的复核结果。063–065 和其他历史修改记录不覆写，各批本地测试、失败、跳过、模型验收及当时的未提交状态继续保留。
- 通过 GitHub Actions API 查询精确 SHA 的运行，再逐次核对 attempt 1 的作业与步骤。两次运行均为 Windows 无模型工作流；CI 不替代真实模型端到端验收。
- 未读取原始云端日志，因此只报告运行、作业和步骤成功，不将 063 的 358 Python / 91 Node / 43 JS 写为本次云端实测数量，也不推断实际安装的 Node / Python 补丁版本。

## 验证

2026 年 10 月 31 日执行只读 Git / GitHub API 核对及文档校验；本批没有运行模型、重跑本地代码测试或触发 CI。

| 命令或操作 | 结果 | 证明的范围 |
| --- | --- | --- |
| `git status --porcelain=v1`、`git branch --show-current`、`git rev-parse HEAD` | 同步前工作区干净，分支为 20261027/feat/experiment-resume，HEAD 为上述完整 SHA | 本地当前状态 |
| `git ls-remote --heads origin 20261027/feat/experiment-resume` | 远端 SHA 与本地一致 | 当前实现基线已推送；不表示本次文档已推送 |
| `git show --format= --stat HEAD`、`git ls-tree -r --name-only HEAD` 按相关路径核对 | 当前提交包含 23 份变更及 063 / 064 / 065 记录 | 已提交实现和验收文档的归属 |
| `GET /repos/1412698607/dsh-eval-lab/actions/runs?head_sha=9252c3e6dd245c533c0b0aec701c06d35413bf12&per_page=20` | 返回 push / pull_request 两次运行，head_sha 均与基线一致，attempt 1 均 completed / success | 当前 SHA 的已存在 CI，无新触发 |
| 对上述两个 run 分别读取 `/actions/runs/<run-id>/attempts/1/jobs?per_page=100` | 各一个 deterministic 作业，作业及全部步骤 completed / success | 五个检查步骤及环境准备 / 收尾均成功，具体测试数量未读取 |
| `python -` 逐份扫描本次六份 Markdown 的相对链接，使用 Path.resolve / is_file、`git ls-files -z` 及 `git check-ignore --stdin` 核对目标 | 365 个本地链接、93 个不同目标，零错误；新增的 M6 当前后续顺序锚点存在 | 目标均在仓库内、存在且已跟踪或为本次新记录，没有忽略文件链接 |
| `git diff --check`；`git diff --exit-code HEAD --` 后附 063 / 064 / 065 历史记录路径 | 均退出 0 | 补丁无空白错误，三份历史记录未改写 |
| `git ls-files -- runs private-notes secrets` | 无输出 | 原始归档、私人资料和凭据目录没有已跟踪文件 |

| 事件 | 运行 / 作业 | 作业完成时间（Asia/Shanghai） | 结果 |
| --- | --- | --- | --- |
| push | [40925323432](https://github.com/1412698607/dsh-eval-lab/actions/runs/40925323432) / [123629158932](https://github.com/1412698607/dsh-eval-lab/actions/runs/40925323432/job/123629158932) | 2026 年 10 月 30 日 01:56:58 | 运行 / 作业 / 全部步骤 success |
| pull_request | [41180889577](https://github.com/1412698607/dsh-eval-lab/actions/runs/41180889577) / [124477893247](https://github.com/1412698607/dsh-eval-lab/actions/runs/41180889577/job/124477893247) | 2026 年 10 月 31 日 15:34:14 | 运行 / 作业 / 全部步骤 success |

工作流 [deterministic.yml](../../.github/workflows/deterministic.yml) 声明 windows-latest、Node 24 / Python 3.12；五个检查步骤为 `npm.cmd run check`、`npm.cmd test`、`npm.cmd run test:python`、`python -m compileall -q dsh_eval scripts test`、`npm.cmd run demo:eval`。本次仅核实已存在运行的状态，不将工作流声明当作云端实际补丁版本或测试数量。

## 风险与后续

本次只同步文档，没有生产代码、测试、配置、协议、架构或运行参数变更。CI 成功不扩大 064 的单配置六任务和 065 的两用例双配置八任务范围，也不改变八任务中七通过一失败的结论。

后续按使用问题加固 Windows 长路径、归档迁移与按已观测用量停止后续调度；当前没有 token / 步骤 / 费用硬限额。完整十用例双配置 / 重复扩大及其他渠道、并发、崩溃恢复、跨实验合并等能力仍需按需求另定范围，没有已确定的 M7 或固定工期。本次文档尚未提交 / 推送，不自动触发新的 CI。

## 文档同步

同步当前进度、README、M3 / M6 路线图及 CHANGELOG。架构和格式未变，不修改架构说明；历史修改记录、真实归档及测试结果保持原样。公开链接仅指向可提交资料和对应 GitHub Actions 证据。
