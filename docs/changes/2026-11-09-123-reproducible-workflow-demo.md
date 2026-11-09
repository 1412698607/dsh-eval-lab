# 修改记录 123 可重复的合成工作流演示

日期：2026 年 11 月 9 日，Asia/Shanghai。类型：功能、测试、配置、文档。插件版本：0.1.2。相关 Git 提交：尚未提交；起始实现为已核实的 `0504755`。

## 问题与目标

已有合成用例和实验断言预览需要手动拼接执行、改写来源及代入输出路径，实验预览尚不能在结果浏览器中打开。本批实现 [122 计划](../plans/reproducible-workflow-and-diagnostics.md)的批次 A：单命令生成独立归档，按固定顺序浏览完整步骤、漏步反例和四样本规则影响。结构化原因码和依赖影响仍为批次 B。

## 文件修改

| 文件 | 修改前 | 修改后 | 原因 |
| --- | --- | --- | --- |
| dsh_eval/runner.py、scripts/fixtures/mutation-adapter.js | 合成测试依赖替换适配器和事后改写来源 | 显式 run_synthetic_case，共用执行核心；预存固定场景和回复，创建 evidence 时声明 synthetic | 产品入口不依赖测试 mock 或 Harness 安装 |
| dsh_eval/batch.py、dsh_eval/experiment.py | 仅调用真实任务入口 | 内部完整回复映射选择合成入口；不声明合成续跑支持 | 复用冻结、清理、身份核对和汇总，避免合成任务转入 live 续跑 |
| dsh_eval/workflow_demo.py、package.json | 无一键工作流 | demo:workflow 生成、复验、发布索引并可启动前台只读服务 | 减少手工步骤，提供生成后退出模式 |
| dsh_eval/browser.py、dsh_eval/web/app.js | 不识别实验规则预览与工作流索引 | 新分类、顺序索引、转移汇总、变化断言、身份核对后的证据跳转 | 从结论定位规则与原始事件 |
| test/test_synthetic_runner.py、test/test_workflow_demo.py、两侧浏览测试 | 缺少公开合成执行链与预览浏览覆盖 | 实际子进程、文件错误、固定结果、干净依赖副本、二次运行、端口占用与范围 / 原文回归 | 验证新增分支及原调用契约 |
| .github/workflows/deterministic.yml | 仅生成原有 eval 示例 | 增加 demo:workflow -- --generate-only | 云端后续执行时核对固定演示结果 |

## 实现与技术取舍

预编排适配器只执行公开固定场景；Python 环境实际处理改名、读回、工具期限和最终文件状态，JavaScript 实际 recorder 写入并封存。普通 run_case 与合成入口共用监督、清理、快照及评分代码，合成入口跳过宿主安装和仅针对安装器的 Windows 路径长度检查。evidence / evaluation 版本和原断言聚合不变。

生成器预设两份独立任务及两用例各两轮的实验。样本 sample-000002 固定回复 `**done**`，其他三项固定 `done`。原确认词规则全部通过，候选规则只删除必需 answer 的确认词匹配方式，诊断项保留。所有结果由既有评分器计算；生成器核对预期结果，不制造评分结论。

普通实验和批次保持原调用契约。合成回复映射必须在输出前完整覆盖入口，且拒绝真实宿主控制参数。复核发现中止的合成批次若声明原续跑协议，后续会丢失脚本行为而调用真实入口；本批因此不为合成批次写 resumeSupportVersion，也不为合成实验写 batchBinding。真实任务的续跑行为不变。

独立任务复验、四样本报告和规则预览完成后，核对 inputs / tasks / experiments 的逐文件 SHA-256，再写索引。索引版本 workflowDemoFormatVersion=1 独立于原评测格式。浏览只读取保存数据，预览的源证据与事件入口核对目录范围及 caseRunId / runId / sessionId，原文通过文本节点呈现。合成评测中的 modelCalls 保留原事件计数，页面明确标为“合成模型事件”，不代表真实模型调用。

