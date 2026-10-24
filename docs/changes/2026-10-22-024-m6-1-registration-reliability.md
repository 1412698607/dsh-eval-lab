# 修改记录 024 M6.1 登记合并与替换重试

日期：2026 年 10 月 22 日，Asia/Shanghai。类型：修复 / 测试 / 文档。插件版本：`0.1.2`。相关 Git 提交：本批尚未提交；开始时 HEAD 为已核实的 `52cfbca`（M6.1），跟踪文件干净。未自动提交、推送、触发云端 CI 或调用模型。

## 问题与目标

M6.1 审查发现两项 P2 问题，修复范围属于 M6.1，不提前实施 M6.2。

1. 获准环境五轮各 600 个小会话中，三轮 run.json rename 报 EPERM，之后用同一写入函数重写当时原快照均成功。首次失败立即成为永久 manifestError，阻断后续登记，运行仅保留部分成员；inspect 正确返回 unverified / 2。错误可随后恢复，但具体占用原因未知，不能归因于杀毒软件或某个进程。
2. 每个新会话都复制完整成员快照并保留在 Promise 队列；同步突发 N 会话累计保留 N(N+1)/2 个成员条目。登记在事件容量检查前，全部事件被拒也会产生该积累。审查资源探针的 300 / 600 会话保留堆增量约 5.7 / 21.7 MiB；这不是完整 benchmark，原关闭用时受到 EPERM 影响，不作性能结论。

目标是容忍适当的短暂替换失败，消除待写完整快照的平方级积累，同时保留登记前禁写、首次观察顺序、失败身份、健康会话排空以及 record / flush / close 的原有语义。

## 文件修改

| 文件 | 修改前 | 修改后 | 原因 |
| --- | --- | --- | --- |
| `src/session-status.js` | 临时文件写好后仅尝试一次 rename | 仅对 EPERM / EACCES / EBUSY 有限退避，使用同一临时文件重试替换 | 避免适当短暂替换错误立即永久破坏运行 |
| `src/recorder.js` | 每个新成员捕获完整快照并排队 | 尚未开始的登记共用批次屏障，开始时才生成快照 | 消除排队快照的平方级保留，维持登记依赖与串行顺序 |
| `test/manifest-queue.test.js` | 无对应回归 | 七项真实临时文件与受控文件边界故障测试 | 验证恢复、失败、合并、交错、关闭和重入 |
| `README.md`、`docs/run-manifest.md`、`docs/architecture.md` | 一次替换及逐成员快照说明 | 有限重试、共享登记批次及准确资源边界 | 与实现一致，运行命令及格式版本不变 |
| `docs/progress.md`、`docs/plans/m6-reliability-validation.md`、`CHANGELOG.md` | 023 的原交付状态 | 追加本次修复及验证，核实 52cfbca 已提交 | 保留历史结果，明确当前状态及后续范围 |

本机交接和面试材料另行追加本批结果，仍被忽略，不是公开仓库依赖。

## 实现与技术取舍

`writeStatus` 仍先写同目录 UUID 临时文件，然后替换目标，最后清理临时文件。只在 rename 的 EPERM / EACCES / EBUSY 时最多尝试六次；五次计划等待为 10 / 20 / 40 / 80 / 160 ms，累计计划退避 310 ms。重试不重新序列化或写临时文件，不提前删除目标；失败时仍按原错误通道拒绝。永久权限错误可能产生相同错误码，所以仍有明确尝试上限；该上限不能约束单次底层文件调用的耗时。

选择在原公共写入函数内处理替换错误，运行清单和会话状态都能容忍这种短暂失败。临时文件创建 / 写入及其他错误不重试，JSONL append 也不重试，避免将不明确的追加结果重复写入。没有新增配置项或仅用于测试的公开 API。

登记使用一个待执行共享 Promise。新会话先加入内存 Map，绑定当前待执行批次；批次在串行队列中实际开始时才读取成员表并生成完整快照，同时清空待执行批次引用。写入期间的新会话因此创建或加入下一批，不会借用尚未包含自己的快照。一个进行中的快照与一个无快照的待执行批次取代逐成员保存快照。

每会话初始状态和日志追加仍等待它自己的登记屏障。flush 等待选中会话检查点和其登记依赖；第一批会话可以在后续批次仍写入时完成自己的 flush。close 先禁止输入，等待所有观察到的会话队列，再串行保存终态，不漏末批；重复 close 和关闭后的 flush 共享同一 Promise。序列化重入可新增成员，错误回调重入也不能绕过永久运行错误。

重试耗尽后保持 manifestError、onError(error, null)、停止新输入与 AggregateError 语义；未登记会话没有日志 / 状态文件，已登记健康会话仍能排空。会话容量或序列化失败仍保留身份及失败状态。批次合并没有绕过容量校验，也没有移除必须保存的失败身份。

## 验证

环境：Windows、Node.js v24.14.0、Python 3.12.0，2026 年 10 月 22 日。新增七项回归先在未修改的生产实现上运行，六项失败、一项通过；失败包括单次 EPERM 即终止、永久错误仅尝试一次、80 个同步拒绝会话产生 80 次登记，以及交错成员不能合并。修复后七项全部通过，无跳过。

