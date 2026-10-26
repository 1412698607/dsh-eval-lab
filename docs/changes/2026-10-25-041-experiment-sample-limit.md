# 修改记录 041 实验任务数上限

日期：2026 年 10 月 25 日，Asia/Shanghai。类型：功能 / 测试 / 文档。插件版本：0.1.2。相关 Git 提交：本批尚未提交；开始时核实 HEAD 为 `b309aa50b7cf8c9f750b2ff641a653313398e575`，工作区干净，分支 `20261024/feat/m6-4-web-lifecycle`。该提交已包含 040，旧记录中的未提交状态保留为历史，当前进度已修正。本批未核对该提交的新云端结果。

## 问题与目标

040 可以无模型查看计划，但预览 / 执行仍会完整展开矩阵；重复次数配置错误时，没有供调用方声明最大任务数的保护。本批增加实验任务数上限并补充无模型回归。

新增可选 --max-samples N，预览和实际运行共用数量检查。总数超过上限时，在读取用例、展开任务、生成身份和创建输出前拒绝；等于上限允许，不截断任务。默认不设上限以保留既有运行行为，本批不运行真实模型。

## 文件修改

| 文件 | 修改前 | 修改后 | 原因 |
| --- | --- | --- | --- |
| dsh_eval/experiment.py | 清单校验后直接读取用例 / 展开 | 共用入口检查可选 max_samples；新计划 / 实验结果保存 maxSamples | 预览和执行执行同一保护，拒绝早于副作用 |
| dsh_eval/__main__.py | 没有任务数限制参数 | --max-samples 仅接受实验的 --plan / --run 和正整数，传入共用路径 | 清晰的调用范围与错误行为 |
| test/test_experiment_limits.py | 无上限回归 | 新增 9 项无模型测试 | 覆盖计数、边界、非法参数、只读 / 无执行、极大重复及实际 CLI |
| test/test_experiment.py | 合成执行未带上限 | 四样本预览 / 实际执行在上限内一致，冻结清单重跑不继承参数 | 验证正常执行链路与旧默认兼容 |
| README、CHANGELOG、progress、architecture、experiments、M3 / M6 方案、本记录 | 040 入口与旧当前状态 | 新参数、格式兼容、当前提交、验证和限制 | 保持实现 / 使用 / 进度一致 |

## 实现与技术取舍

plan_experiment / run_experiment 新增仅关键字 max_samples=None，保留 run_experiment 原四个位置参数。_load_experiment 首先严格验证上限（type 是 int 且大于零，或 None），然后读取 / 校验实验清单，以 cases 条目数 × configurations 条目数 × repetitions 直接计算总数。重复条目或相同 configRef 仍各自计数；超限只抛出带实际数量与上限的 ValueError，不读取任何用例，不调用 _expand_samples、uuid4 或 run_batch。允许范围内继续原全部用例 / 组合预检、冻结和批次执行。

采用可选 CLI / API 参数，未任意引入默认数值或修改实验输入格式。新计划 / 实验结果使用同一版本 1，新增 maxSamples（未指定为 null），旧结果无需有此字段，离线报告不依赖它。参数不写入冻结 experiment.json；重新运行冻结输入仍需显式传入。预览后改动源文件，实际 --run 会重新计算；预览成功不是后续执行许可或输入冻结。

参数冲突、非法整数与非正值由 argparse 向 stderr 报错 / 2。超限预览沿用独立计划错误 JSON，valid=false、modelCalled=false、error / 2，没有 outcome；超限执行沿用实验错误 JSON，outcome=unevaluable、error / 2，不创建结果文件或伪造执行身份。没有调整原顺序、失败策略、隔离、录制、宿主配置或清理。

maxSamples 限制的是计划任务总数。每个任务仍可能多次请求模型，不能据此约束 token 或费用；未来 modelCalls / totalTokens / cost 估算仍为 null。它不提供清单 / 用例文件字节限额或内建的有限默认任务数，也不限制调用方选择过大的上限。

## 验证

环境：Windows、Python 3.12.0、Node v24.14.0。所有调用均为无模型静态预检或合成适配器 / 既有真实子进程回归，没有新增 Harness / Web 模型任务、提交、推送或云端运行。JavaScript 未改，不重跑或沿用旧 85 Node / 41 JS 语法为本轮结果。

| 命令或操作 | 实际结果 | 证明的范围 |
| --- | --- | --- |
| `python -m unittest discover -s test -p test_experiment_limits.py -v`，实现前 | 首批 8 项 / 0.169 秒，3 failures / 30 errors | 旧 API / CLI 没有上限；后续再增加预览后输入变化一项回归 |
| 同命令，实现后 | 最终 9 项 / 0.214 秒，OK | 2 × 2 × 3 计数、上限等于 / 高于 / 低于、None 默认、布尔 / 非整数拒绝、10^100 重复数、CLI / 无关模式 / 编码与无副作用 |
| `python -m unittest discover -s test -p 'test_experiment*.py' -v` | 最终 26 项 / 4.025 秒，OK；较早 25 项 / 4.208 秒记录保留 | 原实验 / 预览及新上限；真实 Node 合成适配器四样本顺序 / 身份 / 请求配置 / 预算 / 录制与预览一致，结果记录上限，冻结重跑默认不继承 |
| `npm.cmd run test:python`，受限环境 | 实际 200 项 / 52.210 秒，5 errors，不能计通过 | 四项自有进程树终止失败；生命周期类初始化的三个合成场景 spawn EPERM，19 项类测试未进入，因此数量少于完整套件 |
| 同命令，获准环境 | 完整 219 项 / 53.272 秒，OK | 真实子进程、目录别名和既有回归；没有以 mock 替代被拒绝的检查 |
| `python -m compileall -q dsh_eval scripts test` | 退出码 0 | Python 编译检查 |
| `python -m dsh_eval --experiment fixtures/evaluation/core/core.experiment.json --plan --max-samples 10` | 退出 0、stderr 为空，counts=10 / 1 / 10，maxSamples=10、valid=true、modelCalled=false | 现有十用例边界成功，无运行目录 |
| 同清单的 --plan / --run，带 --max-samples 9（--run 另指定新 --runs-root） | 两者退出 2、stderr 为空，error 明确 10 超过 9，没有创建输出根 | 预览 / 实际执行入口均在启动前拒绝，没有模型调用 |

测试先失败后实现的证据、两次完整回归、最终定向日志和 CLI JSON 分别新建保存在忽略目录。首次环境失败保留，没有覆盖原记录、原始模型证据或旧结果。交付核对通过：64 份公开 Markdown / 439 个相对文件链接、12 份预期改动、367 份受保护旧文件摘要、HEAD / 忽略规则和空白；git diff --check 通过，仅有 LF / CRLF 转换提示，runs / private-notes 无跟踪。

## 风险与后续

本批功能和本地验收完成，尚未提交 / 推送或进行新云端验收。默认无上限，调用方需要在每次实际 --run 明确传参；只做带上限的预览不能保护随后不带参数的运行。静态数量合格也不能证明 provider / 凭据 / 宿主可用、工作区创建或任务答案成功。

双配置 / 重复真实比较仍待第二套配置、重复次数和实际任务预算；不自动执行十用例或 60 任务示例。token / 步骤 / 费用预算、并发、续跑和其他渠道仍不在本批。

## 文档同步

同步 README、CHANGELOG、进度、架构、实验说明、M3 / M6 方案。保留全部历史修改记录，不增加公开原始日志或私人资料链接。040 已提交的当前状态修正在本记录与进度中说明，没有改写 040 当时的验证结果。
