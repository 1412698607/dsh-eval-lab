# 修改记录 082 工具行为约束断言

日期：2026 年 11 月 1 日，Asia/Shanghai。类型：功能 / 测试 / 文档。插件版本：`0.1.2`。已核实起始 HEAD：`0ba0b93`；本批尚未提交。

## 问题与目标

既有 tool_result 仅要求存在合法证据链，额外调用不会单独导致失败。因此答案正确、必要读取成功，但另行访问禁止目标或反复调用工具的任务，缺少显式的行为失败条件。

新增 tool_forbidden 和 tool_call_count，允许用例声明工具 / 参数筛选及调用次数上下界；通过“答案正确但行为违规”的合成轨迹确认普通任务结论仍为 failed。

## 文件修改

| 文件 | 修改前 | 修改后 | 原因 |
| --- | --- | --- | --- |
| dsh_eval/formats.py | 三种断言 | 新增禁止调用与次数范围的严格校验 | 无效范围与拼写不能被静默接受 |
| dsh_eval/evaluate.py | 必要结果 / 文本 / 结束断言 | 共用调用匹配，统计完整任务区间的匹配调用，保存 actual 与证据序号 | 正确答案不抵消行为失败 |
| dsh_eval/web/app.js | 三种期望展示 | 新类型的筛选、范围、保存次数和零次提示 | 延续诊断卡片与证据跳转 |
| test/test_evaluation.py、test/browser.test.js | 原断言 / 浏览回归 | 九项 Python、两项前端测试 | 覆盖格式、计数边界、真实录制与 CLI 失败、缺失证据和展示 |
| README、格式 / 架构 / 固定集 / 浏览说明、M6 计划、进度、CHANGELOG | 无新行为约束说明 | 同步明确声明方式与验证范围 | 旧输入、历史样本和运行时行为保持原状 |

## 实现与技术取舍

两种类型均要求精确工具名，可选 arguments 以顶层键做类型敏感匹配，允许实际额外参数；省略或空对象匹配该工具所有调用。沿用原 _same 的嵌套值比较，不添加路径归一化、通配符或语义判断。

tool_forbidden 要求零次；tool_call_count 至少有 min / max 之一，范围为非负安全整数且 min≤max，包含端点。省略 min 为 0，省略 max 无上界；min=max 表达恰好次数。拒绝布尔 / 小数 / 字符串 / null、未知字段、result / after，且新类型不能作为 tool_result.after 的前置依赖。

计数位于既有 evaluate / task_view 门禁之后，对完整用户输入至 turn/end 区间的 tool/call 进行匹配，包括最终答案之后的调用。错误返回、无返回及迟到返回仍算调用；按独立 callId 计数，不按参数去重。重复 callId、非法参数、孤立结果、任务序号缺口仍无法评测，不把坏证据推断为零次。

actual 保存整数匹配数；evidence 保存每个匹配调用的 callId / callSeq，存在返回时加 resultSeq。失败保留原因；无匹配时 actual=0、evidence=[]。不足 min 是明确 failed。总体状态沿用原规则：必需断言有 insufficient_evidence 时仍为 unevaluable，各条失败不被抹除。

这是执行后的评测约束，不拦截工具，不是硬步骤预算或完整会话行为证明。只作用于当前校验过的任务片段。两个用例版本及评测结果格式编号不变；旧读取器拒绝未知类型，旧用例无需迁移。完整用例自动纳入既有输入冻结与计划指纹；不修改当前十用例或历史冻结断言，不扩展真实模型证据。

## 验证

2026 年 11 月 1 日，本地 Windows、Python 3.12.0、Node.js v24.14.0。全部为无模型测试。

| 命令或操作 | 实际结果 | 范围 |
| --- | --- | --- |
| 实现前 `python -m unittest discover -s test -p test_evaluation.py -k behavior` | 7 项选中测试，22 处子用例 / 测试错误 | 原校验器拒绝新类型，原求值不提供计数；保留首次失败 |
| 首次实现后完整 test_evaluation.py | 44 项通过 / 7.311 秒 | 原断言兼容及新增八项检查 |
| 补齐缺结果的完整录制反例后，同一入口 | 45 项通过 / 7.478 秒 | 新增共九项；答案通过、违规失败，CLI 退出 1；原录制字节不变 |
| `node --test --test-isolation=none test/browser.test.js` | 26 项通过 / 63.524 毫秒 | 新增两项卡片检查；min / max 的 0 保留，缺 actual 不补零，违规调用可定位 |
| 获准环境 `npm.cmd test` | 111 项全部通过 / 7.101 秒 | 完整 Node 无模型回归，包含真实子进程清理 |
| 获准环境 `npm.cmd run test:python` | 401 项全部通过 / 273.679 秒 | 完整 Python 无模型回归，覆盖评测、输入冻结、批次、报告、续跑与浏览 |
| `npm.cmd run check`、`python -m compileall -q dsh_eval scripts test` | 43 个 JS 文件及 Python 编译通过 | 语法检查 |
| 改动 Markdown 的相对链接、标题锚点、忽略目标与新行为 JSON 示例校验 | 9 份文档、485 个本地链接 / 116 个目标通过；一个示例分别通过版本 1 / 2 用例校验 | 示例无模型执行，公开文档不依赖私人资料 |
| `git diff --check`、fixtures / src / scripts 差异及运行资料跟踪检查 | 补丁通过；公开用例、录制器和宿主脚本无差异，runs / private-notes 无跟踪文件 | 未改写原固定集或引入原始运行资料 |

反例使用公开 read-project 输入 / 事件的独立副本，正常答案不变，在最终答案前或后插入额外调用：禁止路径 restricted.md，或再次读取 README.md 超过 max=1。原 Node 录制器生成新日志，fresh inspect 后为 completed / complete / failed；原三种断言全部通过，新增行为断言失败。另覆盖无返回调用、错误返回、精确工具名 / 参数类型、上下界、零次、开放录制、非法参数、重复调用身份、任务序号缺口和非正常执行。全部是合成事件，未调用模型。

本批全量回归全部通过，未新增模型调用或云端 CI。

## 风险与后续

工具名和参数必须与实际记录一致；当前不提供路径等价、全工具总次数或跨任务 / 子 Agent 约束。未声明的新约束不会自动应用到现有用例；没有新增真实模型样本、运行时工具拦截、提交 / 推送或 CI。前端验证为现有最小 DOM 回归，本批没有新增实际页面视觉验收。更丰富的状态约束与跨版本回归门禁仍按需设计。

## 文档同步

同步 README、docs/evaluation-format.md、docs/architecture.md、docs/core-evaluation.md、docs/result-browser.md、docs/plans/m6-reliability-validation.md、docs/progress.md 和 CHANGELOG；固定集说明区分评测器已支持与用例实际声明，保留既有真实验收边界。
