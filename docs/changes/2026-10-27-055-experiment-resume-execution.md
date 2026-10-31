# 修改记录 055 实验级安全续跑执行

日期：2026 年 10 月 27 日，Asia/Shanghai。类型：功能 / 重构 / 测试 / 文档。插件版本：`0.1.2`。相关 Git 提交：尚未提交；起始提交为已核实的 `33e95e6`。

## 问题与目标

054 已能将中断实验的批次条目对应到用例、配置和重复轮次，但只提供预检，不能显式执行剩余任务。直接在实验预检返回后调用公共批次续跑接口，会分成两次加锁，不能在同一源锁内同时完成实验输入复核与领取。

本批增加 --resume-experiment --run：重新复核实验摘要后，在同一源批次锁下共用既有批次续跑核心，只执行明确未开始项。新结果保存原矩阵映射、下游显式结果路径与本次新增摘要，原实验结果和原始证据不覆盖。跨批次配置报告不在本批实现范围内。

## 文件修改

| 文件 | 修改前 | 修改后 | 原因 |
| --- | --- | --- | --- |
| dsh_eval/experiment_resume.py | 只读预检 | 提取同锁复核函数，增加 resume_experiment 与独立版本 1 结果 | 保留实验级摘要约束及矩阵身份 |
| dsh_eval/resume.py | 批次入口内直接执行 | 提取要求调用方持有源锁的私有执行核心，可接受内部预留续跑 UUID | 两个入口共用领取与调度，不重复实现执行逻辑 |
| dsh_eval/__main__.py | 拒绝实验续跑 --run | 参数校验、预检 / 执行分派和分别版本化的错误结果 | 提供显式执行且保持 0 / 1 / 2 退出约定 |
| test/test_experiment_resume.py | 十四项预检检查 | 新增十一项执行回归，并扩展原终态 / 停止策略 / 锁检查 | 验证实际合成子进程链路与启动前拒绝 |
| README、进度、架构、续跑 / 实验说明、M6 方案、CHANGELOG | 仅记录实验级预检 | 同步执行入口、结果格式及未实现范围 | 使用方式与代码保持一致 |

## 实现与技术取舍

执行要求 64 位十六进制 expected_plan_sha256，接受大写并规范化比较。取得源批次锁后重新读取实验绑定、原 plan-input / 指纹、全部冻结 / 展开输入、来源与证据分类，比较实验摘要；阻断、上限不符或字节变化均先于 UUID、目录和领取拒绝。不能用下层 batchPlanFingerprint 替代实验摘要。原 --plan 仍无输出副作用，executionSupported 改为 true，eligibleForResume 仍需执行时重新检查。

为避免释放实验复核锁后再次调用公共 resume_batch，提取其原有执行段为私有 _execute_resume。调用方继续持有源锁；排他领取文件、剩余输入冻结、run_batch、正常失败 / 中断 / 清理规则及批次级摘要计算均沿用原实现。两个入口共用 `.batch-resume-claim.json`，任一入口领取后，另一入口也不能重复执行同一源。

实验层在新目录保存 resume-plan.json 与 running 的 experiment-resume-result.json，并预留下层批次续跑 UUID / 相对结果路径，再进入批次核心。samplePlan 保留全部原样本的 sampleId / caseEntryId / configurationId / repeatIndex 和启动分类，新批次沿用 sampleId 作为 entryId，新执行仍分配独立 caseRunId / 会话。预留路径不是下游执行完成事实；领取后中断时保持记录，不自动清除或再次启动。

新增 experimentResumeResultFormatVersion=1，保存来源、两层摘要、上限、计划计数 / 映射、下游结果路径、UTC 起止时间、调度 / 总体结论和 newlyExecutedSummary。samplePlan 中的 pending 只是启动分类，counts.newSamples 是拟执行数；最终新项状态从下游结果读取。新增摘要只统计新批次，历史 failed 仍影响总体结论。终态使用同目录临时文件 replace，不改写原实验 samples / summary / groups，也不将新结果冒充可输入 --report 的终态实验。

053 / 054 已存在于起始提交 33e95e6；本批在当前进度中修正“尚未提交”的旧状态，054 历史记录及其验证结果保持原样。本轮没有核对该提交的新云端 CI。

