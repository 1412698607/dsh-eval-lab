# 修改记录 061 连续续跑交付与真实验收准备

日期：2026 年 10 月 28 日，Asia/Shanghai。类型：文档。插件版本：`0.1.2`。相关 Git 提交：已核实 059 / 060 的 23 份实现、测试和文档提交并推送为 `35cf77078beef07b764febd596eee1d7f7610bda`；本验收补记尚未提交。

## 问题与目标

将 059 连续续跑与 060 测试临时路径修复的交付状态绑定到实际提交，保留 967ab43 的原 CI 失败。准备下一批六项真实验收的输入，并在启动任何模型前检查续跑嵌套目录是否能完成真实宿主的离线准备。

## 文件修改

| 文件 | 修改前 | 修改后 | 原因 |
| --- | --- | --- | --- |
| 本记录、docs/progress.md、CHANGELOG | 059 / 060 仍保留当时未提交状态 | 记录 35cf770 的提交、CI 跟踪及 prepare-only 结果 | 区分本地检查、云端交付和真实模型任务 |
| docs/plans/m6-reliability-validation.md | 六项真实任务之前只说明边界停止入口 | 增加真实 CLI 嵌套路径准备的前置条件，记录扩展路径原型的验证边界 | 实际准备失败先于模型调用处理 |

## 实现与技术取舍

本批不修改生产代码。当前分支快进推送 35cf770，没有重写历史或合并其他分支。059 / 060 的历史“尚未提交”保留原样，进度单独更新当前状态。

候选输入由 guarded-acceptance.experiment.json 复制而来：保留 direct-read / retry-once 的原始用例和精确断言、deepseek-official / deepseek-flash 单配置及 stop 策略，将 repetitions 改为 3、experimentName 改为 continuous-resume-flash-6。使用原 plan_experiment、max_samples=6 只读预览，不执行实验；预览不表示远端模型、凭据或费用已验证。

准备检查分别创建全新的用例目录，保存相同 case.json，以 prepare_workspace 建立环境，再只调用 _prepare(directory, None, report)。该入口运行真实 CLI 的 plugin add --offline --ignore-scripts，不进入 case-host run 或 Agent 请求阶段。三次检查独立保存准备日志和结果，均确认本次进程退出。

## 验证

环境：Windows、Python `3.12.0`、Node.js `v24.14.0`。实际 setup 核对 CLI / SessionStore `0.2.0-rc.2`、Cordis `4.0.4`。

| 命令或操作 | 实际结果 | 证明的范围 |
| --- | --- | --- |
| `git fetch origin 20261027/feat/experiment-resume`、提交前比较 HEAD / origin | 两侧差异 0 / 0 | 交付前未落后于远端 |
| `git commit`、当前分支普通快进 push | 35cf770，23 份文件；967ab43 → 35cf770 | 059 / 060 的实现与修复已提交推送 |
| [CI run 40714317704](https://github.com/1412698607/dsh-eval-lab/actions/runs/40714317704)、job 122907733857 首次查询 | attempt 1、head_sha 精确匹配，in_progress；JS / Node 步骤随后 success，Python 当时进行中 | 首次查询不是全部成功，最终状态需另行核对 |
| 六项候选输入预览 | valid=true、modelCalled=false，cases=2 / configurations=1 / samples=6、maxSamples=6 | 现有输入与规模校验通过，未执行模型 |
| 同一候选的真实 `python -m dsh_eval --experiment <manifest> --plan --max-samples 6` | 退出 0、六项、modelCalled=false、UTF-8 JSON，stderr 为空 | 现有 CLI 预览入口通过；仍未启动任务 |
| 普通路径，模拟续跑目录层级，仅真实 CLI 离线准备 | 准备失败，mkdtemp ENOENT；processStarted / processExited 均 true | 当前续跑嵌套目录不能直接用于本机真实宿主准备 |
| 同一用例，较短的新目录，仅真实 CLI 离线准备 | prepared=true，进程退出 | 同配置的短目录对照通过 |
| 同一嵌套层级，另一个新目录，显式 Windows 扩展路径前缀的准备原型 | prepared=true，进程退出 | 一次真实离线准备原型通过，未接入产品，也未验证完整执行 / 证据关联 |

原始普通嵌套 case 目录为 216 个字符，其 home/profiles/headless/.plugin-manager/logs/operation-XXXXXX 模式为 277 个字符；短目录对照 case 为 77 个字符。嵌套目录的系统 GetShortPathNameW 没有返回更短的别名，不能依赖该目录的 8.3 名称绕过。原型只在 _prepare 入参上增加 Windows 扩展路径前缀，没有修改宿主或本项目源文件。

六项预览的计划指纹为 df54bafd7a735d83b47fcca384ec4cc048031964d6e9e1761ac6ec3580579055，版本 1。实际执行时仍需重做 fresh plan，不能把本次预览视为已冻结的未来运行。

## 新提交云端最终结果

后续重新读取 run / attempt jobs 及原始 job 日志，取得以下最终结果。首次 in_progress 的观察保留于上表，不用本地数量代替云端数量。

| 对象 | 最终结果 |
| --- | --- |
| [run 40714317704](https://github.com/1412698607/dsh-eval-lab/actions/runs/40714317704) | attempt 1，head_sha 精确等于 35cf77078beef07b764febd596eee1d7f7610bda，completed / success |
| [job 122907733857](https://github.com/1412698607/dsh-eval-lab/actions/runs/40714317704/job/122907733857) | 相同 head_sha，completed / success，各检查及收尾步骤均 success |
| JS 语法 | 原始日志确认 43 个 JavaScript 文件通过 |
| Node 回归 | 原始日志确认 tests 91 / pass 91 |
| Python 回归 | 原始日志确认 341 项 / 271.928 秒、OK |
| Python 编译与合成示例 | 两步骤均 success，示例 modelCalled=false |

因此 059 / 060 当前实现提交已取得独立云端验收。967ab43 原失败与本地普通 / 实际短路径复验继续保留各自范围，未增加模型样本。

## 风险与后续

本轮没有新增模型任务。六项真实连续续跑需先完成 Windows 路径方案的产品接入与准备 / 启动 / 证据路径验证，并实现和无模型验证任务边界停止入口，再按原批次 2、第一轮续跑 2、第二轮续跑 2 的安排验收。扩展路径的单次准备成功不代表完整真实续跑已修复，也不覆盖原 WinError 5、所有 Windows 文件系统或平台。

原 050 的 stop 失败与四 skipped 保留。035–059 的其他真实样本、未知执行阻断和完整性边界不变。日志与输入保存在忽略目录，公开仓库无需这些原始产物即可理解复验方法和当前限制。

## 文档同步

更新进度当前基线、M6 前置顺序和 CHANGELOG。没有修改生产格式、架构或运行命令；本补记无需重复运行完整代码测试。四份修改 / 新增 Markdown 的 238 个本地链接均存在且未被忽略，git diff --check 通过；runs / private-notes / secrets 无已跟踪文件。本补记及三份配套文档的验收状态更新保留在工作区，没有追加文档提交或触发另一轮 CI。
