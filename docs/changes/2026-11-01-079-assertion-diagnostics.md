# 修改记录 079 断言诊断与事件定位

日期：2026 年 11 月 1 日，Asia/Shanghai。类型：功能 / 测试 / 文档。插件版本：`0.1.2`。尚未提交。

## 问题与目标

逐次结果原来仅展示断言 JSON，无法直接对照期望与实际文本，进入轨迹后还需人工找事件。增加失败优先卡片、文本差异与关联事件跳转，保留评测结论和历史快照。

## 文件修改

| 文件 | 修改前 | 修改后 | 原因 |
| --- | --- | --- | --- |
| dsh_eval/web/app.js、style.css | 断言 JSON、轨迹分页 | 失败优先卡片、期望 / 实际、转义文本、事件序号与定位高亮 | 缩短从失败到原始证据的查看步骤 |
| dsh_eval/browser.py | 文件与分页读取 | 可选 assertionTrace 关联及 seq / runId / sessionId 定位 | 严格区分文件行号与事件序号，按会话选轨迹 |
| test/browser.test.js、test/test_browser.py | 原浏览覆盖 | 六项前端、五项 Python 回归 | 覆盖缺失、歧义、预览限制、只读与真实 HTTP 跳转 |
| README、结果浏览、架构、M6 计划、进度、CHANGELOG | 无断言诊断说明 | 补当前能力与限制 | 使用入口与实现保持一致 |

## 实现与技术取舍

期望只读 evaluation 内嵌的 case.assertions，按 ID / 类型唯一匹配；实际值只读保存的 actual。失败卡片优先，其余原序；原始 JSON 保留。文本按 Unicode 码点找共同前后缀，高亮中间差异，附转义表示。使用线性简易差异区间，不引入最小编辑距离或格式归一化。final_text 的 actual 在评测时已经 strip，页面明确说明，原答案通过事件查看。

工具断言已有结果只保存定位信息，没有实际工具正文，因此展示期望谓词和缺失提示，提供各候选调用 / 返回 / 前置结果 / 答案的按钮。不从 passed 反推工具值，不新增语义评判或重跑断言。

Python 根据 association 的 runDir 与 sha256(sessionId) 文件名选出允许读取的轨迹，返回临时 assertionTrace。定位请求同时提供 seq、runId 和 sessionId，扫描最多 8 MiB，逐行遵守 64 KiB 与 JSON 深度限制；只接受格式 1、身份一致、非负安全整数序号的唯一匹配。再读取目标周围一页并复核目标行身份与序号；缺失、重复或读取期间定位失效均拒绝。原目录、令牌、Host / Origin 与只读限制保持。

复查补充空查询反例：parse_qs 默认忽略空值，会把 `seq=` 当作无定位请求并返回第一页。改为保留空查询值交给校验，空序号或身份现在明确拒绝；目录的空未知参数也不能悄悄忽略。

trace 响应可增加 focus，页面分别显示物理行与事件序号、滚动并聚焦高亮行。定位失败保留原诊断页；成功后可以返回。持久化录制、评测、报告格式和原评测算法不变。

## 验证

2026 年 11 月 1 日，本地 Windows，Python 3.12.0、Node.js v24.14.0。全部无模型调用。

| 命令或操作 | 结果 | 证明的范围 |
| --- | --- | --- |
| `python -m unittest discover -s test -p test_browser.py` | 36 项通过 / 5.383 秒 | 新增五项：关联会话、HTTP 序号定位、重复 / 身份 / 类型拒绝、大小上限、坏行不移位、读取间目标变化和只读摘要 |
| 增补空参数反例后 `python -m unittest discover -s test -p test_browser.py -k test_http_event_focus`，修复后复跑整个 test_browser.py | 反例先失败（200 而非 400）；修复后 36 项通过 / 5.488 秒 | 空 seq / runId 不能回退普通分页；定向测试采用 discover，直接包路径调用因 test 不是可导入包而不可用 |
| 最终按原始字节行定位并补 64 KiB 边界后，同一浏览测试入口与 compileall | 36 项通过 / 5.572 秒，编译通过 | 有 / 无末尾换行的恰好 64 KiB 行均可定位；消除人为补算换行的一字节偏差，不把整份文件拆成行列表 |
| 首次前端定向检查及修正 | 首次两项测试失败；修正差异节点选择和最小 DOM 的文本拼接断言后，一项嵌套面板查找仍失败；改为查找实际嵌套标题后通过 | 测试查找逻辑修正，未将失败写为生产代码通过 |
| 首次 `npm.cmd test` | 109 项，106 通过 / 3 失败 | 一项为上述嵌套面板测试查找；另外两项真实子进程检查受沙箱 spawn EPERM 限制 |
| 修正测试后获准环境 `npm.cmd test` | 109 项全部通过 / 6.995 秒，含 24 前端项 | 完整 Node 回归，真实子进程未被 mock 替换 |
| `npm.cmd run check` | 43 个文件通过 | JavaScript 语法 |
| `python -m compileall -q dsh_eval scripts test` | 通过 | Python 语法编译 |
| 原录制器合成失败与实际浏览器检查 | 失败卡片、期望 / 实际文本、答案跳转、行高亮、返回诊断页均符合预期 | 合成事件经 recorder / evaluate / inspect，不是模型任务 |
| 首次沙箱 `npm.cmd run test:python` | 运行 373 项 / 251.066 秒，5 处错误 | 四项真实进程树终止受限；Web 生命周期 setUpClass 因 spawn EPERM 失败，其类内测试未执行；不作为完整通过 |
| 获准环境 `npm.cmd run test:python` | 392 项全部通过 / 233.612 秒 | 空参数修正后启动的完整无模型回归；最后的字节行读取调整另由上述最终 36 项浏览回归覆盖 |
| 改动 Markdown 相对路径、标题锚点和忽略目标检查 | 首轮 12 份文档、438 个本地链接 / 107 个目标；补齐架构 072 引用后最终 439 个链接 / 107 个目标，均零错误 | 公开链接不依赖 runs 或私人资料 |
| `git diff --check`、跟踪 / 忽略检查 | 补丁通过；runs 与 private-notes 无跟踪文件，合成预览被忽略 | 原始运行未纳入公开差异 |

页面样例使用公开 read-project 用例和事件的独立副本，仅将 assistant/message 文本改为 `**synthetic-project**`；调用 `scripts/demo-eval.js` 的 recordExample 生成新录制，再调用 evaluate 保存 evaluation.json。结果为 completed / complete / failed，工具与结束断言通过，答案失败；使用 `python -m dsh_eval --browse --runs-root <本次样例目录>` 打开，最终答案 seq=4 定位到文件第 5 行。原公开 fixture 未改，样例产物留在忽略的 runs 目录。

实际页面检查后已关闭本次临时页面和浏览服务。截图为合成样例预览，不增加真实模型证据。

## 风险与后续

定位只核对保存关联和可预览事件，不校验整份轨迹完整性、内容摘要或当前断言有效性，不提供实时一致快照；仍应浏览稳定文件。超过 8 MiB 的轨迹须手动分页；工具实际正文通过事件查看。没有新增真实模型任务、提交 / 推送或云端 CI；行为约束断言、跨版本门禁与统计扩展不在本批范围。

## 文档同步

README、docs/result-browser.md、docs/architecture.md、docs/plans/m6-reliability-validation.md、docs/progress.md 与 CHANGELOG 同步；074–078 历史验证保持原样。

架构文档的当前阶段概述仍将完整十用例比较写为待定，本批依据已存在的 072 记录修正为四十项范围已完成；不改写 072 的历史结果或扩大模型结论。
