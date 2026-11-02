# 修改记录 097 删除与编辑真实验收及错误文本修正

日期：2026 年 11 月 2 日，Asia/Shanghai。类型：真实验收 / 用例修复 / 测试 / 文档。插件版本：0.1.2。相关 Git 提交：尚未提交；HEAD 为已核实的 115c670，运行使用工作区中的 096 实现。没有修改生产执行、评测或统计逻辑。

## 问题与目标

096 的删除 / 精确编辑已有合成与组件验证，本批使用已有 DeepSeek Flash 配置验收正常操作、预期错误和两个工具的超时重试。首次三任务全部完成，但两份用例将内部桥接错误文本当成真实 Tools 呈现文本，精确断言漏写 `Error: ` 前缀，导致首轮 1 passed / 2 failed。

保留首轮冻结输入、错误判断和报告；修正当前公开用例与合成适配器，增加反例，再对受影响的两个用例各执行一个新任务。两个补验均通过，不把它们覆盖回首轮，也不把混合版本的五任务合成一个通过率结论。

## 文件修改

| 文件 | 修改前 | 修改后 / 原因 |
| --- | --- | --- |
| [stateful-mutations.experiment.json](../../fixtures/evaluation/stateful-mutations.experiment.json) | 无统一入口 | 三用例、一个配置、各一次的公开实验清单，支持任务数上限和计划指纹 |
| [edit-delete-errors.case.json](../../fixtures/evaluation/edit-delete-errors.case.json)、[edit-delete-timeout.case.json](../../fixtures/evaluation/edit-delete-timeout.case.json) | 四处 textEquals 使用无前缀内部错误 | 精确匹配实际录制中的 Error 前缀；错误码、路径、顺序、次数、答案与最终状态约束不变 |
| [mutation-adapter.js](../../scripts/fixtures/mutation-adapter.js) | 合成工具结果直接使用 Python response.text | isError 时按当前真实 Tools 呈现加 Error 前缀，成功文本不变 |
| [test_stateful_mutations.py](../../test/test_stateful_mutations.py) | 合成输出与错误期望同时遗漏呈现前缀 | 增加两个场景的错误文本核对，验证旧无前缀精确期望仍失败且最终状态仍通过 |
| README、progress、stateful-tools、evaluation-format、M6 方案、用例目录、CHANGELOG、本记录 | 只有无模型删除 / 编辑范围 | 记录首次失败、原因、修正与独立补验，区分内部响应和录制文本 |

## 实现与技术取舍

当前固定版本 Tools 的异常呈现为 `Error: ${message}`；Python 的 tool-response.text 和工具体抛出的 Error.message 本身没有该前缀。096 的组件检查直接调用工具体，合成录制也直接复制内部 text，因此未覆盖真实呈现层差异。实际安装的 dsh-tools 0.2.0-rc.2 错误呈现代码与本次真实轨迹均确认这一行为。

本批将用例四处 textEquals 修正为完整的 `Error: NOT_FOUND: missing.txt`、`Error: AMBIGUOUS_MATCH: settings.txt`、`Error: TOOL_TIMEOUT: settings.txt`、`Error: TOOL_TIMEOUT: obsolete.txt`。不改为宽松包含匹配，不在 evaluate 中剥离前缀，不改工具运行时返回。旧无前缀期望仍应判 failed，新反例覆盖这一点。

公开正常用例未修改。首轮计划为三项，使用 `max_samples=3` 和预检 SHA-256；failurePolicy=continue 仅让清理确认后的普通断言失败继续，未放宽异常清理规则。补验从当前公开清单筛选 expected-errors / timeout-retry，复制修正后的两个输入，使用新实验身份、`max_samples=2` 和独立新指纹。

## 真实执行与复验

Windows、Node.js v24.14.0、Python 3.12.0；实际 setup 为 CLI / SessionStore 0.2.0-rc.2、Cordis 4.0.4。配置均为 deepseek-official / deepseek-flash。每项 timeoutSeconds=120，超时用例中 eval_edit / eval_delete 各自首次延迟 1500 ms、期限 1000 ms；准备和清理另计，不提供 token / 费用硬限额。

| 运行 | 实验 / 报告标识 | 原计划 / 实际结果 |
| --- | --- | --- |
| 首轮 | experiment `6a99ad10-cb70-4bd9-853a-60753cb31eb6`；report `bd22cfb4-5903-4cdd-854d-b2bf51b3aadd` | 3 planned / attempted / finished；1 passed、2 failed，0 skipped / errors / unevaluable |
| 修正后补验 | experiment `aafeebde-25a2-45fe-a5d3-2dc79af23aec`；report `01ebe481-1c92-4dd9-9a43-bc3a78ffa900` | 2 planned / attempted / finished；2 passed，0 failed / skipped / errors / unevaluable |

首轮指纹 `d7ed62c1a2ada0b83a60e4fdf1009180b1f2f69dc9505313e6e16191d58a6775`；两任务补验指纹 `5926148c9689adba87cf082af90e3486a021e048d45a33f3e65443709b4d9462`。修正后的公开三任务清单以 max_samples=3 预览为 `c22e1338d1fe2886f2a2fddae0bc43a5675248176e516c2a38321486876ed45b`，本批未再执行该完整三任务版本。

