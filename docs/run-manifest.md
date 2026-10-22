# M6.1 运行级会话清单

更新：2026 年 10 月 22 日，Asia/Shanghai。插件版本仍为 `0.1.2`；新生成的 `run.json` 为 `formatVersion: 2`，JSONL 事件包装和会话状态仍分别为版本 1。M6.1 实现见 [记录 023](changes/2026-10-22-023-m6-1-run-manifest.md)，后续替换重试与登记合并修复见 [记录 024](changes/2026-10-22-024-m6-1-registration-reliability.md)。

## 解决的问题

旧 inspect 从目录里发现 JSONL / status，再检查已找到的片段。如果一个会话的两个文件一起被删掉，目录不再留下该会话的身份，其他片段仍可能 complete。

新运行在 `run.json` 保存应包含的会话集合；inspect 将清单与实际目录对照，即使整对文件消失，也能报告登记会话缺失。它只覆盖本次录制器观察到的会话，不补齐插件加载前、恢复或 fork 的历史，不是完整会话备份。

## 格式与版本

原目录布局不变：

```text
<outputDir>/<runId>/
  run.json
  <sha256(sessionId)>.jsonl
  <sha256(sessionId)>.status.json
```

`run.json` 保留 plugin、pluginVersion、runId、startedAt、captureScope、sessionFileNaming、statusFormatVersion 和 maxPendingBytes，新增以下内容。下面省略其他元信息，哈希名为占位示意：

```json
{
  "formatVersion": 2,
  "runManifestFormatVersion": 1,
  "state": "sealed",
  "sessions": [
    {
      "sessionId": "example-session",
      "traceFile": "<sha256(example-session)>.jsonl",
      "statusFile": "<sha256(example-session)>.status.json"
    }
  ]
}
```

| 字段 | 含义 |
| --- | --- |
| formatVersion=2 | 运行元信息的新版本，与 JSONL 每行的 formatVersion=1 分开；旧 inspect 会拒绝这个运行版本 |
| runManifestFormatVersion=1 | 会话清单自身的结构版本 |
| state=recording | 成员集合仍可增长，尚未确认运行关闭 |
| state=sealed | 已停止接收，已等待所有会话队列成功封存，再保存最终成员集合 |
| state=failed | 关闭时存在会话录制错误，不能视为成功封存 |
| sessions | 按首次观察顺序登记 sessionId 和两个固定哈希文件名；身份或文件名不能重复，也不能是任意路径 |

插件版本保持当前开发版本，协议能力以文件中的格式版本区分。新记录必须配套使用升级后的 inspect；不能仅从 pluginVersion 推断元信息结构，也不会自动改写历史目录。

## 写入与关闭顺序

1. 创建运行目录时，同步保存版本 2、recording、空 sessions 的初始 run.json。初始化失败直接报错。
2. 首次观察非空 sessionId 时，将会话加入内存集合，加入共享待执行登记批次。批次实际开始时按首次观察顺序生成当前完整清单；同步突发的多个成员共用一次登记，排队阶段不为每个新成员保留完整快照。
3. 该会话等待自己所属批次保存成功，才允许保存它的初始状态或追加 JSONL。正在写入的快照保持不变；写入期间的新成员进入下一共享批次。运行清单仍串行替换，避免较旧集合覆盖较新集合；选中会话的 flush 等待其自身登记依赖，不要求后续其他会话先完成。
4. 会话事件仍按原队列写入，内容在 record 调用时序列化固定。序列化、序号或容量错误的会话也保留登记及失败状态；其他健康会话仍可封存。
5. close 禁止新输入，等待全部会话队列，再保存 sealed 或 failed 的最终清单；重复 close 共享同一 Promise。

清单与会话状态复用同目录临时文件加 rename 替换。仅 rename 的 EPERM / EACCES / EBUSY 使用同一已写好临时文件重试：最多六次尝试，等待依次为 10 / 20 / 40 / 80 / 160 ms，累计计划退避 310 ms。这个限制不约束单次底层文件调用的耗时；错误码也不证明占用根因，永久权限错误仍会耗尽后失败。临时文件创建 / 写入和其他 rename 错误直接失败，不重试 JSONL append，避免重复追加。

清单登记重试耗尽或出现其他错误时，未成功登记的会话不创建日志或状态文件；记录器停止接受后续事件，flush / close 通过 AggregateError 报告运行错误。已登记会话的队列仍可排空，不能据此把整个运行判为 complete。运行错误诊断通过 onError(error, null) 及 stderr 上报，会话错误仍带实际 sessionId。

