# 修改记录 059 显式连续续跑与跨轮报告

日期：2026 年 10 月 28 日，Asia/Shanghai。类型：功能 / 测试 / 文档。插件版本：`0.1.2`。相关 Git 提交：尚未提交；已核实起始提交为 `967ab431ac80dc316c1130be8f3826aa610be0ae`，包含 055–058，工作起始目录干净。

## 问题与目标

原实验第一次续跑后若再中断，只能沿批次结果单独检查，无法继续保留实验的完整用例 / 配置 / 轮次映射。续跑子批次的结果路径直到结束才填写，中途退出留下的 running 外层缺少可核对的下游身份；新批次锁也需要延长至外层汇总写入完成。

本批让已有实验续跑结果可再次 --plan / --run，逐批重新复核历史证据，只为最近批次明确未开始项创建新批次。报告与浏览保留原矩阵、全部批次 / 续跑来源和历史 / 本轮新增用量。未知执行、原 stop 失败、清理不明和重复领取仍阻断，不重复执行已完成项。

## 文件修改

| 文件 | 修改前 | 修改后 | 原因 |
| --- | --- | --- | --- |
| dsh_eval/resume.py | 子批次完成后才保存路径，子批次返回后释放自身锁 | 启动前保存预留 batchBinding，锁保持至批次续跑 / 外层最终写入 | 明确中途退出的下游身份，封闭收尾竞争窗口 |
| dsh_eval/experiment_resume.py | 只接受原实验结果 | 按输入分派连续续跑，首轮也延长新批次锁 | 保留原入口及首轮协议 |
| dsh_eval/experiment_resume_chain.py | 无跨轮预检 / 执行 | 迭代核对显式祖先链、逐批持锁复验及摘要校验，创建独立新结果 | 将执行限制在最新明确未开始项，并保留完整矩阵 |
| dsh_eval/resume_report.py | 只加载终态第一轮续跑 | 共用静态首轮输入加载；预检允许显式绑定的未收尾结果，报告分派连续链 | 共享原冻结输入 / 关联规则，保留最新报告的终态要求 |
| dsh_eval/report.py | 普通 / 首轮续跑报告版本 1 / 2 | 新增版本 3 来源链 Markdown，沿原逐项复验和配对路径报告 | 持续保留原分母，按本轮划分历史 / 新增 |
| dsh_eval/browser.py、web/app.js | 只识别报告 1 / 2 及续跑结果 1 | 识别报告 3 / 续跑结果 2，展示所有批次和续跑链并提供受限链接 | 让来源可核对，浏览继续只读 |
| dsh_eval/__main__.py | 帮助只说明原实验续跑 | 明示原实验或已有续跑结果 | 同一命令处理各轮 |
| test/test_experiment_resume_chain.py、test/test_browser.py、test/browser.test.js | 无连续链验收 | 新增十八项链路 Python、一项浏览 Python 和一项前端回归 | 覆盖真实合成执行、拒绝边界、锁与展示兼容 |
| README、进度、架构、续跑 / 报告 / 浏览说明、M6 方案、CHANGELOG | 连续续跑未覆盖 | 同步格式、操作和验证范围，修正 055–058 当前提交状态 | 保留历史快照，说明当前能力 |

## 实现与技术取舍

原实验输入继续使用预检 / 结果版本 1。输入为 experiment-resume-result.json 时，预检 / 新结果使用版本 2，计划摘要版本 2，报告使用 comparisonReportFormatVersion=3。首轮结果版本 1、普通报告版本 1、首轮报告版本 2 和浏览响应版本 1 均保留。参数与退出码不变，输入错误仍使用公共版本 1 JSON。

批次续跑在 run_batch 之前预留新批次 UUID 并保存 batchBinding，实际结果固定在 batches/<reservedBatchId>/batch-result.json；预留本身不是执行事实，批次和锁文件必须实际存在。通过原 ExitStack 延长新批次锁，独立批次入口保持到自身最终结果，实验入口保持到外层 checkpoint。旧终态续跑可沿已保存的 batchResultPath 加载；旧 running 续跑没有绑定时拒绝。

连续预检按 sourceResumeResult 向前读取显式祖先，不扫描目录，不重置旧领取。迭代加载最多 32 个续跑结果，拒绝循环、重复身份、未来版本和越界下游路径。按原批次到最新批次顺序取得全部内核锁，然后重新加载核对来源未变。每批复用原预检、当前执行环境校验和 fresh inspect / evaluate；历史项只能继续复用，只有最近批次中无执行事实的 pending / skipped 才能进入新批次。达到链长度上限后可报告，停止增加下一轮。

计划保留完整原矩阵 samples、各样本实际批次、全部 batchPlans、祖先结果 / 计划与批次元信息 / 冻结输入的 SHA-256，以及本轮 maxSamples。批次计划还覆盖其核对的运行证据摘要。版本 2 摘要覆盖这些来源、上限、输入和分类；执行在全部锁内重新复核比对，阻断或摘要变化先于身份、目录及领取。新结果只为最近源创建单次领取并复用原 _execute_resume / run_batch 核心，保存本轮 newlyExecutedSummary 和全矩阵 combinedSummary。历史 failed 不会被后续 passed 改写。

报告复用链的静态归档校验和原 _recheck / 统计 / 配对逻辑。祖先可能保留崩溃时的 running，最新选定结果和新批次仍须终态。元信息 / 冻结输入冲突整体拒绝；历史录制或证据变化按逐样本重新判断，保留原计划分母。版本 3 的 batchIds / batchResultPaths 按执行顺序列出所有批次，resumeChain 给出所有续跑结果；reusedSummary 是本轮之前的全部历史样本，newlyExecutedSummary 只含最新批次。仍按原 case / configuration / repeatIndex 与 live / synthetic 来源配对。

