# 修改记录 028 M6.3 关键步骤与空文件断言修复

日期：2026 年 10 月 24 日，Asia/Shanghai。类型：修复 / 测试 / 文档。插件版本：`0.1.2`。相关 Git 提交：本批尚未提交；已核实基线为 `a239d7d`，包含 026 配置传递修复和 027 固定评测集。旧记录的未提交说明保留为当时状态。

## 问题与目标

审查复现三项问题：发现 / 引用 / 恢复任务只检查必要调用出现，步骤反序也 passed；空文件仅检查 isError=false，非空工具返回配 EMPTY_FILE 答案仍 passed；README 仍写 M6.3 待开发、没有模型调用，与 027 单配置真实验收冲突。

本批修复断言并补充回归，不重跑真实模型。目标是拒绝上述误通过，同时保留独立路径交错、额外工具调用之后补做合法链及旧用例兼容；原模型任务与冻结输入不改写。

## 文件修改

| 文件 | 修改前 | 修改后 | 原因 |
| --- | --- | --- | --- |
| `dsh_eval/formats.py` | 工具结果仅可约束 isError / textContains | 可选 after 和 result.textEquals，严格校验类型及依赖引用 | 描述关键步骤和精确空文本 |
| `dsh_eval/evaluate.py` | 各断言独立查找任一匹配调用 | 按声明顺序求值，保存最早完成的合格证据并检查先行结果 → 后继调用 | 拒绝反序和未等结果便发出后继调用 |
| `fixtures/evaluation/core/` 中七个用例 | 六个顺序任务无跨步骤约束，空文件无文本检查 | 六个用例共 11 条 after 关系，empty-file 精确比较空字符串 | 不修改任务、环境、配置和预算 |
| `test/test_core_suite.py` | 原六项无模型验收 | 新增五项回归，必要证据删除 / 状态测试沿完整依赖求值 | 覆盖九个反例及三个合法替代路径 |
| `test/test_assertion_constraints.py` | 无可选约束边界测试 | 八项格式 / 文本 / 依赖测试 | 类型、引用、缺失、失败、乱序完成及多候选匹配 |
| README、progress、core-evaluation、evaluation-format、architecture、M6 方案、用例 README、CHANGELOG | 当前状态和断言能力不完整 | 同步当前实现、兼容、历史验证及本次无模型范围 | 公开文档可独立接续 |

JavaScript、录制 / inspect、状态化环境和模型调度不变。main.py 保留。

## 实现与技术取舍

扩展已有 tool_result：after 仅接受 assertions 中前面某条 tool_result 的 ID，因此输入验证即可拒绝未知、自身、向后、循环和非工具依赖。evaluate 通过 check_assertions 依次计算，后继 callSeq 必须严格大于先行匹配 resultSeq；已有匹配但顺序错误为 failed，先行 failed 传播 failed，缺少先行证据保持 insufficient_evidence，缺上下文不会放行。

对每个断言选满足内容及依赖、resultSeq 最早的匹配结果。这一选择给后继保留最大的合法时间范围，避免首个发出的调用返回较晚而错误拒绝一条真实可行链。额外早期调用不阻止后续完整合法链；independent-retries 分别声明 alpha / beta 自身的依赖，不附加两路径之间的顺序。

textEquals 接受字符串包括空串，按全部文本块的拼接结果精确比较，不 strip；与 textContains 互斥，后者仍要求非空。空白或后续非空块不能被当作空文件。复用已有三种断言，没有增加另一套运行器或工具环境。

用例 1 / 2 均支持两个可选字段，格式编号不变，输入不补默认；不含新字段的用例保留原有存在性语义。旧严格读取器会拒绝新字段，应升级读取器。当前七个用例的完整输入已变化，旧实验的冻结快照仍保持原断言；标准 report 不自动替换成当前用例。

## 验证

2026 年 10 月 24 日，Windows、Python 3.12.0 / Node.js v24.14.0。本次没有启动模型任务或重跑真实 Harness。

| 命令或操作 | 结果 | 证明的范围 |
| --- | --- | --- |
| 先添加五项固定集回归，运行 `python -m unittest discover -s test -p test_core_suite.py -v` | 旧实现 11 项中三个测试方法出现九个 subTest 失败；修复后 11 项全通过，5.904 秒 | 反序四场景、提前调用两场景、非空返回三场景被拒绝；独立交错及补做合法链仍通过 |
| `python -m unittest discover -s test -p test_assertion_constraints.py -v` | 八项通过 | 可选字段类型和依赖、精确文本、多候选 / 乱序完成、先行缺失或失败 |
| `python -m unittest discover -s test -p test_evaluation.py` | 原 36 项通过 | 原离线评测行为兼容 |
| `npm.cmd run test:python` | 163 项通过，45.800 秒 | 获准环境的完整 Python 回归，真实子进程清理，无模型调用 |
| `npm.cmd test` | 79 项通过，无失败 / 跳过 | 原 Node 回归 |
| `npm.cmd run check`、`python -m compileall -q dsh_eval test` | 36 个 JS 文件及 Python 编译检查通过 | 语法 |
| 对 027 保存的十项录制以当前用例调用 evaluate | 十项 passed | 七个用例仅断言变化，新断言检查现有真实录制，不是新模型执行 |
| 对原冻结实验调用 generate_report | 十项 verified / matched / passed，changedFields 全空，comparisons 为空 | 原用例兼容，未改写历史结果 |
| 原始文件摘要前后比较 | 125 份 JSON / JSONL 与 027 保存摘要完全一致 | 原实验、输入、结果及录制未改写 |
| 公开文档、README 当前状态、忽略规则与 `git diff --check` | 50 份公开 Markdown / 335 个相对链接有效，README 定向状态检查通过，文本检查通过 | 原十行用量表与证据一致；runs / private-notes 无跟踪文件，仅 LF / CRLF 提示 |

原实验 ID `6530df76-86e2-4ea1-80a9-86ca71e74e4e`，本次原冻结断言复验报告 ID `c1a95bab-f3c9-4f1c-9dcd-2a33bd98ef36`。实际检查结果和更严格断言的十份离线评测另存于忽略的 runs；可移植公共命令见 [固定评测集验收](../core-evaluation.md)。模型调用数本次新增为零，不把 027 的 32 次已结算调用重新计为本次运行。

## 风险与后续

after 只约束声明的先后关系；不检查固定调用次数、全部额外行为或安全策略。精确文本比较针对文本块，不把录制摘要当作签名。没有新增稳定性、配置比较或费用结论。

旧快照的报告仍回答旧评测条件，当前断言的离线检查单独保存，不能把它标作重新执行模型。下一批 M6.4 验证页面取消、正常退出和处理中断；双配置 / 重复扩展及新的模型规模另定。本批未运行云端 CI、smoke:host、check:output 或资源测量，没有自动提交 / 推送。

## 文档同步

已同步 README 当前里程碑、progress、评测格式、架构、固定评测集、M6 方案、用例说明、CHANGELOG。历史记录 026 / 027 及其验证不覆盖。
