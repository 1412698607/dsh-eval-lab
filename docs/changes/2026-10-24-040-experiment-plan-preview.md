# 修改记录 040 实验预检与计划预览

日期：2026 年 10 月 24 日，Asia/Shanghai。类型：功能 / 重构 / 测试 / 文档。插件版本：0.1.2。相关 Git 提交：本批尚未提交，开始时已核实 HEAD 为 `39347f23d68e287e5e9cb38826f15957ff280002`，工作区干净。M6.4 历史验收与 001 至 039 记录保留。

## 问题与目标

M6.4 收尾后增加无模型准备入口：实现 `--experiment … --plan` 的预检与计划预览，补齐测试并同步文档。原入口必须带 --run，虽然启动前会校验全部组合，却不能独立查看将执行多少任务及其安排。

新入口读取同一实验与用例，校验全部组合并输出任务矩阵；与 --run 共用加载 / 预检和样本展开逻辑。它不安装宿主、读取模型凭据或启动任务，不将预检通过表述为实际任务成功。

## 文件修改

| 文件 | 修改前 | 修改后 | 原因 |
| --- | --- | --- | --- |
| dsh_eval/experiment.py | 加载、全组合校验和展开嵌在实际执行函数中 | 提取共用加载 / 预检、无副作用展开，新增 plan_experiment | 预览与执行保持相同数量、顺序、请求配置和样本身份 |
| dsh_eval/__main__.py | --experiment 仅接受 --run | 新增互斥 --plan，stdout 计划 JSON / 独立错误格式，0 / 2 退出码 | 无执行动作即可检查清单 |
| test/test_experiment_plan.py | 无独立预览回归 | 新增 8 项无模型测试 | 覆盖规模、顺序、输入边界、无执行副作用和真实 CLI 编码 |
| test/test_experiment.py | 既有合成执行只核对自身结果 | 对照预览与实际合成运行的身份、请求配置、预算及展开录制覆盖 | 验证共用展开后既有执行链路仍一致 |
| README、CHANGELOG、progress、architecture、experiments、M3 / M6 方案、本记录 | 原运行方式及 M6.4 收尾状态 | 新入口、独立格式、验收与后续边界 | 使用方式与当前实现一致 |

## 实现与技术取舍

先加载并校验清单及全部用例，再以实验 configRef 完整替换原请求配置，检查每个组合的 headless / 当前插件版本。_expand_samples 只按重复 / 用例 / 配置的固定顺序生成计划身份和展开用例；--plan 将其转成 JSON，--run 才创建 UUID / 目录、冻结输入并交给原 batch。没有另写调度器或改变顺序、隔离、清理和原结果格式。

预览使用独立 experimentPlanFormatVersion=1，成功包含 valid=true、modelCalled=false、counts、配置声明、repetitions、failurePolicy、order 及逐样本矩阵。任务数量不是模型调用数量；未来执行的 modelCalls / totalTokens / cost 均为 null，不凭任务数或 timeoutSeconds 估算费用。没有运行 outcome / 状态或 experimentId、batchId、caseRunId、runId、sessionId。

recorderOverrides 原样保留用例声明：省略为 null，空对象为 {}，部分 / 完整值不补齐。有效默认值继续由 Node 配置模块解析，避免在 Python 中复制并维护另一份默认值；原用例、实验快照和后续配置传播语义不变。budget 只是原 timeoutSeconds 声明，不是总退出期限或费用硬上限。

--plan 只适用于实验，并拒绝实际执行、证据、输出目录 / 文件、宿主和浏览 / 报告控制参数，空字符串选项值也拒绝。stdout 沿用缩进 UTF-8 JSON；未增加文件输出模式或独立的人类摘要流。参数错误走既有 argparse stderr / 2，预检错误返回计划版本的 valid=false / error JSON / 2，不伪装成 unevaluable 的任务执行结果。

## 验证

本轮未运行真实模型 / Harness / Web，没有提交、推送或新云端 CI。原 039 的 202 Python / 85 Node 等云端结果是历史基线，不计作本批验证。

| 命令或操作 | 实际结果 | 证明的范围 |
| --- | --- | --- |
| `python -m unittest discover -s test -p test_experiment_plan.py -v`，实现前 | 当时 7 项中 1 failure / 12 errors，缺 plan 函数 / 参数 | 新入口原先不存在，实际 CLI 也返回未知参数；随后另增一项非法预算 / 录制输入回归 |
| 同一命令，实现后 | 获准环境 8 项通过，0.146 秒 | 10 × 2 × 3 = 60 任务顺序、只读 / 禁止调用运行边界、元信息、录制声明、全部配置 / 用例错误及 UTF-8 真实子进程 |
| `python -m unittest discover -s test -p 'test_experiment*.py' -v` | 获准环境 17 项通过，3.398 秒 | 新入口及既有实验回归；通过真实 Node 合成适配器对照预览与执行展开，未调用模型 |
| `npm.cmd run test:python` | 获准环境 210 项通过，50.215 秒，OK | 补齐空选项冲突后，当前完整 Python 回归；真实子进程 / junction / 回环服务仍按原方式执行 |
| `python -m compileall -q dsh_eval scripts test` | 退出码 0 | Python 编译检查；Python 3.12.0 / Node v24.14.0 |
| `python -m dsh_eval --experiment fixtures/evaluation/core/core.experiment.json --plan` | 真实 CLI 返回 valid=true、modelCalled=false，counts=10 / 1 / 10，三项估算均 null，stderr 为空 | 直接预览现有十用例清单，无宿主安装 / 任务调用 |

实现前失败、定向 / 完整测试、编译环境及 CLI JSON 另存新的忽略目录，不覆盖历史证据。本批没有改 JavaScript，不重复 Node 85 项 / JS 41 文件检查，也不将它们写作本轮新结果。收尾核对通过：63 份公开 Markdown / 432 个相对文件链接、12 份预期修改的范围与空白、354 份受保护旧代码 / 记录 / 原始证据摘要，以及 HEAD / 忽略规则一致；`git diff --check` 通过，仅有 LF / CRLF 转换提示，runs / private-notes 无跟踪。

## 风险与后续

预检验证输入结构和已声明的运行兼容条件，不探测凭据、provider / model、网络或宿主安装，也不保证运行时工作区创建和任务答案。源文件没有锁定；下一次 --run 重新读取 / 校验 / 冻结，预览与执行之间改动文件可能改变安排。计划 JSON 不是可直接执行的冻结清单。

完整矩阵在内存中展开并打印，未新增样本上限、token / 步骤 / 费用预算、并发或续跑。计划的成功不能替代真实配置配对证据；第二套配置、重复次数和真实任务预算仍待另定。当前新功能仅本地验证，未进入新提交的云端验收。

## 文档同步

同步 README、CHANGELOG、进度、架构、实验说明、M3 / M6 方案。保留全部历史记录，不新增公开原始日志或私人资料链接。
