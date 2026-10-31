# 修改记录 056 实验续跑的跨批次报告

日期：2026 年 10 月 27 日，Asia/Shanghai。类型：功能 / 重构 / 测试 / 文档。插件版本：`0.1.2`。相关 Git 提交：尚未提交；Git 起始提交为 `33e95e6`，本批在 055 的本地执行实现之上增加独立报告。

## 问题与目标

055 已能只执行中断实验的明确未开始项，但原 --report 只接受单个终态实验与一个批次，不能将历史复用项与新批次按原用例、配置、轮次重新对应。把新任务数量当作原计划规模或直接相加保存摘要，会遗漏原分母、混淆历史与新增用量，也不能重新检查两侧证据。

本批让 --report 读取一个终态 experiment-resume-result.json，核对显式来源和两个批次后，逐项复验并生成独立 JSON / Markdown。普通实验仍输出报告版本 1，续跑报告使用版本 2，明确多个批次和历史 / 新增归属。原实验、续跑结果及证据不修改。

## 文件修改

| 文件 | 修改前 | 修改后 | 原因 |
| --- | --- | --- | --- |
| dsh_eval/experiment_resume.py | 静态输入核对与执行预检在同一函数 | 提取 _load_inputs，仍由执行预检做 fresh 证据分类 | 报告复用同一矩阵 / 冻结输入校验，不触发执行或领取 |
| dsh_eval/resume_report.py | 无跨批次报告加载器 | 新增显式关联、两层摘要、领取、原 / 新批次输入与身份核对 | 为共用报告器提供每项的实际批次和证据根 |
| dsh_eval/report.py | 只复验普通实验的单个批次 | 分派续跑输入，复用 _recheck / 配对 / 统计 / 输出；增加版本 2 来源和分开用量 | 保留原分母、来源隔离及当前证据判定 |
| dsh_eval/__main__.py | --report 帮助只说明普通实验 | 明示普通实验或实验续跑终态输入 | CLI / API 入口保持一致 |
| test/test_experiment_resume_report.py | 无跨批次报告测试 | 十六项合成正反例、真实 CLI 与录制检查 | 验证完整矩阵、证据异常、配对及兼容边界 |
| README、进度、架构、报告 / 实验 / 续跑 / 浏览说明、M6 方案、CHANGELOG | 报告整合待实现 | 同步版本 2 格式、读取方式、证据范围和浏览器限制 | 保留各批历史，说明当前能力 |

## 实现与技术取舍

报告入口识别 experimentResumeResultFormatVersion，要求实验续跑、下层批次续跑及新批次均有终态与 finishedAt，核对身份 / 目录、状态、源实验和批次绑定。读取保存的两层 resume-plan.json，重算其摘要并比较预留下游路径与源领取记录；原实验可以保留中断时的 running，不能据此重新执行。

复用 _load_inputs 检查原 plan-input、冻结用例、展开、完整矩阵与源批次关联。原实验 / 冻结输入 / 源元信息的选定字节摘要必须与保存计划一致；新批次核对 remaining.batch.json、两层输入快照、顺序及输入指纹。样本数量检查先于完整位置枚举。全矩阵的 caseRunId / runId / sessionId 不允许重复；新批次只能对应原 pending 的 sampleId，历史复用项对应原来源。非法路径、计数、身份、轮次、版本或非终态在 inspect / 新输出之前拒绝。

报告不调用执行预检来重新领取或阻断已领取的源。保存摘要中的历史录制 / evidence / runtime 文件按逐样本当前证据处理，不因文件字节变化就删除整个原计划。两侧都进入原 _recheck / evaluate / Node inspect；坏录制保留 invalid / unverified，丢失证据为 rejected 或 unavailable，原分母保留，配置 unknown / mismatched 或来源不同不能进入同一配对。原 checkpoint 落后时，只有受控 caseDirectory 的固定证据位置用于重建读取关联，仍需本次复验。

直接复用原配对与统计，避免第二套计算口径。原 sampleId / caseEntryId / configurationId / repeatIndex 保持，允许同一原轮次的一对跨 reused / new，但必须同用例、同来源且两侧 verified / matched。live / synthetic 仍只是证据声明，不是签名；执行归属 reused / new 与证据来源分别统计。

续跑报告 comparisonReportFormatVersion=2，batchId=null，batchIds 保存原 / 新批次，sourceResumeResult / resumeId 与 sourceExperimentResult 明确两个执行阶段的关联；逐样本增加 executionOrigin、sourceBatchId 和 sourceBatchResult。reusedSummary / newlyExecutedSummary 与 groups.byExecutionOrigin 都从新复验结果计算，前者不能计成本次新增消耗；savedSummary 只保留保存的 combinedSummary。samplePlan 继续只是启动分类，不冒充终态样本。Markdown 显示两类分母、指标累计值 / 均值 / 范围 / 缺失覆盖和逐项来源。

