# 修改记录 088 种子执行顺序与重复结果分布

日期：2026 年 11 月 1 日，Asia/Shanghai。类型：功能 / 测试 / 文档。插件版本：`0.1.2`。已核实起始 HEAD：`03a301e`；本批尚未提交。

## 问题与目标

此前实验只按重复 / 用例 / 配置的固定顺序运行，报告虽有汇总和逐样本证据，仍缺少按用例直接观察重复结果变化的视图。增加显式种子的可复现排序，以及保持缺失和复核条件的描述性分布；不将随机顺序等同于独立样本或可靠性提升。

## 文件修改

| 文件 | 修改前 | 修改后 | 原因 |
| --- | --- | --- | --- |
| dsh_eval/formats.py、experiment.py | 固定矩阵展开 | 可选 randomSeed、稳定 sampleId、seeded-sha256-v1 排序与元数据校验 | 同一计划 / 种子可重建顺序，默认行为和指纹保留 |
| dsh_eval/report.py、experiment_resume.py | 固定位置核对 | 共用顺序 / 身份重建；报告增加执行设计与分来源重复分布 | 续跑、复验与随机计划保持一致 |
| dsh_eval/regression.py | 两侧无执行顺序元信息 | 披露 executionOrder，配对键保持不变 | 允许比较不同顺序时仍可核对设计差异 |
| dsh_eval/web/app.js | 汇总与逐次结果 | 执行顺序和分布面板、完整整数种子、缺字段兼容 | 按用例直接查看每轮及不可用覆盖 |
| test/test_randomization.py、test/browser.test.js | 无种子 / 分布回归 | 十项 Python、两项前端测试 | 冻结计划、真实合成执行、连续续跑、源完整性和显示边界 |
| README、实验 / 报告 / 浏览 / 基线说明、架构、M6 计划、进度、CHANGELOG | 原固定顺序约定 | 补齐新协议、字段、默认兼容与限制 | 运行方式与实现一致 |

## 实现与技术取舍

randomSeed 是清单顶层可选的非负安全整数，0 有效；拒绝 bool、null、负数、小数、字符串和超范围值。省略时不补字段，_plan_input 的默认载荷和指纹保持原值。填写时 plan / result 的 order 为 seeded-sha256-v1，并保存同一 randomSeed；完整清单和顺序规则进入原计划指纹，改种子不能沿用旧 expected 摘要。

先按原固定规则生成 sampleId / caseEntryId / configurationId / repeatIndex，再对 `[规则, 种子, 用例条目, 配置, 重复编号]` 的紧凑 UTF-8 JSON 做 SHA-256 字节升序排序，以 sampleId 破同分。使用固定哈希排序而非依赖全局 RNG 或 Python hash 状态；规则版本明确记录，金样序列锁定种子 0 / 42。不同种子可能产生相同排列，不承诺所有排列等概率或控制模型采样。

执行仍串行，配置或轮次可以交错；sampleId 不变，列表位置表示调度顺序。报告先确认矩阵长度，再重建保存的顺序和身份；新增规则需要完整排序列表，没有总内存硬限额。首轮和连续续跑复用同一冻结矩阵，只安排明确未开始项，不重新随机化。旧默认顺序 / 指纹不迁移，新字段或顺序需要新版读取器。

repeatDistributions 按用例 / 配置 / 复验来源分组，各轮按 repeatIndex 显示；outcomes 保留 passed / failed / unevaluable / missing，statusCounts 保留 skipped 等状态。有效通过 / 失败要求 verified、matched、completed、complete 且可评测；其余计入排除，不能补成普通失败。多个来源行共享原计划轮次分母，不能相加；历史复用和新增项在完整原计划中只计一次。报告版本不变，新增字段由 JSON、Markdown 和浏览器展示，旧报告不补算。

基线比较仍按用例 / 重复编号对齐，每侧顺序分别核验；两个独立实验可以使用不同种子，新的 executionOrder 元信息明确披露差异，不引入统计因果结论。