使用版本 3 明示多于两个批次及完整链，避免原版本 2 的“原批次 / 新批次”读者误解位置。执行继续复用既有批次核心和锁协议，代价是需要保留显式绝对归档路径，祖先轮数和检查量随链增加。没有引入另一套任务调度、数据库或自动重试规则。

## 验证

环境：Windows、Node.js `v24.14.0`、Python `3.12.0`。全部新增执行为 synthetic，使用真实 Python / Node 子进程、原录制器、状态化环境和 fresh inspect，无 Harness 安装或模型请求。

| 命令或操作 | 结果 | 证明的范围 |
| --- | --- | --- |
| 实现前，PYTHONPATH=test，运行新增完整矩阵预检用例 | 1 项 / 1.524 秒，1 error | 原入口拒绝已有续跑结果，尚无连续续跑 |
| `python -m unittest discover -s test -p test_experiment_resume_chain.py`，中间九项回归 | 9 项 / 31.365 秒，OK | 双轮执行、四批次报告、只读预检、锁 / 损坏 / 上限拒绝 |
| 同命令，扩展到十四项 | 14 项 / 55.039 秒，OK | running 外层绑定、checkpoint 恢复、收尾持锁及链校验 |
| 同命令，扩展到十八项首轮 | 18 项 / 60.470 秒，1 failure | 失败历史 / 新项结果正确，测试遗漏 outcomes.unevaluable=0；修正该断言后由完整回归覆盖 |
| `python -m unittest discover -s test -p test_browser.py` | 22 项 / 4.318 秒，OK | 报告 1 / 2 / 3、续跑结果 2、新链链接与原读取边界 |
| `node --test --test-isolation=none test/browser.test.js`，修正文本空格断言后 | 6 项通过，无失败 / 跳过 | 四批次与链展示、跳转、版本 1 / 2 兼容 |
| `python -m unittest discover -s test -p test_batch_resume.py` | 17 项 / 12.218 秒，OK | 原批次预检 / 执行和新增预留身份兼容 |
| `python -m unittest discover -s test -p test_experiment_resume_report.py` | 21 项 / 68.094 秒，OK | 首轮报告、原收尾锁与离线版本兼容 |
| `npm.cmd run test:python`，允许真实子进程创建 / 回收的环境 | 完整 341 项 / 212.606 秒，OK、无跳过 | 原有 322 项及十九项新增 Python 均通过 |
| `npm.cmd run check`、`npm.cmd test`，允许真实子进程的环境 | 43 个 JS 语法、91 Node 全通过，无失败 / 跳过 | 原前端、录制和生命周期兼容 |
| `python -m compileall -q dsh_eval scripts test` | 退出 0 | Python 语法 |
| 实际本机页面准备，较长测试输出根 | 最终 batch checkpoint replace 返回 WinError 5，未完成 | 没有宣称长路径兼容通过或修改产品路径逻辑 |
| 缩短测试输出根后重新生成并浏览 | 四批次 / 三轮，八项 synthetic；177 份文件前后摘要相同 | 全部来源、链链接、历史 6 / 新增 2 及最新批次样本正确，临时服务已停止 |

关键验收：八个原样本按 2 / 2 / 2 / 2 分到四个批次，仍保留两用例 / 两配置 / 两轮及四个有效配对；第三次续跑只执行最后两项。真实 CLI 预检和离线报告的 stdout 是 UTF-8 JSON、stderr 为空；CLI 执行入口在同进程确定性适配器下通过。未知执行、历史或最新坏录制、原 stop 失败、重复领取和摘要 / 上限变化均不启动新任务；循环、越界和未知版本在 inspect 前拒绝。新批次锁保持到最终外层写入；写入故障后解锁、结果仍为 running，已完成项可重新复核但不补写成功。历史两项失败、最终新增一项通过时，累计结果仍为 failed。

## 风险与后续

当前只允许同一原实验的显式祖先链，最多 32 个续跑结果。不是未知任务重试、模型会话恢复、任意跨实验合并或在线一致快照；仍需稳定归档、有效绝对路径及可读写内核锁。领取后的旧源不可重复启动，后续显式选择最近结果。版本 2 / 3 的旧读者应拒绝未知格式。

SHA-256 与来源声明不是签名，不能认证协调改写后的整个归档。原子 replace、锁和预留身份不等于 fsync、多文件事务或断电恢复保证。Windows 较长输出根曾出现 WinError 5，缩短测试根后通过，未提供全局长路径保证。

本批没有新增真实模型样本，真实模型连续续跑仍未验收；未提交 / 推送或触发新云端 CI。后续交付须独立核对最终提交的 CI，不用本地数量替代云端结果。

## 文档同步

更新 README、docs/progress.md、docs/architecture.md、docs/experiment-resume.md、docs/batch-resume.md、docs/configuration-reports.md、docs/result-browser.md、docs/plans/m6-reliability-validation.md 和 CHANGELOG。055–058 历史记录保持原样；进度按实际 Git 修正为已包含于 967ab43。十份修改 / 新增 Markdown 的 372 个本地链接均存在且未被忽略，git diff --check 通过；runs / private-notes / secrets 没有已跟踪文件，合成页面截图保留在忽略的 runs 目录。
