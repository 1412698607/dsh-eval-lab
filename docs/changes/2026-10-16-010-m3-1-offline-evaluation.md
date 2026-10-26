# 修改记录 010 M3.1 用例与离线证据断言

日期：2026 年 10 月 16 日，Asia/Shanghai。类型：功能 / 测试 / 文档。插件版本：`0.1.2`。相关 Git 提交：本批尚未提交；已核实基线 `4f54ddf`（M2.3 与路线），合并提交为 `de86bd2`。分支：`20261015/feat/eval-workflow`。

## 问题与目标

M2.3 固定 Python 检查器只能理解受控 fixture，无法加载不同任务和预期行为。下一批需要明确用例执行编号及结果协议，在复用现有录制检查的前提下，判断实际工具证据和最终答案，避免把取消、录制损坏、证据不足或工具正常返回错误都混为任务失败。

本批完成 M3.1：版本化用例 / 清单 / 结果、独立 caseRunId、三种离线断言与三维分类；通过两个公开合成用例和反例验证。不实现真实任务驱动、环境执行、状态化工具或批次调度。

## 文件修改

| 文件 | 修改前 | 修改后 | 原因 |
| --- | --- | --- | --- |
| `dsh_eval/__init__.py`、`formats.py` | 无通用包与用例约定 | 标准库包及版本 1 用例 / 清单校验 | 固定字段、版本、身份、配置与预算边界 |
| `dsh_eval/evaluate.py` | 仅固定 fixture 检查 | 调用 Node inspect，单任务证据关联与通用断言 | 保持摘要校验职责在 JavaScript，Python 判断任务事实 |
| `dsh_eval/__main__.py` | 无通用命令 | 显式 case / evidence / 新输出文件，JSON 与 0 / 1 / 2 退出码 | 可复核的离线入口，保留历史结果 |
| `fixtures/evaluation/` | 无公开评测数据 | 两个用例及对应人工合成事件、说明 | 公开仓库不依赖私人真实日志 |
| `scripts/demo-eval.js`、`package.json` | 无用例证据演示 | 原记录器生成两个独立用例身份的日志，新增 demo:eval | 不在 Python 复制封存或摘要实现 |
| `test/test_evaluation.py` | 6 项旧固定检查测试 | 新增 24 项格式、证据、真实 Node 集成及 CLI 测试，总计 30 项 | 正反例与失败分类验证 |
| `README.md`、`docs/evaluation-format.md` | 无通用离线运行说明 | 当前入口、三个版本格式、证据与限制 | 使用方式及接口可接续 |
| `docs/progress.md`、`docs/architecture.md`、`docs/plans/m3-regression-evaluation.md`、`CHANGELOG.md` | M3.1 仍为计划；基线分支过时 | 更新实际实现、验证及 M3.2 下一批入口 | 当前状态与实际 Git / 代码一致 |

未修改 `src/`、既有录制协议、`scripts/verify_live.py` 或 `main.py`；插件版本和分发文件范围保持当前基线。

## 实现与技术取舍

1. 用例以 caseFormatVersion 1 描述输入、初始文件声明、配置引用、超时预算声明和全部必需断言；严格拒绝未知字段 / 断言 / 版本、重复键、非有限数字、重复断言 ID 与危险或冲突文件路径。首版用 Python 校验器落实约定，不增加 schema 第三方依赖。
2. evidenceFormatVersion 1 明确 UUID caseRunId（不能直接用录制 runId）、caseId、runId、sessionId、runDir、来源、适配器配置、预算实施标记与执行事实。runDir 相对清单文件解析，单会话范围拒绝额外片段，不猜测最新目录。复验沿用执行身份。
3. Python 每次直接调用现有 Node inspect，校验报告 / 退出码一致。开放、损坏、缺失、进程不可用 / 超时均不能继续判断任务通过。重新读取稳定文件后再复核录制身份与插件版本，关联不符降为录制 unverified，原 inspection 保留。
4. completed 必须与唯一 completed 结束及无冲突退出事实一致；cancelled 要求实际 aborted/user。非正常完成不运行普通任务断言。超时和运行错误事实由适配器声明，本批测试分类，不伪称已执行真实超时 / 取消干预。
5. 单任务视图要求唯一匹配用户输入、结束和最终文本，任务内序号连续；未知事件跳过，已知结构错误、孤立 / 重复 / 倒序工具结果拒绝。final_text 精确检查最终文本；tool_result 按用例工具名和参数匹配并关联 callId，结果必须先于最终答案；turn_end 完整比较原因。
6. 明确不符为 failed，缺匹配证据为 insufficient_evidence。总体只在正常执行、录制有效、证据充分时给 passed / failed；其他为 unevaluable。每条断言保留结论与序号 / callId，输出同时保留用例快照、配置、预算标记和路径。不采集或推算费用、token、耗时等指标。
7. 合成数据经过实际录制器生成 JSONL 和状态，避免再写一套生产摘要校验。演示生成两份独立证据只是离线输入，不是模型任务或批次调度。结果以新建模式保存，已有文件不能覆盖；本批未实现结果原子发布。

