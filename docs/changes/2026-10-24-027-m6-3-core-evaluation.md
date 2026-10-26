# 修改记录 027 M6.3 单配置固定评测集

日期：2026 年 10 月 24 日，Asia/Shanghai。类型：用例 / 测试 / 文档。插件版本：`0.1.2`。相关 Git 提交：本批尚未提交；已核实当前 HEAD 为 `5777f2d`，工作区保留上一批 026 的未提交修复，未覆盖或自动提交。

## 问题与目标

既有真实验收主要围绕少数读取 / 恢复任务，尚缺一个可整体复跑、覆盖不同环境情况的固定评测集。原 M6.3 建议约 8～12 用例、两配置与预算确认；本轮验收范围限定为 deepseek-flash 的 10 个用例，因此先交付单配置各一次范围，不把双配置或重复实验写成已验收。

目标是冻结 10 个任务、初始文件和故障状态，复用现有执行 / 录制 / 断言及报告链路，完整保留计划分母、实际路由、用量缺失和清理事实。先用无模型正反例验证断言，再执行清单中的 10 个任务；没有追加模型重跑。

## 文件修改

| 文件 | 修改前 | 修改后 | 原因 |
| --- | --- | --- | --- |
| `fixtures/evaluation/core/*.case.json` | 无固定扩展集 | 10 个独立版本 2 用例 | 覆盖读取、发现、引用链、归档干扰、缺失 / 空文件、中文、单 / 双路径暂时失败及组合恢复 |
| `fixtures/evaluation/core/core.experiment.json`、目录 README | 无整组入口 | 现有 deepseek-flash、1 配置、1 轮、10 任务，continue 策略，显式说明模型调用 | 固定规模，沿用标准冻结和隔离流程 |
| `test/test_core_suite.py` | 无新集验收 | 6 项无模型回归、30 份真实录制 / inspect 合成轨迹 | 检查正例可行性、错误答案与必要证据，避免答案正确即可通过 |
| `docs/core-evaluation.md`、README、用例 README、experiments | 分散的历史入口 | 用例范围、命令、真实结果及完整局限 | 可复现且不依赖私人资料 |
| progress、M6 方案、architecture、CHANGELOG、本记录 | M6.3 仍计划 | 记录本轮单配置范围及仍未执行的双配置 / 重复与 M6.4 | 当前状态与实际验收一致 |

本批没有修改生产 Python / JavaScript、CI 工作流或格式版本。现有工作区中的 `formats.py` / `case-host.js` 等修改属于 026，不归为本批实现。原用例与历史运行不改写，main.py 保留。

## 实现与技术取舍

直接编写静态 JSON 用例和标准实验清单，复用 experiment → batch → run_case → Python StatefulEnvironment / Harness eval_read、eval_list → recorder → inspect → evaluate → report。没有为 10 个固定任务增加另一套运行器、CLI 计划模式或新断言类型。

10 个用例都采用虚拟文件环境，故障状态由 Python 按路径保存，每个任务新建环境；原生工具无法直接读取这些虚拟初始文件。missing-file 要求真实 NOT_FOUND 结果，empty-file 要求实际成功读取及明确 EMPTY_FILE 答案；空结果不依赖 textContains 的空串匹配。目录发现约束成功列表包含目标，允许根目录和目标子目录，避免对合法查找方式过拟合。

参考动作 / 答案独立于用例断言手写，动作真实调用 Python 环境，结果经原 Node recordExample、实际录制器和 fresh inspect 验收，来源 synthetic。10 正例可通过；10 个只有正确答案的无工具轨迹为 unevaluable；10 个工具正确但答案错误轨迹为 failed。逐项删除 22 个必要调用 / 结果对，相关断言均不能通过；另 4 组检查列表替代路径及环境重建后故障重置。它们没有调用模型或真实 Harness 工具桥接，真实模型验收另行执行。

