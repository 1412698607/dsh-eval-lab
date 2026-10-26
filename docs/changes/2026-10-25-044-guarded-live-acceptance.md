# 修改记录 044 带计划约束的真实小批验收

日期：2026 年 10 月 25 日，Asia/Shanghai。类型：用例 / 测试 / 真实验收 / 文档。插件版本：0.1.2。相关 Git 提交：本批尚未提交，HEAD 仍为 `b309aa50b7cf8c9f750b2ff641a653313398e575`，分支 `20261024/feat/m6-4-web-lifecycle`。开始时 041–043 的 18 份未提交文件均保留；本批不提交 / 推送或新跑云端。

## 问题与目标

本批增加小规模真实模型验收。041–043 的上限、执行前计划指纹、原始载荷快照与报告复核尚只做无模型验收，需要以可控数量验证真实宿主 / 模型链路。

本批沿用现有 deepseek-official / deepseek-flash，选择 direct-read / retry-once 两个既有用例各两次，共四个实际模型任务，失败即停。新增固定清单和无模型回归，再用上限 4 / 预览指纹执行并离线报告。没有把这一批扩展为十用例重复或第二配置比较。

## 文件修改

| 文件 | 修改前 | 修改后 | 原因 |
| --- | --- | --- | --- |
| fixtures/evaluation/core/guarded-acceptance.experiment.json | 无固定小批清单 | 两用例 × 单配置 × 两轮，failurePolicy=stop | 让真实验收范围明确且可复用 |
| test/test_guarded_acceptance.py | 无该入口回归 | 新增 3 项无模型测试 | 数量 / 顺序 / 配置 / 停止策略、两类拒绝及完整合成执行 / 报告链路 |
| README、experiments、configuration-reports、core-evaluation、progress、M3 / M6 方案、CHANGELOG | 原 043 状态及验收范围 | 新清单入口、实际结果、环境失败和当前边界 | 与已实现 / 实际验证一致 |
| docs/guarded-acceptance.md、本记录 | 无独立说明 | 可复现命令、全部分母 / 指标与风险 | 公开文档足以接续，不依赖私人日志 |

生产执行代码、JavaScript、旧用例 / 断言和历史 001–043 记录均不改；架构与格式未变，不重复追加架构变更。041–043 原未提交内容继续保留。

## 实现与技术取舍

直接复用已有两个版本 2 用例，保留每项 120 秒任务期限、原工具证据和 after 顺序约束；实验按轮次 / 用例 / 配置执行，每次独立 home / workspace / session / 故障状态。清单只增加组合方式，没有复制用例、引入调度器或修改配置 / 预算语义。

预览生成 counts=2 / 1 / 4、maxSamples=4、failurePolicy=stop 及版本 1 指纹。实际 --run 携带同一上限与预期摘要，通过后保存原始载荷 / 冻结输入，执行后 --report 复核。一个任务可能多次请求模型，四任务不等于四次调用；本批不声明 token / 费用硬限额。

首轮输出根选择过深，实验 5ffa19f5-3d81-4640-b7cb-fae7df402d42 在第一项 prepare 阶段失败：当前宿主 plugin-manager 的 mkdtemp `.plugin-manager/logs/operation-XXXXXX` 报 ENOENT，adapterProcessStarted=false、host 为空且没有录制。CLI 返回 2，实验 stopped / unevaluable，planned=4、attempted=1、finished=1、skipped=3。此时没有启动 Agent / 模型，不把 source=live 声明或 attempted=1 说成已调用模型。

保留原失败结果，另以短目录单独执行同一宿主的离线插件准备，processStarted / processExited 均 true、prepare 成功，没有调用模型；随后使用短输出根 runs/g44 执行原定四个真实任务。单独记录本机当前安装器的深目录兼容问题，没有修改宿主、映射盘符或放宽路径安全检查，也不推定所有 Windows 文件操作具有同一限制。该准备失败未消耗实际模型任务，后续没有重跑任何已调用模型的任务。

## 验证

环境：Windows、Python 3.12.0、Node v24.14.0、CLI / SessionStore 0.2.0-rc.2、Cordis 4.0.4。仅引用原凭据路径，不打印 / 复制密钥或修改原 profile；每项新 home 离线安装本地 link 插件。完整回归在获准环境运行，不以受限子进程失败充当通过。JavaScript 未改，不重复 85 Node / 41 JS 历史检查。

