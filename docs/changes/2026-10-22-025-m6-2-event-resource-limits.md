# 修改记录 025 M6.2 单条事件限制与资源基线

日期：2026 年 10 月 22 日，Asia/Shanghai。类型：功能 / 测试 / 文档。插件版本：`0.1.2`。相关 Git 提交：本批尚未提交；开始时 HEAD 为已核实的 `2a228941a15bed754c0d5303f0a385212b110552`（M6.1 登记可靠性修复），工作区干净。024 的“尚未提交”保留为当时状态，本批未提交、推送、运行云端 CI 或调用模型。

## 问题与目标

原录制器只有 16 MiB 的全局待写 Buffer 上限，单个大工具结果会先分配 Buffer 和反解析，再发现队列不够；没有独立的单条策略。M6.1 合并登记之后也只有少量资源探针，尚未覆盖大文本、慢追加及分批成员到达。

本批完成已同意的 M6.2：提供可配置的整行字节限制，超限明确失败而不截断证据；沿用健康会话隔离、运行完整性和 Python 断言门禁；提供可复现的真实文件 / 独立进程资源基线。M6.3 / M6.4 不包含在本批。

## 文件修改

| 文件 | 修改前 | 修改后 | 原因 |
| --- | --- | --- | --- |
| `src/config.js`、`src/recorder.js` | 只有 maxPendingBytes，先分配 Buffer | maxEventBytes 默认 1 MiB、入口校验与 run.json 记录；先计量再解析 / 分配 | 拒绝单个超大证据，同时明确保护范围 |
| `test/event-limit.test.js`、`test/config.test.js` | 没有单条限制回归 | 10 项新增边界 / 隔离 / 生命周期回归；配置快照包含新字段 | 核对完整 UTF-8 行、有效配置及错误语义 |
| `test/test_evaluation.py` | 已有一般录制失败门禁 | 真实 Node 录制完成任务后追加超限，Python 仍拒绝断言 | 防止已有正确答案掩盖录制失败 |
| `scripts/lib/host-smoke.js`、`scripts/fixtures/output-child.js`、`scripts/check-output.js` | 三种输出子进程 | 增加真实宿主单条超限、保留前缀 / 健康会话检查及 stderr 诊断 | 验证真实组件调用链与独立进程 |
| `scripts/measure-recorder.js`、`package.json` | 无公开完整测量入口 | 8 类场景、可设重复数、新进程实写 / 采样 / inspect / 断言 | 留下可重复的资源观察，不引入性能通过阈值 |
| README、CHANGELOG、进度、架构、M3 / M6 方案、清单 / 评测说明、新资源文档 | M6.2 计划 | 实际配置、接收流程、兼容、测量数据和剩余两批 | 同步当前状态，保留历史结果 |

## 实现与技术取舍

整行 JSON.stringify 后加换行，用 Buffer.byteLength 检查 maxEventBytes；合格才反解析该字符串核对 seq，再检查全局容量并创建 Buffer。包含元信息、会话 ID、UTF-8 和 JSON 转义成本；自定义 toJSON 实际输出只处理一次。不对原对象做估算，也不使用字符长度代替字节数。

超过上限返回 false 并上报 EVENT_BYTES_LIMIT；错误只给出实际大小和阈值，沿用会话 failed、received / accepted / written 三个计数、排队跳过及 onError 异常隔离。失败会话的已写前缀不修改，正在追加的写入可能完成。健康会话继续，但 close 仍拒绝、运行 failed、inspect invalid；Python 原门禁得到 unevaluable / not_run，评测算法不改。

选择“序列化后检查”，以保持 JSON.stringify / toJSON 原语义和现有同步 record 接口。提前深度估算无法准确处理转义或自定义序列化；自定义流式序列化会扩大协议、错误与顺序改动。该选择仍有序列化的同步 CPU 和临时内存成本，未声称阻止 OOM。默认 1 MiB 是可调整的策略值，没有把它包装成统计最优阈值。没有自动截断、日志轮转、会话淘汰或宿主背压接口。

run.json 新增 maxEventBytes 接收配置，已有格式版本不变，旧运行不要求补字段。inspect 继续接受可验证的历史大行，不把新接收阈值当作离线文件限制。插件发布版本、主入口及 Python 持久化格式不变。

资源脚本使用 JavaScript，是为了在录制器同一进程观测 Node 堆 / Buffer 和文件追加；未新建第二套离线评测 / 统计算法。每个样本单独进程，实际写文件，慢写只在实际 append 前添加延迟；完整方法与 24 样本结果见 [资源文档](../recorder-resources.md)。

## 验证

环境：Windows `10.0.26200` x64、Node `v24.14.0`、Python `3.12.0`；真实组件 SessionStore `0.2.0-rc.2`、Cordis `4.0.4`。命令均于 2026 年 10 月 22 日执行。

