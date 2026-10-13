# 修改记录 006 M2.2 录制状态与离线检查

日期：2026 年 10 月 12 日，Asia/Shanghai。类型：功能 / 修复 / 测试 / 文档。插件版本：`0.1.2`。相关 Git 提交：本批尚未提交；已核实开发基线为 `f92733b`。开发分支：`20261012/feat/m2-reliable-recording`。

## 问题与目标

M2.1 只有进程内错误状态。JSONL 存在不能证明排队事件全部写完，flush 也不表示不再追加；离线消费者无法确认录制片段是否正常结束。待写队列没有字节上限。

本批按 M2 方案增加独立会话状态、内容一致性校验、容量保护及显式目录检查入口。只完成 M2.2，真实模型任务和实际 profile 安装留在 M2.3。

## 文件修改

| 文件 | 修改前 | 修改后 | 原因 |
| --- | --- | --- | --- |
| `src/recorder.js` | Promise 队列及进程内错误 | 接收/排队/写入计数、字节和摘要、检查点、封存及容量限制 | 为离线检查提供证据，过载显式失败 |
| `src/session-status.js` | 无 | 独立状态命名、同目录临时文件与 rename | 状态与宿主事件分开 |
| `src/inspect.js` | 无 | 流式解析、身份/序号/前缀/最终摘要校验 | 区分完整、损坏和未验证 |
| `scripts/inspect.js` | 无 | --run 参数、JSON 报告、退出码 0 / 1 / 2 | 避免自动选错运行批次 |
| `src/config.js` | 只解析路径 | 默认 16 MiB、正安全整数校验 | 显式配置待写容量 |
| `src/index.js` | 监听 dispose 事件 | ctx.effect 注册所属 fiber 的异步关闭清理 | 修复真实卸载没有执行关闭 |
| `scripts/lib/host-smoke.js` | 检查 flush 后事件 | 增加 recording / failed 状态及卸载后 inspect | 用持久化证据验证生命周期 |
| `scripts/check-output.js`、`scripts/fixtures/output-child.js` | 两种输出场景 | 增加 inspect 结果及未关闭直接退出场景 | 验证独立进程的 0 / 1 / 2 结果 |
| `test/integrity.test.js` | 无 | 17 项完整性与异常边界测试 | 覆盖竞态、过载、损坏、旧格式和流式边界 |
| `test/config.test.js`、`test/recorder.test.js` | 旧配置与简化生命周期 | 增加容量配置用例，使用 effect 清理 | 与真实接口一致 |
| `package.json` | 0.1.1 | 0.1.2，新增 inspect 脚本 | 标识本批能力 |
| README、进度、架构、M2 方案、CHANGELOG | M2.2 待开发 | 当前实现、命令、边界和验证依据 | 文档与代码同步 |

## 实现与技术取舍

会话 JSONL 仍为 formatVersion 1、captureScope 为 live-events-only。状态新增独立 statusFormatVersion 1，包含 runId / sessionId / traceFile、状态、receivedCount / acceptedCount / writtenCount、writtenBytes、首尾序号及 SHA-256。received 包括触发失败的接收尝试，失败后拒绝不再累计；accepted 仅指成功入队。

首条会话写入前初始化 recording 状态。事件在接收路径同步序列化为 UTF-8 Buffer，检查序列化后的 seq 是严格递增非负安全整数，再计入全录制器待写字节。追加成功更新计数和增量哈希，完成或跳过时释放容量。超限只使受影响会话失败，不静默丢弃后继续封存；其他会话仍可写入和封存。

flush 将状态任务插入选定队尾，并保存调用时的接收计数，使计数、字节和摘要属于同一个前缀；此后追加不在该检查点内。close 先停止接收，排空每个会话队列，正常会话保存 sealed；失败会话尽力保存 failed，整体仍拒绝。重复关闭共享 Promise，关闭后 flush 不会回写 recording。

采用独立 status 而非在 Harness 事件中混入内部记录；状态替换用同目录临时文件和 rename。状态写失败会使录制失败；failed 本身可能无法写入，所以缺失、旧 recording 或损坏状态均不能接受为完整。保留 JSONL 与 JavaScript 结构，无新增依赖、数据库或语言迁移。

inspect 按原始字节逐行读取与计算摘要，严格解码 UTF-8，核对运行与会话身份、哈希文件名、计数、字节、序号及摘要。sealed 比较全部字节；recording / failed 比较已保存前缀。序号缺口允许存在并报告，不补历史。未知事件类型可读；缺口详情最多 100 项，另报完整数量。旧日志缺状态和未知状态版本只报告未验证。

### 2026 年 10 月 12 日对历史生命周期判断的修正

新增卸载后 inspect 断言首次在真实组件下失败：fiber.dispose 完成后状态仍为 recording。核对本机固定版本 Cordis 源码与类型声明后，确认旧 ctx.on("dispose") 没有由该卸载流程触发；普通函数 apply 还可能按构造函数执行，直接返回清理函数也不能覆盖该路径。最终显式使用 ctx.effect 注册清理，并在真实组件卸载后验证 sealed。

