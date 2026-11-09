# 修改记录 127 实验级结构化原因汇总

日期：2026 年 11 月 9 日，Asia/Shanghai。类型：功能、测试、文档。插件版本：0.1.2。相关 Git 提交：尚未提交；起始 HEAD 为已核实的 `4a1c261`。

## 问题与目标

批次 B 已能展示单个任务的评分原因和依赖，但实验报告尚不能统计独立问题、后继阻断及全局门禁。原 diagnosticSummary 只描述 role=diagnostic 的单项结果，不能代表两个角色的结构化原因。

本批将已有单样本诊断汇总到 JSON、Markdown 和报告页面，按原因定位样本，继续沿原 evaluationPath 查看证据链。一个源头和三个后继分别统计；必需 / 诊断角色、来源与缺失覆盖清楚区分。使用历史真实归档做离线验收，不新增模型调用。

## 文件修改

| 文件 | 修改前 | 修改后 | 原因 |
| --- | --- | --- | --- |
| dsh_eval/diagnostics.py | 仅统计诊断角色四类结果 | 新增 assertion_causes、assertion_cause_summary，保留原两个函数 | 原因分类与诊断角色统计使用独立字段和分母 |
| dsh_eval/report.py | 保存新评测但不汇总结构化原因 | 核心复验后派生逐样本原因，沿现有分组 / 来源 / 续跑汇总，并输出 Markdown | 复用原报告链路，不增加执行器或改变判分 |
| dsh_eval/web/app.js | 报告页只能逐样本查看原因 | 原因覆盖、角色 / 来源分组、原因与样本本地筛选及安全跳转 | 从实验总体问题定位具体任务 |
| dsh_eval/workflow_demo.py、test/test_workflow_demo.py | 未核对实验原因摘要 | 核对四样本覆盖和唯一诊断格式源头 | 原无模型 CI 演示入口同时验证新汇总 |
| test/test_assertion_cause_summary.py | 无原因聚合回归 | 12 项分类、去重、角色 / 缺失及畸形输入回归 | 明确零问题与不可用，防止把后继当独立源头 |
| test/test_assertion_cause_reports.py | 无报告集成覆盖 | 5 项普通 / 续跑、门禁、缺证、链接与源摘要回归 | 复用实际子进程录制和独立评分 |
| test/browser.test.js | 无实验原因面板覆盖 | 新增 6 项前端回归 | 来源、角色、筛选、跳转、旧格式及不完整明细 |

## 实现与技术取舍

从本次 fresh evaluate 的 assertionDiagnostics 版本 1 读取分支原因，核对原断言唯一 ID、类型、角色、结论、冻结 after、直接前置顺序和阻断传播。不支持、缺失或矛盾的元数据将整个样本原因标为 unavailable，不从 reason 文本猜测。报告不能取得 fresh 结果时单列 not_evaluated。原因派生在原核心复验后执行，不进入 changedFields 或任务聚合。

逐样本 assertionCauses 和汇总 assertionCauseSummary 都是独立版本 1 的可选扩展，报告主版本 1 / 2 / 3 不变。byRole 分开 required / diagnostic；rootIssues、blockedAssertions、globalGates 分开。原 diagnosticSummary 的内容和算法保持。

availableSamples 表示结构化原因可用，不是任务可评测数量；全局门禁原因已知的样本仍可在此分母中。declaredSamples 是原因可用子集中声明该角色的样本数。原因码在同一样本和角色内只计一次，并保留 rootIssueCount / blockedAssertionCount 的断言条数；一个源头与三个后继是 1 个独立问题、3 条阻断，影响到同一份样本。分类与角色可以重叠，不相加当作任务数。

分来源直接复用现有 groups[].bySource，不再添加平行分组或重建样本身份。报告匹配子集、历史复用与本轮新增沿原 _summary 各自统计。前端筛选只作用于当前保存报告，跳转仍使用原样本索引对应的已核对 evaluationPath，不发起模型或评分请求。Markdown 使用原转义和相对评测链接。