| 场景 | 首轮证据 | 补验 / 当前覆盖 |
| --- | --- | --- |
| edit-delete | 8 条断言通过；编辑 / 删除各一次，最终 settings.txt 为 mode=ready 且其余文本保留，obsolete.txt 缺失、guard.txt 不变 | 正常用例与当前公开输入相同，未重复运行 |
| edit-delete-errors | 记录 Error: NOT_FOUND、Error: AMBIGUOUS_MATCH；模型各调用一次、回答 rejected，最终状态不变；前缀失配及 after 依赖导致 failed | 新任务 7 条断言通过，2 次工具调用；错误场景按预期通过，不把工具错误当成基础设施失败 |
| edit-delete-timeout | 两工具均先超时后成功重试，次数各二、最终状态正确、回答 done；前缀失配及 after 依赖导致 failed | 新任务 10 条断言通过，编辑 / 删除各两次；含读回共 6 次工具调用 |

首次正常任务共 6 次工具调用，包含额外读取；用例仅限定编辑 / 删除次数，未禁止这些读取。所有五项均 completed / complete，最终环境快照完整且通过状态断言；两次实验报告均为 plan verified、逐样本 verified / matched / live，changedFields 均空。verified 不表示任务断言全部通过，首轮报告仍为 1 / 2。

| 用量 | 首轮三任务 | 补验两任务 |
| --- | ---: | ---: |
| 已结算模型调用 | 15 | 9 |
| 工具调用 | 14 | 8 |
| 已报告 totalTokens | 117769 | 70268 |
| elapsedSeconds 合计 | 约 25.922 | 约 17.031 |
| 费用 | 全部缺失 | 全部缺失 |

累计实际执行五任务、24 个已结算模型调用、22 个工具调用、188037 已报告 totalTokens。耗时含准备 / 执行 / 清理，不是纯模型延迟或整体验收墙钟；token 不由 input + output 补算，费用不补零，不推断总体模型能力或性能 / 成本改善。

## 验证

| 实际命令或操作 | 结果 | 边界 |
| --- | --- | --- |
| `plan_experiment(..., max_samples=3/2)`、Windows `check_output_root(..., kind="experiment")` | 各自预检有效，输出根为被忽略的 `runs/m` | 预检不调用模型；完整安装路径先检查 |
| `run_experiment(..., max_samples=3/2, expected_plan_sha256=<对应指纹>)` | 上述首轮三项与补验两项 | 当前固定配置和受控虚拟工具，失败样本保留 |
| 新进程 `python -m dsh_eval --report <对应实验结果> --reports-root <独立报告根>` | 两份报告分别复验 3 / 2 项，计划与身份 / 路由 / 来源通过，结论保持 | 原冻结输入复验，报告生成退出 0 不等于任务全部通过 |
| 使用修正期望对首轮两份旧轨迹另存 `evaluate` 结果 | 两项均 passed，原冻结结果和原报告仍 failed | 仅用于确认用例错误的离线对照，不新增模型任务、不替换原样本 |
| 报告前后文件 SHA-256 | 首轮 64 份、补验 45 份选定文件摘要不变 | 覆盖实验输入 / 批次 / 用例 / 录制等，排除 home / workspace / 安装缓存 |
| 108 份初始代码 / 输入摘要比对 | 差异仅两个修正用例、合成适配器、对应测试 | 生产执行 / 评测逻辑未改动；新实验清单已在首轮预检前保存 |
| runtime / host / setup 及 OS PID 核对 | 五项准备和专用 CLI 均正常结束，无强停 / 协议错误，stdinWriterStopped=true；PID 31948、32224、30344、33452、29268 均不存在 | 只限定本次专用进程，不推定任意外部进程树 |
| ArtifactBrowser 读取补验报告 / 两份 evaluation 及七处工具结果定位 | 全部可读，按 runId / sessionId / seq 正确定位 | 读取层验证，未新增实际页面点击验收 |
| `python -m unittest discover -s test -p test_stateful_mutations.py -v` | 14 项通过，3.476 秒 | 新错误呈现反例及原正常 / 失败 / 超时 / 续跑报告回归，无模型 |
| `npm.cmd run check`；`python -m compileall -q dsh_eval scripts test` | 45 个 JavaScript 文件及 Python 编译通过 | 语法检查 |

修正后执行 `npm.cmd run test:python`，完整 477 项通过，307.775 秒，零失败 / 错误。最终八份本轮文档的 493 个相对文件链接目标均存在，三用例 validate_case 与公开三任务 plan 检查通过，`git diff --check` 通过。再次核对首轮 / 补验共 109 份源文件摘要不变；runs/m 与 runs/m-reports 均被忽略，Git 未跟踪 runs / private-notes。096 的 476 项 Python / 121 项 Node 及首次无模型验证保持历史，不冒充本轮结果。

## 风险与后续

当前三个场景各有真实通过证据，分别来自未修改的首轮正常任务和修正后的两项新任务；没有一次修正后完整三任务实验，不能把它们称作同一冻结矩阵的 3/3。两份公开用例的历史失败仍可从首轮冻结输入复现；新的公开完整清单只用于未来新运行。

每个场景的样本仍很少，未验证其他模型、跨平台、真实模型取消、重命名、目录删除或外部系统副作用。工具延迟是受控注入，不代表真实网络 / 磁盘自然发生超时。错误呈现绑定当前固定宿主版本，升级后应重新核对。

本批未提交 / 推送或新增远端 CI。原始模型内容、安装缓存及凭据引用保留在忽略目录，不加入公开仓库。

## 文档同步

同步 README、CHANGELOG、progress、evaluation-format、stateful-tools、M6 方案和用例目录。生产架构与格式版本未变，096 原验证记录不改写；当前验收结论与修正单列在本记录。