最终清单替换失败，即使各会话状态已经 sealed，close 仍拒绝；磁盘可能保留 recording、缺失、损坏或临时文件。不能保证失败状态本身一定可写。record 返回 true 仍只表示排队成功；flush 仍等待选中会话的检查点及其登记依赖，不封存运行。没有增加 fsync、断电可靠、进程总内存上限或实时一致快照保证。

## inspect 的判定

命令不变：

```powershell
npm.cmd run inspect -- --run 'runs/<runId>'
```

报告新增 `runManifest`：formatVersion、state、expectedSessionCount、outcome 和 reasons；sessions 保留原片段检查结果。清单中存在但文件全无的会话也进入 sessions，保留实际登记的 sessionId。

| 情况 | 整体判定 |
| --- | --- |
| 新格式清单 sealed，登记集合与文件一致，所有片段及其他原检查均通过 | complete / 0 |
| 新格式 sealed 清单缺少任一日志或状态文件，包括整对消失 | invalid / 1 |
| 发现未登记会话文件、重复 / 错误身份、非法哈希名、已知格式损坏 | invalid / 1 |
| 清单 failed 或存在确定的片段损坏 | invalid / 1 |
| 清单 recording，即使现有会话已 sealed | unverified / 2；确定损坏仍优先 invalid |
| 支持的运行版本中出现未来清单版本 | unverified / 2，不猜测成员结构 |
| sealed 空清单且没有任何片段 | 保留原来的 unverified / 2；runManifest 本身可 complete，表示空集合已结束 |

检查器只按已验证的哈希文件名访问成员，不采用清单提供的任意路径。正常片段仍重新核对原始字节、身份、计数、序号和 SHA-256。`runManifest.outcome=complete` 只描述清单闭合及成员对照，不代表每条日志内容或任务断言通过，仍须看整体 outcome 和三维评测结果。

## 历史兼容与评测边界

版本 1 运行元信息且没有清单字段时，保留原来的片段检查结果和退出码。已有 sealed 片段可以仍为 complete / 0，但新增 `runManifest.outcome=unverified`、expectedSessionCount=null 及“运行级会话覆盖未知”原因。真正缺状态的旧日志仍按原规则 unverified。

旧格式整对会话文件丢失仍无法检测，不能因为新 inspect 支持清单就宣称历史文件获得完整覆盖。版本 2 删除清单字段，或把版本 2 改成版本 1 却留下清单字段，均拒绝，不悄悄退回旧语义。清单、版本和日志被同时人为改写不在防篡改保证内。

Python 继续调用原 Node inspect：新运行整体 invalid / unverified 时不执行任务断言，结果 unevaluable；旧日志保持既有任务判断，覆盖局限保留在 recording.inspection.runManifest。无需改变 evidence / evaluation / experiment / comparisonReport 的持久化版本。浏览器已允许读取 run.json 版本 1 / 2，可在保存 JSON 中查看清单；浏览不会自动重新检查日志。

## 本地验证与后续

14 项新增 Node 检查先在旧实现失败，再在最终实现通过；完整 58 Node、137 Python（新增 3 项评测门禁）、32 文件 JS 语法、compileall、真实 Cordis / SessionStore 六事件以及三个真实输出子进程通过。输出子进程首次沙箱 spawn EPERM，获准环境重跑成功；没有用 mock 代替真实进程。

新格式双会话、整对 / 全部缺失、清单开放、旧格式五种合成验收分别得到 0 / 1 / 1 / 2 / 0，旧格式覆盖同时标明未知；基线旧 inspect 对新格式返回 1。两个历史实验的四个样本保持 passed / completed / complete / assertions passed，80 份原 JSON / JSONL 摘要不变。没有新模型调用或本批云端 CI 实测。

023 的历史验证结果保留。024 修复新增七项 Node 回归，旧实现六项失败、一项通过，修复后全部通过；完整 65 Node / 33 文件语法、35 离线评测 Python / 17 浏览 Python、获准环境完整 137 Python、真实组件与获准环境三个输出子进程通过。获准环境五轮各 600 个模拟小会话均 sealed / complete / 0；资源探针在 300 / 600 个全部因 maxPendingBytes=1 被拒的会话中，保留堆增量分别为 471976 / 887024 字节。这里只是指定输入和一次采样的观察，不是完整 benchmark，不把关闭用时作性能结论。

下一批 [M6.2](plans/m6-reliability-validation.md) 仍计划单条事件限制和更完整的资源测量。合并消除了待写完整快照的平方级积累，但内存成员表、会话队列和实际写入的完整快照仍随规模增长；成员分散到不同批次时仍反复重写完整集合，累计 I/O 仍可能呈平方级，不宣称进程总内存硬上限。