## 验证

环境为 Windows、Node.js v24.14.0、Python 3.12.0。新增回归输入为合成数据；历史真实轨迹是既有录制的离线复验，不是新增模型端到端任务。

| 命令或操作 | 结果 | 证明的范围 |
| --- | --- | --- |
| python -m unittest discover -s test -p test_assertion_cause_summary.py | 12 项通过 | 独立问题与阻断、原因样本去重、角色声明、全局门禁、旧 / 未知 / 畸形元数据 |
| python -m unittest discover -s test -p test_assertion_cause_reports.py | 5 项通过 / 5.809 秒 | 普通、版本 2 / 3 续跑、缺证与门禁、来源覆盖、原评分与源归档、Markdown 和浏览链接 |
| python -m unittest discover -s test -p test_diagnostic_reports.py | 3 项通过 / 2.031 秒 | 原诊断角色统计及续跑分区保持 |
| node --test --test-isolation=none test/browser.test.js | 59 项通过 | 新原因面板、角色 / 来源分母、本地筛选与已核对评测链接、旧报告和不完整明细 |
| npm.cmd test（允许真实子进程的环境） | 151 项通过 / 7.760 秒 | 完整 Node 回归，包含实际 Web 子进程退出 |
| npm.cmd run test:python（允许真实子进程的环境） | 583 项通过 / 414.878 秒 | 当前完整 Python 回归，包含原因聚合、三类报告及新工作流断言 |
| npm.cmd run check；python -m compileall -q dsh_eval scripts test | 45 个 JS 文件及 Python 编译通过 | 语法与编译 |
| npm.cmd run demo:workflow -- --generate-only | 退出 0，三场景与新报告原因检查通过，89 份源文件摘要保持 | 新 checkout 的合成工作流沿用原入口，无模型调用 |
| python -m dsh_eval --report ＜117 实验目录＞/experiment-result.json --reports-root ＜新目录＞ | 新进程退出 0，四份 verified / matched / live，四项任务仍 passed，changedFields 为空 | 既有真实归档的独立离线验收 |
| 实际浏览新报告 | 原因筛选唯一 sample-000002，进入单样本后定位 seq 46 / 第 47 行答案事件 | 原因 → 样本 → 原事件的实际页面路径 |

历史验收复用[117 四任务矩阵](2026-11-04-117-live-confirmation-matrix.md)。新原因覆盖 4 / 4、缺失 0；必需角色独立问题、阻断、全局门禁均为零。诊断角色仅 sample-000002 的 answer-exact 出现 final_text_mismatch，实际文本仍为 `**done**`，与原精确回复诊断失败一致。原诊断统计仍为三通过、一失败，任务通过且诊断失败样本仍为一份。

本次选定归档目录 137 份文件、既有报告 6 份文件在新进程复验前后摘要保持，输出写入新目录。补充类型边界复核未发现会修改原评分或令畸形可选字段抛出的剩余问题；明确允许非阻断项的空 blockedBy。完整 Python 和 Node 回归全部通过。浏览服务 Ctrl+C 后监听数量为零。九份变动文档共 589 个相对文件链接目标有效，git diff --check 通过；runs 与 private-notes 无跟踪文件。

## 风险与后续

原因与依赖描述评分条件，不证明模型意图。聚合覆盖和样本计数不是新通过率，不用于模型总体表现、性能或费用结论。来源与摘要不是签名。未知元数据缺失时仍可查看原报告与逐样本评测；需要新统计须显式重新生成报告。

本批尚未提交、推送或运行新云端 CI，旧提交的 CI 不作为本批结果。归档迁移打包、更多平台或更多模型重复保持按需独立安排，本批不增加这些功能。

## 文档同步

更新 README、CHANGELOG、进度、架构、评测格式、配置报告、结果浏览和工作流说明，明确原因分母、角色与历史复验边界。原历史验证结果保留，公开文档不链接真实运行产物或私人资料。