## 验证

以下均为无模型验证。测试冻结 synthetic 配置，替换准备入口及适配器，实际使用 Python / Node 子进程、状态化工具环境、录制器和 Node inspect。辅助数据在原路由检查之后统一保存 synthetic 的 evidence / evaluation / batch 来源，未开始、错误和跳过项保留未知。

| 命令或操作 | 结果 | 证明的范围 |
| --- | --- | --- |
| 实现前：在 PYTHONPATH=test 下运行两个新增定向用例 | 2 项 / 1.341 秒，2 errors | 缺少 resume_experiment API，真实 CLI 仍在参数解析阶段拒绝执行，无模型任务 |
| `python -m unittest discover -s test -p test_experiment_resume.py` | 25 项 / 28.436 秒，OK | 十四项原检查及十一项新回归；后续追加终态 / 锁断言由完整回归覆盖 |
| 首轮 `npm.cmd run test:python`，受限进程环境 | 实际 277 项 / 98.541 秒，5 errors，不计通过 | 四项自有进程树终止失败，一项生命周期 setUpClass 的 spawn EPERM，后者十九项未运行 |
| 同一 `npm.cmd run test:python`，可创建 / 回收真实子进程的环境 | 完整 296 项 / 102.148 秒，OK，无跳过 | 新实验执行、原批次续跑、普通实验、报告、浏览及生命周期兼容回归 |
| `python -m compileall -q dsh_eval scripts test` | 退出 0 | Python 语法检查 |

具体场景：

- 两用例 / 两配置 / 两轮，中断前完成二项：预检复用二项、执行六项；六个新 caseRunId 唯一且不与历史重叠，下游 entryId 顺序与原 sampleId 一致。八个合成来源计数保持一致，原选定文件字节摘要不变，源目录只新增领取文件。
- 执行中对源批次重新加锁被拒绝；实验入口先领取、批次入口先领取两种顺序均阻止另一入口重复执行。
- 缺失 / 非法 / 错误或下层摘要、上限改变 / 非法、源结果仅增加换行均先于身份和输出拒绝；真实 Python CLI 错摘要返回版本 1 JSON、退出 2、stderr 为空且无输出。
- 旧 checkpoint 中已有完整评测的项不重复执行；未知执行、损坏录制、原 stop 失败策略、已完成无剩余项及源锁占用阻断。
- 领取后、下层 run_batch 前模拟中断，实验与批次续跑结果均保持 running，显式下游路径可核对，重试被领取记录阻止。
- 单轮四项中历史二项 failed、新二项全部 passed 时总体仍 failed；新 runner 错误保留一 error / 五 skipped、来源全 unknown，原领取不释放。
- CLI --plan 与 --run 分派、结果版本、退出码及预检参数组合检查通过。

JavaScript 未修改，本批不重复运行 Node / JS 套件，不将 054 的历史数量当作本批新验证。没有真实模型调用、提交 / 推送或新云端验收。

## 风险与后续

本批只完成执行与关联。配置报告、跨批次逐样本重新核对及浏览器展示另行开发，experiment-resume-result.json 不能直接交给 --report。旧实验不补造绑定；目录搬迁、未知项自动重试、实验层连续续跑和模型会话恢复均未覆盖。

输出或进程中断可能留下 running / 部分新文件。预留但未领取时不表示已执行；领取后不自动回滚。同一源不再次放行，需沿显式路径检查下游结果。源锁是合作调度机制，不约束绕开协议的写入；摘要不是签名，临时文件替换不保证多文件事务、fsync 或断电恢复。

下一阶段为独立实验报告整合；真实模型续跑需另定配置与任务规模。合成任务和当前本地子进程回归不能当作真实模型验收。

## 文档同步

更新 README、docs/progress.md、docs/architecture.md、docs/experiment-resume.md、docs/experiments.md、docs/batch-resume.md、docs/plans/m6-reliability-validation.md 与 CHANGELOG。九份修改 / 新增 Markdown 的 342 个本地链接均存在且指向可提交文件或目录，git diff --check 通过。runs / private-notes / secrets 没有已跟踪文件；本记录未包含本机身份路径或私人资料链接。