单配置清单不虚构第二套可用配置。现有 report 能读取单配置实验、重新核对全部冻结输入与路由并输出 comparisons=[]；本轮使用这一行为，未更改报告算法。必要工具断言不限制所有额外行为，也没有通用全序 / 指定次数断言，故障先后由既有状态化环境约束。

## 验证

环境为 Windows、Node.js v24.14.0、Python 3.12.0、CLI / SessionStore 0.2.0-rc.2、Cordis 4.0.4。

| 命令或操作 | 结果 | 证明的范围 |
| --- | --- | --- |
| `python -m unittest discover -s test -p test_core_suite.py -v` | 6 项通过，5.274 秒 | 固定用例正反轨迹与环境状态，非模型验收 |
| `npm.cmd run test:python` | 150 项通过，44.706 秒 | 获准环境完整 Python 回归，包含真实子进程 / 清理检查 |
| `npm.cmd test` | 79 项通过、无失败 / 跳过 | 现有 Node 回归 |
| `npm.cmd run check`、`python -m compileall -q dsh_eval test` | 36 个 JS 文件及 Python 语法通过 | 本地语法 |
| `python -m dsh_eval --experiment fixtures/evaluation/core/core.experiment.json --run` | 首次 10 / 10 通过，无追加重跑 | 10 个实际模型任务、真实隔离 profile / 工具桥接 / 录制与断言 |
| 对上述实验运行原 `--report` 对应 generate_report | 10 项 verified / matched / live，各项三维结果不变、changedFields 为空 | fresh inspect、冻结输入 / 身份 / 路由及指标复验，无新模型调用 |
| 原始证据摘要和专用进程核对 | 125 份 JSON / JSONL 摘要不变；10 个保存的 CLI PID 均已退出 | 不覆写历史、当前受控进程清理范围 |
| 公开 Markdown、结果表格、忽略规则及 `git diff --check` | 49 份 Markdown / 320 个相对链接有效，10 行结果与原报告逐项一致，文本检查通过 | 公开入口不链接私人 / 原始日志，runs / private-notes 无跟踪文件；只有既有 LF / CRLF 提示 |

实验 ID `6530df76-86e2-4ea1-80a9-86ca71e74e4e`，报告 ID `2a3253d3-69b8-49e9-9c09-51cd01baae7b`，完整逐项结果及可复现命令见 [固定评测集验收](../core-evaluation.md)。planned / attempted / finished 为 10 / 10 / 10，skipped / errors 为 0 / 0，passed / failed / unevaluable 为 10 / 0 / 0；10 项均 completed / complete / passed，全部请求路由匹配 deepseek-official / deepseek-flash，单配置 comparisons 为空。

观测到 32 次已结算模型调用、24 次工具调用，已报告 totalTokens 合计 242085；六项数值指标覆盖 10 / 10，费用覆盖 0 / 10、保持 null。原始 usage 包含 cacheReadTokens，不用 input + output 补算 total。单项耗时约 4.265～7.719 秒，合计 56.795 秒包含准备 / 执行 / 清理，不是纯模型延迟或整个命令墙钟。10 个 run 清单 sealed，默认事件 / 队列限制均正确保存；host 正常退出、无强停，准备进程和写线程退出。

本轮未执行云端 CI、smoke:host、check:output、资源测量或早期模型重跑，不借用历史通过作为本轮结果。真实模型及完整进程清理回归在获准环境执行，未用模拟替代实际子进程。

## 风险与后续

10 个任务各一次只描述该批样本，不能推断整体成功率提升、稳定性、统计显著性或模型成本。任务数不是供应商请求数或费用硬上限；墙钟预算也不是 token / 总退出硬限制。source 和 SHA-256 不是签名。

原建议的第二套真实配置和重复比较仍待选择配置与预算；下一批 M6.4 验证实际页面取消、宿主正常退出和处理中断，需要新的明确任务规模。真实原始输出留在忽略的 runs，公开用例可独立重跑但不会携带凭据或个人日志。

## 文档同步

已同步 README、用例目录说明、固定评测集验收、experiments、progress、architecture、M6 方案和 CHANGELOG。
