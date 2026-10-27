# 修改记录 057 实验续跑报告的只读浏览

日期：2026 年 10 月 27 日，Asia/Shanghai。类型：功能 / 测试 / 文档。插件版本：`0.1.2`。相关 Git 提交：尚未提交；已核实起始提交为 `33e95e6`。

## 问题与目标

056 增加 comparisonReportFormatVersion=2 的跨批次报告，原浏览器只接受版本 1。用户无法从页面查看历史复用和本次新增的用量，也不能沿报告进入实际来源批次及两层续跑结果。

本批接入版本 2 保存报告，展示原矩阵分母、两个批次、逐样本执行归属和分开的历史 / 新增统计，关联可进入原实验、两层续跑及录制证据。浏览继续只读，普通版本 1 布局保持兼容。

## 文件修改

| 文件 | 修改前 | 修改后 | 原因 |
| --- | --- | --- | --- |
| dsh_eval/browser.py | 报告只接受版本 1，续跑结果不受支持 | 接受报告 1 / 2 及两种续跑结果版本 1，新增显式来源链接 | 沿已有目录边界读取续跑证据 |
| dsh_eval/web/app.js | 单批次报告布局 | 增加来源 / 归属 / 分区摘要及用量表，样本可打开来源批次 | 明示历史和新增的统计含义 |
| test/test_browser.py | 原浏览边界检查 | 新增四项格式、只读、HTTP 和关联路径回归 | 验证兼容、无写入及范围拒绝 |
| test/browser.test.js | 两项前端回归 | 新增三项版本 2 展示、缺失 / 文本安全及版本 1 布局检查 | 在原页面逻辑上核对展示和请求 |
| test/test_experiment_resume_report.py | 报告生成 / 复验检查 | 增加实际生成八样本报告后的递归浏览回归 | 核对两个批次、八份轨迹和文件摘要不变 |
| README、进度、架构、报告 / 续跑 / 浏览说明、M6 方案、CHANGELOG | 版本 2 浏览未覆盖 | 同步当前入口、只读含义及验证限制 | 保留 056 历史快照，说明当前能力 |

## 实现与技术取舍

目录列表仍收录已有四类结果文件名，版本 2 报告进入原配置报告类别。experiment-resume-result.json 和批次 resume-result.json 作为关联文档读取，不增加列表类别。新增路径键覆盖 sourceResumeResult、sourceBatchResult、batchResumeResultPath 和 resumeVerification.batchResumeResult，并复用原有文本范围预检、真实路径复核和禁用目录规则；缺失 / 越界链接显示不可用。

页面从保存的 batchIds 和 resumeId 显示绑定，从 executionOrigin 与 sourceBatchId 显示逐样本归属；reusedSummary / newlyExecutedSummary 分别显示计划、尝试、跳过、来源、通过比例分子 / 分母和指标累计 / 缺失覆盖。完整计划的汇总明确含历史复用，groups.byExecutionOrigin 提供组内两类数量。缺失数值继续显示缺失，来源声明和执行归属分别呈现。所有内容使用文本节点，JSON 里的 HTML 标签不执行。

展示直接使用已保存的报告统计和路径，沿用已有表格与关联读取；服务和前端均不调用 evaluate、inspect、runner 或模型。浏览响应仍是 browserFormatVersion=1，没有新增持久化格式或运行命令。报告生成与主动复验继续使用 056 的 --report。

## 验证

环境：Windows、Node.js `v24.14.0`、Python `3.12.0`。全部样本为 synthetic，确定性适配器启动真实子进程，无 Harness / 模型请求。

| 命令或操作 | 结果 | 证明的范围 |
| --- | --- | --- |
| `python -m unittest discover -s test -p test_browser.py` | 21 项 / 3.804 秒，OK | 格式 1 / 2、HTTP 只读及新增关联边界 |
| `node --test --test-isolation=none test/browser.test.js` | 5 项通过，无失败 / 跳过 | 版本 2 分区、缺失与文本安全、版本 1 布局 |
| PYTHONPATH=test，运行 ExperimentResumeReportTests.test_generated_continuation_report_browses_both_batches_and_traces_without_writes | 1 项 / 3.714 秒，OK | 实际报告可遍历原实验、两层续跑、两个批次和八份轨迹；摘要不变 |
| `npm.cmd run check` | 43 个 JavaScript 文件通过 | JavaScript 语法 |
| `npm.cmd test`，沙箱首次 | 90 项中 88 通过、2 失败 | 两项真实 Web 启动 / 清理回归出现 spawn EPERM，此次不计完整通过 |
| `npm.cmd test`，允许真实子进程的环境 | 90 项全部通过，无失败 / 跳过 | 原生启动和清理实际执行，前端与原 Node 回归兼容 |
| `npm.cmd run test:python`，沙箱首次 | 299 项 / 145.839 秒，5 errors | 四项进程树回收失败；Web 生命周期类初始化出现 spawn EPERM，未执行该类测试，不计完整通过 |
| `npm.cmd run test:python`，允许真实子进程的环境 | 完整 318 项 / 146.090 秒，OK、无跳过 | 报告、浏览、续跑执行、进程树清理及生命周期回归兼容 |
| `python -m compileall -q dsh_eval scripts test` | 退出 0 | Python 语法 |
| 实际本机浏览器页面检查 | 通过；147 份文件前后 SHA-256 相同 | 八样本报告显示历史 2 / 新增 6；原 / 新批次跳转及新增样本评测 → 九行合成轨迹可打开 |

新增五项 Python、三项前端回归。报告未知版本、布尔 / 浮点版本拒绝；新增链接的外部绝对路径、UNC、禁用目录在 resolve 前拒绝，缺失文件保留不可用标记；HTTP POST 返回 405。实际页面核对分区表格、来源声明、缺失 token / 费用和证据跳转，临时服务已停止。

## 风险与后续

页面展示保存时结论，来源和 verified 不是签名或任务通过保证；读取不会修复失效绝对路径、刷新证据或认证被协调改写的文件。原有稳定目录、容量、分页及本机访问边界保持不变。版本 1 报告及浏览响应版本不变。

本批不增加模型样本，真实模型续跑验收、连续续跑及跨实验合并仍未覆盖。改动尚未提交 / 推送或运行新云端 CI，本地测试不能替代提交级云端验收。

## 文档同步

已更新 README、docs/progress.md、docs/architecture.md、docs/configuration-reports.md、docs/experiment-resume.md、docs/result-browser.md、docs/plans/m6-reliability-validation.md 和 CHANGELOG。055 / 056 历史修改记录保持原样；当前进度说明浏览能力已由 057 接入。当前工作区十三份修改 / 新增 Markdown 的 375 个本地链接均存在且未被忽略；git diff --check 通过，runs / private-notes / secrets 没有已跟踪文件，页面截图保留在被忽略的 runs 目录。