| 命令或操作 | 结果 | 证明的范围 |
| --- | --- | --- |
| `node --test --test-isolation=none test/event-limit.test.js`，先运行于改动前 | 10 项中 8 失败 / 2 通过 | 新限制未生效；两项原路径已满足，不写成全失败 |
| `node --test --test-isolation=none test/event-limit.test.js test/config.test.js` | 18 / 18 通过 | UTF-8 精确等号边界、含换行、序列化输出、默认与显式配置、失败隔离、容量释放、重入 close、插件参数透传 |
| `npm.cmd test` | 75 / 75 通过，无跳过 | 新旧 Node 功能回归，包括登记队列与清单 |
| `python -m unittest discover -s test -p test_evaluation.py -v` | 36 / 36 通过 | 新增超限录制阻断任务断言 |
| `npm.cmd run test:python`，获准环境 | 138 / 138 通过，39.524 秒 | 全 Python 回归，真实子进程与专属测试进程清理 |
| `npm.cmd run check`；`python -m compileall -q dsh_eval test` | 35 个 JS 文件及 Python 编译通过 | 最终语法检查 |
| `npm.cmd run demo` | 8 条模拟事件写出并正常关闭 | 模拟录制，不是宿主或模型验收 |
| `npm.cmd run smoke:host` | 6 条人工事件原样导出、真实插件卸载后通过 inspect | 真实 Cordis / SessionStore 组件，不执行模型 |
| `npm.cmd run check:output`，获准环境 | normal / write-error / abrupt-exit / event-limit 四个真实子进程通过；inspect 0 / 1 / 2 / 1，stdout 均为空 | 超限保存原 6 行、失败状态、健康会话封存，错误留 stderr；其他生命周期回归保留 |
| `npm.cmd run measure:recorder`，获准环境最终版 | 8 类 × 3 次 = 24 个新进程全部符合预期 | 长文本、超限拒绝、多会话突发 / 分批、慢追加及队列溢出，实际状态与文件计数核对 |
| demo 新目录执行 `npm.cmd run inspect -- --run runs/<runId>` | complete / sealed / 0，预期 1 会话 | 新默认配置下的实际 CLI 检查 |
| `git diff --check`、`git check-ignore`、`git ls-files`，Python 核对公开 Markdown 相对链接与测量表格 | 差异检查通过；43 份 Markdown 的 280 个相对链接有效；8 行资源表与保存样本一致；20 个公开修改 / 新增文件文本检查通过 | runs / private-notes 仍忽略且无跟踪，公开链接不指向原始日志或私人材料；仅有 LF / CRLF 提示 |

资源入口首次在普通沙箱遇到 spawn EPERM，记为未执行成功；随后获准运行 7 类 × 3 次，再补充分批场景后运行最终 8 类 × 3 次，早期结果保留不覆盖。新宿主超限 fixture 的首次输出检查缺少 SessionStore 所需 surfaceOp，被宿主拒绝；补齐真实工具结果结构和 surfaceOp 后四场景通过。该失败是验证事件构造问题，不计作事件限制生效。

最终资源样本中，每次 16 个 2 MiB 正文全部以 EVENT_BYTES_LIMIT 拒绝，健康事件封存；慢写 48 行全量写入，队列溢出场景接受 4 条、写入 2 条且整体 invalid。600 突发会话均 complete；清单写 3 份 / 279456 字节，分六批则 8 份 / 629041 字节。超限场景采样 heapUsed 增量 24.94～24.97 MiB，证明这不是 1 MiB 内存硬上限。完整规模、采样定义和数据表留在资源文档。

## 风险与后续

新默认上限会拒绝旧版可接收的大行，需显式配置；没有真实模型任务分布来证明默认值适合所有工具。同步序列化、输入对象、成员表、Promise、哈希、状态 / 清单快照仍可消耗资源。采样不能观察所有瞬时峰值，定时器可能受阻塞影响，不给出性能提升、长期稳定性或总内存硬限额结论。

record 成功只表示排队，flush 不等于 fsync，日志不是完整会话备份或确定性重放。没有新模型、历史模型样本复验或新云端运行。下一批 M6.3 先确定两套实际配置、固定用例和调用预算；之后 M6.4 仍需真实 Web 页面取消 / 正常退出 / 处理中断验收。

## 面试讨论点

可用同一事件解释“字符数、完整序列化字节、队列字节、堆 / Buffer / RSS”为什么不同；可以演示已产生正确任务答案，但后续录制超限仍不能作为可信评测样本。资源测试既检查预期成功也检查预期失败，并公开分母、方法和无法保证的范围。清单合并减少待写快照保留，不等于消除成员增长和累计重写成本。

## 文档同步

已同步 README、CHANGELOG、progress、architecture、运行清单、评测门禁说明、M3 / M6 方案和新资源文档；本机 handoff / interview 追加当前结果与下一批入口，继续忽略且不作为公开依赖。历史 023 / 024 和旧验证结果不覆盖。
