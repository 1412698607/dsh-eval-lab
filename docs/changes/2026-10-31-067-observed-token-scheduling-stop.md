# 修改记录 067 按已观测 token 停止后续调度

日期：2026 年 10 月 31 日，Asia/Shanghai。类型：功能 / 测试 / 文档。插件版本：`0.1.2`。相关 Git 提交：本批尚未提交；已核实实现基线为 `9252c3e6dd245c533c0b0aec701c06d35413bf12`。

## 问题与目标

已有 `--max-samples` 限制计划任务数，`--stop-after` 按本轮任务数停止，但一项任务可能多次请求模型，任务数不能表示已报告的 token 用量。本批增加任务边界上的已观测 totalTokens 控制，让调用方在已有用量达到阈值或无法确认用量时停止后续调度，保留原计划与未开始项，供之后显式预检续跑。

该能力只使用任务结束后可用的指标，不在当前任务内截断请求，不承诺 token / 步骤 / 费用硬限额，也不根据不同厂商的 usage 推算可比费用。

## 文件修改

| 文件 | 修改前 | 修改后 | 原因 |
| --- | --- | --- | --- |
| dsh_eval/batch.py | 仅按任务数在完成检查点后停止 | 校验 stop_after_tokens，统计本轮有效 totalTokens 及缺失覆盖，在同一边界停止 | 复用既有调度和清理顺序 |
| dsh_eval/__main__.py | 没有 token 调度控制 | 四类执行入口接受 --stop-after-tokens；拒绝预览、单用例、报告和浏览 | 明确参数作用范围 |
| dsh_eval/experiment.py、resume.py、experiment_resume.py、experiment_resume_chain.py | 外层仅传递任务数控制 | 传递本轮 token 阈值，保存 stopAfterTokens / tokenUsage 和停止原因 | 首轮、批次及连续续跑行为一致 |
| scripts/fixtures/batch-adapter.js | 合成消息不报告 usage | 测试专用 DSH_TEST_USAGE 可向合成录制声明 usage，默认行为不变 | 用真实子进程、录制和 fresh inspect 验证调度，而非仅注入统计结果 |
| test/test_scheduler_tokens.py | 无该控制的回归 | 十一项用量、参数、优先级、检查点及续跑 / 报告检查 | 覆盖缺失、零、越界和历史复用 |
| test/test_experiment_fingerprint.py | CLI 转发检查只列旧参数 | 核对未指定 / 显式 token 阈值时的指纹、上限透传及三种任务退出码 | 新控制不改变原计划约束和退出码 |
| README、docs/batch-runner.md、batch-resume.md、experiment-resume.md、experiments.md | 未说明该参数 | 记录参数、结果字段、停止规则与实际运行示例 | 使用方式与代码一致 |
| docs/architecture.md、progress.md、plans/m3-regression-evaluation.md、plans/m6-reliability-validation.md、CHANGELOG、本记录 | 后续用量停止仍为候选 | 同步已实现的无模型范围与剩余限制 | 区分实现、模拟验证和真实模型证据 |

## 实现与技术取舍

1. Python API 增加仅关键字 `stop_after_tokens=None`，在读取输入或分配输出 / 领取前拒绝布尔、非整数和非正值。CLI 只接受批次、实验及两类续跑的 --run，省略保持原调度行为。
2. 每项结果与清理检查之后，按本轮已结束尝试统计 totalTokens；只接受有效非负整数，不用 inputTokens + outputTokens 补总量。用量覆盖随完成检查点一起保存，成功写入后才决定是否安排下一项；检查点失败不会启动下一项。
3. 原用户中断、清理不明、runner 错误和失败策略先处理。尚有剩余项时，先处理用量缺失 / 无效 / 求和超范围，再检查 token 阈值，最后检查任务数阈值。对应 stopReason / skipReason 为 token_usage_unavailable 或 stop_after_tokens。当前任务允许超出阈值；最后一项结束时仍按正常终态收尾，不补造一次停止。
4. 结果可选新增 stopAfterTokens 与 tokenUsage，格式版本不变。未启用时二者为 null；启用时 tokenUsage 包含 observedSamples、missingSamples、observedTotal。总和只包含可用值，没有有效值或总和超范围时为 null；零值有效，缺失不补零。未开始项不计入覆盖，异常结束的已安排尝试可增加缺失数。
5. 续跑的新批次重新累计；外层保存下游本轮 tokenUsage，历史复用项不计入阈值或覆盖，源阈值不自动继承。原输入 / 预览 / expected 指纹、maxSamples 完整矩阵检查、单次领取、祖先锁和未知任务阻断均保持原义。
6. 使用任务边界控制复用已验证的退出与检查点顺序，不另建在线用量采集或任务内取消机制。成本缺失、未结算模型尝试和厂商 usage 差异仍按现有口径保留。