## 验证

2026 年 10 月 16 日，仓库根目录，Windows / Python `3.12.0` / Node.js `v24.14.0` / npm `11.9.0`：

| 命令或操作 | 结果 | 证明的范围 |
| --- | --- | --- |
| `npm.cmd run check` | 22 个 JavaScript 文件通过 | 新合成演示与原有脚本语法 |
| `npm.cmd test` | 36 项通过，0 失败 / 跳过 | 原 Node 功能回归 |
| `npm.cmd run test:python` | 30 项通过 | 原 6 项 + 新 24 项；格式、断言、真实记录器 / inspect、分类及 CLI |
| `python -m dsh_eval --help` | 正常显示 case / evidence / output 参数 | Python 包入口 |
| `npm.cmd run --silent demo:eval`，分别执行 `python -m dsh_eval --case <casePath> --evidence <evidencePath> --output <新的 evaluation.json>` | read-project 与 missing-file 均 passed；execution completed / recording complete / assertions passed，source synthetic | 两个独立 caseRunId、runId 和会话；无模型或实际工具调用 |
| 测试中成功评测后截断同一日志再评测 | invalid / unevaluable，断言 not_run | 旧成功结果不能掩盖磁盘损坏 |
| 测试中用真实记录器 flush 后不 close | unverified / unevaluable，断言 not_run | 完整 JSONL 也不能代替封存 |
| 测试中缺结果、错 callId、错误答案、倒序 / 重复结果、序号缺口、输入 / 配置不符、错误关联和额外会话 | 均不能 passed；明确答案 / 结果不符为 failed，证据缺失为 unevaluable | 通用任务证据边界；额外会话负例单独构造有效状态供真实 inspect 检查 |
| 测试中取消 / 超时 / 运行错误清单与结束事实 | 保留执行分类、unevaluable、断言 not_run；完成声明冲突转 unknown | 分类逻辑，不是本批真实模型生命周期验证 |
| Node 不可用 / inspect 超时错误路径 | 模拟异常，映射 unverified | 仅错误路径使用模拟；录制正反例使用真实 Node 子进程 |
| `npm.cmd run smoke:host` | 6 条人工事件与卸载后封存通过 | 真实 SessionStore / Cordis，无模型调用 |
| `npm.cmd run check:output` | 首次沙箱 EPERM，获准环境执行同一命令后 normal / write-error / abrupt-exit 全部通过 | 真实子进程，不用 mock 代替；abrupt-exit inspect 为 2 |
| `python -m compileall -q dsh_eval scripts/verify_live.py test/test_evaluation.py` | 通过 | Python 语法检查 |
| `git diff --check`；按 Markdown 引用提取相对链接并解析、检查存在性及 `git check-ignore`；`git ls-files runs private-notes` | diff 无空白错误；21 份公开、2 份私人 Markdown 的 84 个本地链接有效，公开目标均可提交；runs / private-notes 无已跟踪文件且忽略规则有效 | 文档与公开 / 私人隔离检查；CRLF 提示不是空白错误 |

演示复现时使用该次输出的明确目录，示例占位符不指向任何原始真实会话。全部合成运行与输出写到已忽略 runs；公开样例 JSON 可提交。没有执行 `live:prepare` / `live:run`，没有复验旧真实模型结果或测量性能 / 成本 / 模型成功率。

## 风险与后续

- 离线模块基于停止写入目录或稳定副本；不提供在线一致快照。sealed / flush 没有 fsync，SHA-256 不是签名，删除整对文件等录制限制沿用现有说明。
- source、provider / model / profile、进程干预与预算实施是证据生产者声明；本批只独立核对日志内可见事实和插件版本。环境文件与预算只声明，不能当作已应用或强制执行。
- 首版仅单会话单任务；没有 JSON 字段断言、跨断言顺序 / 次数约束、真实通用驱动、状态化工具、实时桥接、批次 / 重复试验或报告指标。
- 下一批 M3.2：Python 准备独立 workspace / 新会话，复用真实 CLI headless 启停，采集真实配置、执行 / 预算事实与录制关联，再调用本批离线模块。验证正常任务、启动 / 路由错误、超时 / 取消和清理；M3.3 / M3.4 按路线推进。

## 文档同步

已同步 README、评测格式、进度、架构、M3 路线、CHANGELOG、公开 fixture 说明。历史记录和历史验证不覆盖。公开链接只引用可提交文件。