选择新报告版本而非放宽原版本的单批次语义，原普通实验 API、输出版本及配对行为保持兼容。当前浏览器只识别版本 1 报告，因此新报告先直接查看 JSON / Markdown，浏览器接入不在本批范围内。

## 验证

全部使用合成适配器、真实 Python / Node 子进程、状态化环境、录制器与 Node inspect，没有真实模型调用。正常样本来源统一为 synthetic；来源隔离反例故意构造一个 live 声明，属于合成负例，不是实际模型样本。

| 命令或操作 | 结果 | 证明的范围 |
| --- | --- | --- |
| 实现前：PYTHONPATH=test 下运行新增的八样本报告测试 | 1 项 / 2.483 秒，1 error | 原入口拒绝续跑结果格式，尚无跨批次报告 |
| `python -m unittest discover -s test -p test_experiment_resume_report.py`，首批 | 12 项 / 30.508 秒，OK | 八样本整合、原证据不改写、异常关联、错误 / 跳过和真实 CLI |
| 同一命令，补充配对 / 路由 / 来源反例后 | 16 项 / 43.241 秒，OK | 跨执行边界配对、实际路由不符、来源隔离、原来源文件移除 |
| `npm.cmd run test:python`，可创建 / 回收真实子进程的环境 | 完整 312 项 / 140.532 秒，OK、无跳过 | 新报告、原普通报告、055 执行、批次续跑、浏览与生命周期兼容 |
| `python -m compileall -q dsh_eval scripts test` | 退出 0 | Python 语法检查 |

关键结果：

- 八项原矩阵重新复验 verified / matched / synthetic，历史二项 / 新增六项，四个用例 / 配置分组、每用例两对比较。历史与新增的调用、工具、耗时累计值之和与全部样本一致；费用保持缺失。原实验和续跑目录文件摘要均不变，未重新执行任务。
- 第一项完成后中断，再执行七项，原同一轮次的一对可跨历史 / 新增配对，仍保留全部四对。原始输入来源文件删除后，冻结计划和证据仍可报告。
- 原 / 新批次任一录制损坏只排除对应一对，八项计划 / 尝试分母保留；历史证据删除保留一 rejected / 七 verified。实际 request/header 路由不符排除一对；构造的来源冲突产生独立 live / synthetic 条目，不混配。
- 历史二项 failed、新二项全部 passed 时，重新复验仍保留两个 failed。新 runner 错误保留一 error / 五 skipped、六 unknown 来源；skipped 伪造 source 会在 inspect 前拒绝。
- 重复执行身份、错误 / 布尔轮次、冻结输入或计划快照变化、越界 / 外来下游路径、领取不符、running / 未知版本及 10^100 重复元信息均在 inspect / 输出前拒绝。
- 真实 Python CLI --report 返回 0、版本 2 JSON、stderr 为空，源文件摘要保持不变。

JavaScript 未修改，本批不重复 Node / JS 全套检查，也不继承历史数量作为新验证。055 的受限环境失败及后续通过保留在原记录，本批完整回归直接使用可运行实际子进程的环境。没有提交 / 推送或新云端 CI。

## 风险与后续

本批只整合一个实验续跑及其原 / 新批次，不接受纯批次结果或任意跨实验拼接，不自动跟随再次续跑。来源使用保存的显式绝对路径，续跑整组搬迁不支持；普通版本 1 实验的整体搬迁能力保持原范围。原实验 summary / samples / groups 不回填。

报告须读取停止写入后的稳定目录，不持有在线多文件一致快照。绑定和 SHA-256 不是签名，无法认证全部文件和摘要被协调改写后的来源。报告成功、结构复核、录制完整与任务通过分别判断；合成比较不能推断真实模型总体表现或费用。

后续可以接入浏览器版本 2 展示，并另定真实模型续跑验收的配置与任务数。当前不增加模型、并发调度、未知任务自动重试或统计推断。

## 文档同步

更新 README、docs/progress.md、docs/architecture.md、docs/configuration-reports.md、docs/experiment-resume.md、docs/experiments.md、docs/batch-resume.md、docs/result-browser.md、docs/plans/m6-reliability-validation.md 与 CHANGELOG；055 历史记录保持原样。当前十二份修改 / 新增 Markdown 的 366 个本地链接均存在且指向可提交文件或目录，git diff --check 通过。runs / private-notes / secrets 没有已跟踪文件。