## 验证

环境为 Windows、Node.js v24.14.0、Python 3.12.0，命令在仓库根目录执行。本批没有模型调用或新增真实宿主组件验收。

| 命令或操作 | 结果 | 证明的范围 |
| --- | --- | --- |
| python -m unittest discover -s test -p test_synthetic_runner.py | 6 项通过 | 实际管道、recorder、inspect、评分、来源创建、缺少 Node 与输入 / 输出错误 |
| python -m unittest discover -s test -p test_workflow_demo.py | 8 项通过 / 21.896 秒 | 原始 JSONL 调用与返回、完整文件映射、唯一翻转、独立 CLI 预览、源摘要、新身份、仅公开运行目录副本无 host 安装、输出冲突、端口占用和拒绝合成续跑 |
| python -m unittest discover -s test -p test_browser.py | 43 项通过 / 6.409 秒 | 新分类、预览范围和身份约束、原浏览行为 |
| node --test --test-isolation=none test/browser.test.js | 42 项通过 | 转移 / 分母、字面原文、场景顺序、事件跳转和合成事件标签 |
| npm.cmd test（允许真实子进程的环境） | 134 项通过 / 7.076 秒 | 完整 Node 回归，包含 Web 实际子进程退出 |
| npm.cmd run test:python（允许真实子进程的环境） | 548 项通过 / 330.794 秒 | 当前完整 Python 回归，包含监督器、真实 Web 子进程与八项工作流集成 |
| npm.cmd run check；python -m compileall -q dsh_eval scripts test | 45 个 JavaScript 文件及 Python 编译通过 | 语法与导入编译 |
| npm.cmd run demo:eval | 两份原合成示例生成成功 | 原入口契约保持 |
| npm.cmd run demo:workflow -- --generate-only | 退出 0，三场景结果符合预设，89 份源文件摘要保持 | 完整生成、独立报告与规则预览，无模型调用 |
| npm.cmd run demo:workflow、实际页面操作及 Ctrl+C | 索引三个入口可打开；漏步成功重试定位 seq 5 / 第 6 行；唯一翻转原文定位 seq 12 / 第 13 行，答案事件高亮；Ctrl+C 后终止 npm 包装，监听数量为 0 | 真实浏览、定位、返回与前台服务停止 |

首轮工作流测试误从独立文件读取最终快照，随后改为核对实际 runtime.environmentSnapshot；最终八项通过。首轮完整 Node 在沙箱内 131 / 133 通过，两项既有 Web 子进程创建为 spawn EPERM；允许真实子进程后全量通过，后续新增来源标签回归后的最终数量为 134。

首轮沙箱 Python 全量执行 528 项，四项监督器测试无法通过 taskkill 结束进程，Web 生命周期进程组的 setUpClass 因 spawn EPERM 失败。测试自身对所持子进程执行 kill / wait 清理，未发现残留。随后在允许真实子进程的环境运行当前完整回归，548 项全部通过，首轮环境失败保留。

最终九份变动文档共 549 个相对文件链接均指向当前可提交文件；git diff --check 通过。runs 与 private-notes 保持忽略且无跟踪文件。

## 风险与后续

合成事件只能验证工程流程，不能作为真实模型可靠性、速度或成本证据。token 与费用保持缺失。哈希不提供签名、原子发布或断电持久性保证。合成归档暂不支持续跑；目录迁移仍沿用既有本地路径约定。本批未提交、推送或触发 / 核对新云端 CI，CI 配置的执行结果不能沿用基线结果。

批次 B 将在实际评分分支产生可兼容的原因与依赖元数据，当前仍未实现。

## 文档同步

更新 README、进度、架构、结果浏览说明、批次计划和 CHANGELOG，新增[工作流使用说明](../workflow-demo.md)。保留 122 计划形成时的历史范围；不修改历史验证记录，不提交 runs 或私人资料。
