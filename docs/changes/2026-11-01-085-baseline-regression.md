# 修改记录 085 基线回归比较

日期：2026 年 11 月 1 日，Asia/Shanghai。类型：功能 / 测试 / 文档。插件版本：`0.1.2`。起始 HEAD：`f4009f5`；本批尚未提交。

## 问题与目标

原 --report 只描述单个实验 / 显式续跑链中的配置表现，生成成功即返回 0，不能判断旧基线到新候选是否出现任务退化。新增独立入口，先确认任务、配置与证据可比，再列出逐项状态变化，并对缺项和不可比返回明确退出码。

## 文件修改

| 文件 | 修改前 | 修改后 | 原因 |
| --- | --- | --- | --- |
| dsh_eval/regression.py | 无跨实验门禁 | 选定配置、fresh 复验、并集配对、可比性及变化分类 | 已确认退化不被改善或缺项掩盖 |
| dsh_eval/report.py | 报告入口内加载普通 / 续跑输入 | 提取共用 _load_report_inputs；原报告生成流程保持 | 避免复制续跑关联核验或创建不需要的中间报告 |
| dsh_eval/__main__.py | 原评测 / 报告入口 | --compare-baseline / --candidate、配置选择、允许字段、0 / 1 / 2 与可选排他输出 | 可供脚本使用的明确协议 |
| test/test_regression.py、test/test_report.py | 原报告测试 | 17 项回归比较测试，报告夹具提取为无测试方法的共用 mixin | 复用真实合成适配器 / 录制及证据变体，保留原 17 项报告测试 |
| README、架构、配置报告、M6 计划、进度、CHANGELOG、新基线回归说明 | 无新入口说明 | 同步格式、退出码与比较边界 | 可复现使用方式 |

## 实现与技术取舍

每边接受一个终态普通实验或显式实验续跑结果，并选择一套 configurationId；单配置可省略，多配置必须明确。输入复用既有计划快照、矩阵、批次、续跑链校验；选定样本调用原 _recheck / evaluate / inspect，不读取旧 summary 决定结论，不运行或续跑任务。

两侧完整 case 除 configRef 外严格相同，包括任务、环境、断言、预算与路由目录；实际不同的顶层字段写入 taskChanges。configRef 默认相同，可逐字段显式放行 provider / model / profile / pluginVersion，但每侧实际配置与请求路由仍须匹配自己的计划。计划无法重算、共享原实验身份或任一执行身份时不能通过门禁；来源逐对一致，未知或不匹配的路由不能参与结论转换。

以 caseEntryId / repeatIndex 对齐矩阵并集，不按可重新编号的 sampleId 或数组位置。变化分为 regression、improvement、unchanged_passed、unchanged_failed、missing_in_baseline、missing_in_candidate、incompatible、unavailable。矩阵缺项与计划存在但 skipped / 缺证据分别显示。仅全部共有样本可比且无缺项时，按有无退化返回 1 / 0；其余为 2，并保留其他样本已确认的退化及 hasRegressions。改善不能抵消退化，0 不等于所有任务通过。

新输出 regressionComparisonFormatVersion=1。默认仅 stdout，可通过 --output 排他创建一个 JSON；不自动生成中间报告目录或更新旧证据。输入 / 写入错误返回 status=error 与退出 2；原 --report 的生成语义及原执行退出码不变。选择严格矩阵覆盖与显式字段放行，不增加任意 ID 映射、忽略缺项开关或统计推断。

## 验证

2026 年 11 月 1 日，本地 Windows。所有新样本由合成适配器、真实子进程和原录制器产生，再 fresh inspect；未调用模型。

| 命令或操作 | 实际结果 | 范围 |
| --- | --- | --- |
| 首轮 `python -m unittest discover -s test -p test_regression.py` | 15 项，1 个环境变更子用例错误 / 14.995 秒 | 测试夹具删掉了故障状态引用的文件，被既有输入校验提前拒绝；不是比较算法失败 |
| 修正夹具为保留原文件再新增文件，并补计划篡改与续跑链测试后的同一入口 | 17 项通过 / 23.024 秒 | 0 / 1 / 2、配对键、配置允许、任务字段变化、缺项、不可用、同源身份、fresh 结果和只读来源 |
| `python -m unittest discover -s test -p test_report.py` | 原 17 项通过 / 20.741 秒 | 提取加载入口与夹具后，原报告输出、复验和错误行为保持 |
| 获准环境 `npm.cmd run test:python` | 420 项全部通过 / 267.236 秒 | 完整 Python 无模型回归，含新比较、原报告、续跑链、浏览与真实子进程清理 |
| `python -m compileall -q dsh_eval scripts test`、`git diff --check`、`python -m dsh_eval --help` | 通过，帮助包含新入口及全部配置选项 | 编译、补丁与 CLI 可发现性 |
| 改动 Markdown 相对路径、标题锚点与忽略目标检查 | 8 份文档、461 个本地链接 / 114 个目标，零错误 | 公开链接不依赖私人目录或原始运行资料 |

关键反例包括：旧保存结论仍为 passed，但重新录制的候选答案错误，fresh 结果列为 regression；另一重复从 failed 变 passed 不抵消退化。已确认退化与缺失证据并存时返回 2 且保留退化。顺序颠倒导致 sampleId 变化时仍按用例 / 重复编号定位。任务输入、环境、预算、断言、录制配置或 caseId 不同不能通过允许配置变化绕过；live / synthetic 声明不同、路由不符、截断轨迹、必要工具证据缺失与 skipped 不判普通退化。真实 Python CLI 的退化退出码为 1，已存在输出拒绝覆盖。

连续续跑验收在独立基线与另一实验的两轮续跑上比较选定配置，四项保持通过，保留 reused / new 来源；与该续跑自己的原实验比较则拒绝同源身份。比较前后来源摘要相同，比较期间运行 / 续跑入口被测试禁止，确认没有追加任务。

本批完整 Python 回归通过。未修改 JavaScript / 录制器 / 宿主脚本，本轮未重复完整 Node 测试，也未新增模型任务或云端 CI。

## 风险与后续

结果仅描述所选矩阵，不是显著性、因果或总体质量结论。同一重复编号不保证独立随机样本；live 声明和摘要不是签名，输入须为稳定归档，不提供原子快照。旧计划缺少可重算快照时无法通过严格门禁。当前没有浏览器展示、Markdown 报告、模型自动 CI、任意跨任务映射或新模型验收；未提交 / 推送或运行新云端 CI。

## 文档同步

新增 docs/baseline-regression.md，更新 README、docs/configuration-reports.md、docs/architecture.md、docs/plans/m6-reliability-validation.md、docs/progress.md 和 CHANGELOG；旧阶段的验证结果保留。README 中最新已交付实现的旧引用按已存在的 084 更新，不扩大当前新功能的交付状态。