| 命令或操作 | 结果 | 证明的范围 |
| --- | --- | --- |
| `node --test --test-isolation=none test/manifest-queue.test.js` | 七项通过 | 三类可重试错误恢复、六次耗尽、其他 rename 错误及临时文件写入不重试、临时文件清理、登记合并、交错 / flush / close / 重入、健康会话排空 |
| `npm.cmd test` | 完整 65 项通过 | 原录制、inspect、新旧格式和宿主适配回归 |
| `npm.cmd run check` | 33 个 JS 文件语法通过 | 生产与测试语法 |
| `python -m unittest discover -s test -p test_evaluation.py -v` | 35 项通过 | 新旧清单对离线断言的原门禁 |
| `python -m unittest discover -s test -p test_browser.py -v` | 17 项通过 | 只读浏览及录制格式兼容 |
| `npm.cmd run test:python` | 获准环境完整 137 项通过 | 包括真实子进程与强停的确定性回归，不调用模型 |
| `npm.cmd run smoke:host` | 真实 Cordis 4.0.4 / SessionStore 0.2.0-rc.2 六事件通过 | 宿主检查点与卸载封存 |
| `npm.cmd run check:output` | 首次沙箱 spawn EPERM，不计通过；获准环境 normal / write-error / abrupt-exit 三场景通过 | 真实 stdout / stderr 与未关闭退出 inspect / 2，无 mock 替代 |
| 获准环境多会话文件探针，五轮各 600 条小事件 / 不同会话 | 3000 条全部接受；五次 close 成功、各 600 成员、sealed / complete / 0；无上报的永久录制错误 | 真实文件写入的指定规模复验；没有记录底层重试次数，不声称自然触发了暂时错误 |
| 获准环境 `node --expose-gc` 资源探针 | maxPendingBytes=1，100 / 300 / 600 会话全部事件拒绝，保留堆增量 291680 / 471976 / 887024 字节；close 分别报告 100 / 300 / 600 个会话错误，inspect / 1 | 同步入队后、异步队列运行前各 GC 一次，测量 heapUsed 差值；单次指定输入观察，非总内存硬限额或完整 benchmark |
| 最后一次测试文件调整后的 `npm.cmd test` / `npm.cmd run check` | 65 项 / 33 文件再次通过 | 包含安全清理、屏障超时和回调外重入断言的最终测试版本 |
| 公开 Markdown 相对链接、`git diff --check`、忽略 / 跟踪核对 | 43 份 / 268 链接有效；diff 检查通过；runs / private-notes 均忽略且无跟踪文件 | 文档引用有效，不依赖本机原始日志或私人材料 |

正常沙箱环境同样执行五轮 600 会话，全部 complete / 0；资源探针另留独立结果。审查证据、修复前失败测试、修复后测试与获准环境探针都保留在忽略目录，没有覆写旧运行。

下面公开验收命令的脚本正文也从记录提取后实际执行，五轮均 complete / 0、各 600 成员；导入路径仅按脚本保存目录调整，不改变逻辑。

公开的七项回归可直接复现有界重试与批次合并，不需要本机探针文件。实际多会话测量使用审查保留的 burst-probe / resource-probe 脚本；等价的小会话文件验收可在项目根运行下列命令，不调用模型：

```powershell
@'
import { resolve } from "node:path";
import { randomUUID } from "node:crypto";
import { createRecorder } from "./src/recorder.js";
import { inspectRun } from "./src/inspect.js";
const outputDir = resolve("runs", "manifest-validation", randomUUID());
for (let round = 0; round < 5; round++) {
  const recorder = createRecorder({ outputDir });
  for (let i = 0; i < 600; i++) recorder.record(`session-${i}`, { seq: 0 });
  await recorder.close();
  const report = await inspectRun(recorder.runDir);
  console.log(recorder.runId, report.exitCode, report.runManifest);
  if (report.exitCode !== 0 || report.runManifest.expectedSessionCount !== 600) process.exitCode = 1;
}
'@ | node --input-type=module
```

## 风险与后续

未查明最初 Windows EPERM 的具体占用原因；受控注入证明恢复机制，真实探针证明指定规模可完成，两者不能互相替代。重试只限制次数和计划等待，不保证操作系统 I/O 在固定总时间内返回。

修复消除了待写完整快照的平方级积累，仍有随会话数增长的成员表、Promise 队列、哈希、错误和正在写入的完整快照。多批分散新增成员仍需多次写完整集合，累计 I/O 仍可能呈平方级；不承诺总内存或累计 I/O 硬上限。堆数据不覆盖外部 Buffer、RSS、全部输入分布或长期负载；不以关闭用时或这组小样本宣称性能提升比例。

协议版本和入口不变，无迁移或历史重写。record 成功只代表排队；flush 不是 fsync，日志不是完整会话备份。下一批仍是 M6.2 单条事件限制和资源基线，其后 M6.3 真实评测集、M6.4 Web 生命周期；本批未实现这些功能。

## 面试讨论点

可以用“先登记成员再写成员文件”的依赖说明为什么不能只对事件 Buffer 设限：元数据队列本身也会积累。共享屏障需保证新成员不会错误等待旧快照，关闭需等待末批，永久错误仍要明确拒绝；临时替换重试不能扩到非幂等追加。测试分别注入故障和运行真实文件负载，避免把沙箱权限错误当成产品根因。

## 文档同步

已更新 README、CHANGELOG、progress、architecture、运行清单协议和 M6 方案，并在本机 handoff / interview 追加当前结果。023 的原结果保留为历史，当前状态以 024 和 progress 为准。公开资料不链接私人材料或原始运行日志。