| 命令或操作 | 实际结果 | 证明的范围 |
| --- | --- | --- |
| `python -m unittest discover -s test -p test_guarded_acceptance.py -v` | 新增 3 项 / 0.967 秒，OK | 固定清单、启动前 cap / 指纹拒绝、真实 Node 合成适配器四样本到计划 / 样本报告；未调用模型 |
| `npm.cmd run test:python` | 获准完整 241 项 / 50.782 秒，OK | 当前所有 Python 回归，含真实子进程 / 目录别名 / 本机服务；未调用模型 |
| `python -m compileall -q dsh_eval scripts test` | 退出码 0 | Python 编译检查 |
| 新四任务清单 --plan --max-samples 4 | 退出 0、stderr 空，valid=true / modelCalled=false、counts=2 / 1 / 4、stop、指纹已保存 | 真实执行前预览，不创建运行身份 |
| 首轮同清单 --run，带上限 / 预期摘要及显式匹配宿主路径 | 准备失败，stopped / unevaluable，1 attempted / 3 skipped，实际模型任务 0 | 新计划快照正确保存，失败即停生效，深目录环境失败保留 |
| 短目录同一宿主离线 prepare | prepared，准备进程已退出 | 先排除安装目录问题，没有模型调用 |
| 新清单 --run --max-samples 4 --expected-plan-sha256 <预览指纹> --runs-root runs/g44，显式匹配宿主路径 | 退出 0，实验 16777431-b937-4345-a37a-4a9edb7bb472，四个真实任务 completed / complete / passed | 首次真实验收 041–043 新链路，失败 / 跳过分母另保留，不自动重跑 |
| 对成功实验实际 --report | 返回 0，报告 58c9abe1-3811-467c-91ef-0249ef974515，计划 verified、四样本 verified / matched / live、changedFields 全空 | 原输入 / 来源 / 实际路由 / 录制 / 断言独立复核；comparisons 为空 |
| 对首轮准备失败实验实际 --report | 返回 0，计划 verified、一项样本 verified / unevaluable、三 skipped | 计划一致不等于录制或任务通过，原失败不被成功批次覆盖 |
| --run 携带 --max-samples 3 或错误预期摘要 | 两次均返回 2、stderr 空、未创建新输出根 | 真实 CLI 启动前拒绝，没有追加模型任务 |
| 复验前后摘要及自有 CLI PID 检查 | 成功实验 80 份 / 首轮 22 份选定证据摘要均不变；四个专用 PID 均不存在 | 仅核对输入 / 结果 / runtime / setup / 原始输出 / 录制及明确本次进程，不扩张到所有外部文件 / 进程 |

真实成功实验 planned=4、attempted=4、finished=4、skipped=0、errors=0，passed / failed / unevaluable=4 / 0 / 0，三个比例分子 / 分母均为 4 / 4；只描述本次任务。四个执行 / 录制 / 会话身份分别唯一，四份 run 清单 sealed，实际录制限制默认 1 MiB / 16 MiB。host 均正常关闭、退出 0、未强停，准备进程退出、stdinWriterStopped=true。

实际 11 个已结算模型事件、7 个工具调用；totalTokens=82672、inputTokens=29027、outputTokens=397，原始 cacheReadTokens=53248 / cacheWriteTokens=0；不由 input + output 补造 total。四项 elapsedSeconds 合计 22.282 秒含准备 / 执行 / 清理，费用全部缺失。逐项结果与完整边界见 [验收说明](../guarded-acceptance.md)。

证据存入新忽略目录：开始状态和 561 份受保护旧文件摘要、测试 / 编译环境、plan.json、只运行一次的原 / 短目录执行脚本及对应命令 / 退出 / stdout / stderr、离线准备、两个实验的复验和摘要、真实路由 / 生命周期 / usage 审核、精确 PID 查询。所有输出新建，不覆盖旧证据；公开文档不链接原始模型日志。交付核对通过：68 份公开 Markdown / 478 个相对文件链接、含 041–043 的 23 份预期未提交文件、561 份旧文件和 22 / 80 份本批选定证据摘要、HEAD / 忽略规则及空白；git diff --check 通过，仅有 LF / CRLF 转换提示，runs / private-notes 无跟踪。

## 风险与后续

本批固定入口及真实小批验收完成，041–044 尚未提交 / 推送或进行新云端验收；首轮环境失败保留。深目录兼容问题目前通过选择短输出根处理，未改宿主长路径实现或宣称跨平台修复。

只验证单配置、两个用例各两次，未执行全部十用例重复或第二配置；不推断模型总体成功率、配置优胜、性能 / 费用提升、显著性或供应商账单。token / 步骤 / 费用限制、证据签名、事务快照等既有局限不变；后续扩大范围需明确配置、重复次数和任务规模。

## 文档同步

同步 README、CHANGELOG、进度、实验 / 配置报告 / 固定评测集、M3 / M6 方案、新独立验收说明。架构 / 数据格式未变，保留历史记录。