## 验证

2026 年 11 月 1 日，本地 Windows；新增执行均为合成适配器、真实子进程与原录制器，无模型调用。

| 命令或操作 | 结果 | 范围 |
| --- | --- | --- |
| 首轮 `python -m unittest discover -s test -p test_randomization.py` | 10 项通过 / 10.477 秒 | 种子校验、旧指纹、跨进程、执行 / 报告、两轮续跑、基线比较与分布 |
| 补金样序列与随机 sampleId 篡改反例后，同一入口 | 10 项通过 / 11.408 秒 | 种子 0 / 42 的固定序列；样本 ID、种子、规则、顺序篡改拒绝；同一种子不受 PYTHONHASHSEED 影响 |
| `python -m unittest discover -s test -p test_experiment.py` | 原 9 项通过 / 3.872 秒 | 原执行、冻结、错误与默认顺序兼容 |
| `node --test --test-isolation=none test/browser.test.js` | 28 项通过 / 72.146 毫秒 | 新增两项分布及完整整数种子 / 旧报告兼容 |
| 首轮获准环境 `npm.cmd test` | 113 项通过 / 7.151 秒 | 完整 Node 无模型回归 |
| 补随机规则缺种子反例，`node --test --test-isolation=none --test-name-pattern="execution seeds" test/browser.test.js` | 修复前 1 项失败：缺字段被显示为固定顺序 | 应区分随机报告缺种子和明确固定顺序 |
| 修复后获准环境 `npm.cmd test` | 113 项全部通过 / 7.133 秒 | 仅固定规则缺种子显示未设置；随机 / 未知规则缺种子显示缺失 |
| 获准环境 `npm.cmd run test:python` | 433 项全部通过 / 274.046 秒 | 完整 Python 无模型回归，含默认 / 随机实验、连续续跑、报告、基线比较、浏览与真实子进程清理 |
| `npm.cmd run check`、`python -m compileall -q dsh_eval scripts test`、`git diff --check` | 43 个 JS 文件、Python 编译与补丁检查通过 | 语法与补丁格式 |
| 实际浏览器合成报告检查 | 种子 0、两配置 / 三轮的通过、失败及缺证据分布显示正确；预览页与本次服务已关闭 | 由公开 retry-read 夹具的合成实验生成 fresh 报告，临时副本中另存错误答案录制并移除一项证据；不是模型运行 |
| Markdown 相对路径、标题锚点、忽略目标及种子声明示例 | 10 份文档、522 个本地链接 / 118 个目标通过；randomSeed 示例合并到既有清单后通过 validate_experiment | 公开文档与字段约定一致，无模型执行 |
| fixtures / src / scripts 差异、运行资料跟踪及补丁检查 | 原固定用例、录制器和宿主脚本无差异；runs / private-notes 无跟踪文件；git diff --check 通过 | 没有改写历史用例或引入原始运行资料 |

连续续跑按 2 / 2 / 4 完成八项原随机计划，最后版本 3 报告的样本列表与预览相同，各来源文件摘要保持；执行身份没有重复。分布测试另外改变合成样例的保存来源声明验证分桶，不将该声明当作真实模型验收。

本轮全量回归与文档检查全部通过；没有新增模型调用或云端 CI。

## 风险与后续

这里只新增可复现调度与描述性结果分布，尚无置信区间、显著性、停止规则的统计校正或模型采样种子。固定 / 随机顺序的少量观测均不能支持总体模型优胜、成本或稳定性改善；读取仍要求稳定归档。现有固定评测集和历史真实样本没有自动加入种子；本轮无新模型、提交 / 推送或 CI。

## 文档同步

同步 README、docs/experiments.md、docs/configuration-reports.md、docs/result-browser.md、docs/baseline-regression.md、docs/architecture.md、docs/plans/m6-reliability-validation.md、docs/progress.md 和 CHANGELOG；旧固定顺序历史与已有验证保留。