旧组件检查证明 flush 后 6 条事件原样导出，不能据此声称真实卸载执行了 recorder.close。修改记录 001 / 004 和既有历史结果保持原文，本记录说明新增复验证据及判断修正。Cordis 捕获清理错误的边界仍成立；dispose 完成仍不能代替 inspect。

## 验证

运行环境：Windows、Node.js v24.14.0、npm 11.9.0；真实组件 dsh-session 0.2.0-rc.2 / Cordis 4.0.4。执行日期均为 2026 年 10 月 12 日。

| 命令或操作 | 结果 | 证明的范围 |
| --- | --- | --- |
| 测试先行：加入完整性测试后执行 `npm.cmd test` | 首次因 inspect 模块尚未实现失败 | 保留待实现功能的失败起点，不作为通过结果 |
| `npm.cmd run check` | 退出码 0，18 文件 | 语法检查 |
| `npm.cmd test` | 36 通过，0 失败、0 跳过 | 原 18 项 + 容量配置 1 项 + 完整性 17 项 |
| `npm.cmd run demo` | 退出码 0，8 条模拟事件 | 无模型调用 |
| `npm.cmd run inspect -- --run 'runs/b0a3e7e4-df5a-43cc-bec6-2087dc028c48'` | complete / 0，8 条、2073 字节、seq 0–7 | 本次模拟输出封存与摘要一致 |
| `npm.cmd run smoke:host` | 首次增加封存断言后失败；修复 effect 后退出码 0，6 条 | 真实组件加载、原始事件、flush 与卸载封存，不代表真实模型任务 |
| `npm.cmd run check:output`（沙箱内） | spawn EPERM，未完成 | 无法捕获真实子进程，不以 mock 代替 |
| 同命令获准在沙箱外执行 | 退出码 0，三个场景通过 | normal inspect=0；write-error inspect=1；abrupt-exit inspect=2。子进程 stdout 均为空；前两种 stderr 诊断匹配 |
| 本地 Markdown 链接检查 | 13 份公开、2 份私人 Markdown，35 个本地链接有效 | 公开链接不指向私人材料、运行输出或依赖缓存 |
| `git diff --check`、跟踪及忽略规则核对 | 通过；main.py 仍跟踪；私人目录及运行输出被忽略且未跟踪 | 不自动添加日志、私人文件或删除已有代码 |

完整性测试覆盖检查点后追加、交错 flush/close、重复关闭、其他会话封存、UTF-8 精确容量边界及跳过后的释放、真实追加失败、初始化/检查点/封存状态替换失败、序列化与序号失败、截断/空文件/损坏/额外内容、元信息与身份、旧日志、开放前缀及跨流分块中文长行。

本次通过的组件批次为 `runs/host-smoke/d3188c8d-caca-4d81-98de-8a2e832adfa1/79e29e71-d057-4bc5-b2ec-ae7f328ebaf0/`；子进程批次为 `runs/output-check/cecb5448-e719-420c-9cbe-bc273af1067c/`。这些被忽略的本机输出不是可分发固定夹具；复现请运行脚本获取新目录，并对新目录执行 inspect。

## 风险与后续

- sealed 描述观察到的新增片段，不代表整个历史、任务成功或断电可靠。没有 fsync、修复或确定性重放。
- SHA-256 无签名保护；日志与摘要同时改写、删除整对会话文件无法保证检测，没有运行级会话清单。
- inspect 不提供在线一致快照；请检查停止写入后的目录或稳定副本。单行很大仍占用该行内存。
- 容量上限只约束待写文本，不涵盖临时序列化、会话状态和系统缓存；轮转、淘汰及性能基准后续按需求开发。
- 状态替换只在当前 Windows 本地文件系统验证，不推定所有文件占用或网络盘行为。
- abrupt-exit 使用专用录制器子进程 flush 后 process.exit(0)，未验证操作系统强杀或断电；未终止用户宿主。
- 下一批 M2.3：实际 profile、受控真实模型任务、Web/headless 正常退出、取消及强制停止的分别验证。本批未安装 profile、未调用模型、未提交或推送。

## 面试讨论点

可以演示 record 成功仅为入队、flush 保存前缀而 close 才封存、容量为什么按 UTF-8 字节计数，以及为什么真实组件检查暴露了简化上下文测试漏掉的清理接口问题。把录制 complete 与任务 passed 分开；不填写未测量的性能、成功率或费用改善。

## 文档同步

已同步 README、docs/progress.md、docs/architecture.md、M2 方案、CHANGELOG，以及本地存在的私人准备和交接材料；公开文档不依赖私人文件。按用户指定的 Karpathy Guidelines 限定 M2.2 范围，以失败测试、真实组件复现和实际结果收敛实现。