## 验证

本批使用合成适配器和真实 Node 子进程、原录制器、fresh inspect 及 Python 断言，不安装真实宿主或调用模型。合成 usage 是测试声明，不能视为真实模型用量。

| 命令或操作 | 结果 | 证明的范围 |
| --- | --- | --- |
| `python -m unittest discover -s test -p test_scheduler_tokens.py -v`（首轮定向） | 十一项 / 12.926 秒，OK；其后补充缺失续跑、部分覆盖、任务数优先命中和末项缺失等边界 | 首轮功能与真实合成链路，最终完整套件另列 |
| 同一定向命令（补充边界后） | 十一项 / 13.398 秒，OK | 最终新增回归含真实录制与 fresh inspect，未调用模型 |
| `python -m unittest discover -s test -p test_experiment_fingerprint.py -v` | 十一项 / 0.276 秒，OK | 省略 / 显式 token 阈值的 CLI 转发与原计划约束 |
| `python -m unittest discover -s test -p test_*.py`（首轮受限环境） | 350 项 / 253.996 秒，1 失败 / 5 错误；失败为旧 CLI 转发检查遗漏新增参数，已修正并定向复验；四项监督器无法终止自有进程树，一项 Web 生命周期 setUpClass 因 spawn EPERM 失败，相关 19 项未执行 | 不记作完整通过；最终允许真实进程操作环境复验另列 |
| `python -m unittest discover -s test -p test_*.py -v`（最终允许真实进程操作环境复验） | 369 项 / 254.158 秒，OK，0 失败 / 错误 / 跳过 | 包含全部十一项新回归、更新的参数转发检查、真实进程树清理与 Web 生命周期合成子进程；未调用模型 |
| `npm.cmd run check` | 43 份 JavaScript 语法检查通过 | 合成适配器及既有脚本语法 |
| `npm.cmd test`（受限环境） | 89 通过 / 2 失败；两项 Web 生命周期检查的实际子进程 spawn EPERM | 该次不能记作全部通过 |
| `npm.cmd test`（允许真实子进程的环境复验） | 91 项通过，0 失败 / 跳过 | 两项真实子进程场景实际复验通过，无 mock 替代 |
| `python -m compileall -q dsh_eval scripts test` | 退出 0 | 当前 Python 代码及测试可编译 |
| Python 遍历当前工作区十二份 Markdown，核对相对链接、标题锚点、Git 跟踪及忽略规则 | 482 个本地链接、95 个不同目标，零错误 | 包含上一批 066 文档同步；目标存在、锚点有效，未链接忽略资料 |
| `git diff --check`、按路径检查 063 / 064 / 065 历史记录差异、`git ls-files -- runs private-notes secrets` | 补丁与历史记录检查退出 0，隔离目录无已跟踪文件 | 无空白错误、历史记录未覆写，原始产物保持隔离 |

六任务合成实验按每项报告 5 token、每轮阈值 8，实际按 2 / 2 / 2 执行；原实验及两轮续跑各新增观测 10，末轮正常完成。独立版本 3 报告六项 verified，历史复用 totalTokens=20 / 本轮新增=10，原文件摘要保持不变；浏览读取层能读取保存的阈值与本轮用量，未新增页面点击验收。缺失 totalTokens 不妨碍单项断言 passed，但会阻止启用该控制时继续安排下一项。

## 风险与后续

本批没有新增真实模型任务、提交 / 推送或云端 CI，不继承 066 的基线 CI 作为本批验收。063–065 及 066 的历史记录不覆写，原模型失败、跳过和验证范围保留。

阈值只约束后续调度：当前任务可明显超出 N，模型调用中途的未结算用量不可见，不是费用预算或全实验累计硬限额。跨轮续跑必须显式选择新的控制，历史复用和缺失指标仍可在报告中查看。真正的任务内 token / 步骤控制、其他 Windows 长输出路径与归档迁移仍需另定范围。

## 文档同步

同步 README、批次 / 实验 / 续跑运行说明、架构中的边界与可选结果字段、当前进度、路线图及 CHANGELOG。原始轨迹和运行产物仍不加入版本管理，公开文档只链接可提交资料。
