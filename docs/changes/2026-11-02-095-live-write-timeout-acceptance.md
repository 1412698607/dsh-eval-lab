# 修改记录 095 写入与工具超时真实模型验收

日期：2026 年 11 月 2 日，Asia/Shanghai。类型：真实验收 / 文档。插件版本：0.1.2。相关 Git 提交：尚未提交；HEAD 为已核实的 8129678，运行使用工作区中的 094 实现。本批不改生产代码、测试、公共用例或断言。

## 问题与目标

094 已实现受控虚拟写入、工具期限、最终状态证据，并完成合成与真实组件无模型验证。本批用公开 write-retry 用例执行一个真实模型任务，检查模型收到工具超时后能否重试，以及实际工具结果、最终文件状态和离线证据是否一致。另补齐最终短期限唤醒版本的完整 Python 回归，不将 094 的旧全量数量作为最终代码全量结果。

## 文件修改

| 文件 | 修改前 | 修改后 | 原因 |
| --- | --- | --- | --- |
| README、stateful-tools、single-case-runner、fixtures/evaluation/README | 写入能力仅有无模型验证 | 链接单任务真实验收及边界 | 区分已实现、组件验证和模型任务证据 |
| progress、M6 方案、CHANGELOG、本记录 | 无本批真实样本及最终全量记录 | 记录实际任务、独立复验和验证范围 | 保留 094 原验证历史 |

## 输入与技术取舍

- 使用 [write-retry.case.json](../../fixtures/evaluation/write-retry.case.json) 原样运行，无提示、环境、配置或断言变更。运行快照与公开输入相等。
- 配置 deepseek-official / deepseek-flash，任务数为 1；timeoutSeconds=120，默认工具期限 5000 ms，eval_write 覆盖为 1000 ms，首次写入延迟 1500 ms、第二次零延迟。准备与清理另有期限，不将任务数或墙钟预算说成 token / 费用硬上限。
- 使用通过 Windows 路径预检的项目内忽略目录 `runs/write-acceptance/<caseRunId>`，新建独立 profile、workspace 和运行身份；宿主只引用现有凭据，不修改原 profile。
- 实际模型决策通过真实 Harness / Tools 与 Python 虚拟环境执行。工具延迟来自受控注入，不表示供应商、网络或真实磁盘自然发生超时；没有写入宿主业务文件。

## 真实任务结果

caseRunId：`4d740b7c-20e9-4e3c-b803-ccf876066938`；runId：`73d067a4-4ba1-457d-80fa-f8c9778d910a`。

环境为 Windows、Python 3.12.0、Node.js v24.14.0；本次 setup 实际记录 CLI / SessionStore 0.2.0-rc.2、Cordis 4.0.4。

| 检查项 | 实际结果 |
| --- | --- |
| 执行 / 录制 / 断言 / 总结论 | completed / complete / passed / passed，source=live |
| 首次写入 | callSeq=17、resultSeq=18，返回 TOOL_TIMEOUT |
| 重试写入 | callSeq=23、resultSeq=24，返回 WROTE: result.txt；满足 after 首次超时 |
| 读回 | callSeq=29、resultSeq=30，文本精确为 `done\n`；满足 after 重试成功 |
| 调用次数 | eval_write 恰好两次，共三次工具调用 |
| 最终完整文件映射 | result.txt 为 `done\n`、guard.txt 为 `keep\n`，没有额外文件；快照 complete=true |
| 最终回答与结束 | 回答精确为 done，turn/end completed；七条断言全部通过 |
| 录制 | 37 条事件、51356 字节、run 清单 sealed；实际 request/header 路由与输入配置匹配 |
| 已观测用量 | modelCalls=4、toolCalls=3、inputTokens=7485、outputTokens=217、totalTokens=30230、cost=null |
| 运行耗时 | elapsedSeconds 约 8.360 秒，含准备 / 执行 / 清理，不是纯模型延迟或整个验收流程耗时 |

modelCalls 是已结算录制事件，不等于任务数或供应商账单请求数。totalTokens 使用报告值，不用 inputTokens + outputTokens 补算；费用缺失不补零。该单任务只证明上述固定配置与场景，不推断总体模型表现、成功率、成本或性能改善。

## 验证

| 实际命令或操作 | 结果 | 证明的范围 |
| --- | --- | --- |
| `validate_live_case(load_json(...))`、`check_output_root(..., kind="case")`、`git check-ignore runs/write-acceptance` | 输入有效、路径通过、输出被忽略 | 不探测远端认证或模型表现 |
| `run_case(Path("fixtures/evaluation/write-retry.case.json"), Path("runs/write-acceptance"))` | 一项真实任务 passed；未追加任务 | 真实模型与受控工具链路 |
| 新进程 `python -m dsh_eval --case <本次目录>/case.json --evidence <本次目录>/evidence.json --output <新的复验文件>` | 退出 0，七断言通过；除复验时间外，身份、来源、配置、预算执行、三维结论、断言与指标无差异 | 原冻结输入和当前磁盘录制的独立离线复验，无模型调用 |
| 独立复验前后对选定文件计算 SHA-256 | 本次目录顶层文件及 traces 共 16 份摘要不变 | 不扫描 home / pnpm-store；新复验结果另存，不改原输出 |
| runtime / host / setup / run 清单核对 | 准备进程退出、childClosed=true、exitCode=0、forceStopped=false、adapterExitCode=0、stdinWriterStopped=true，无监督干预 / 协议错误 | 当前专用任务清理事实 |
| 操作系统核对本次 CLI PID 35680 | 验收时不存在 | 只限定本次已记录 PID，不推定任意外部进程树 |
| ArtifactBrowser 读取 evaluation 与 seq=18 | 最终状态卡片数据可读；超时结果定位至物理第 19 行 | 保存文件的读取层，没有新增实际页面点击验收 |

本轮对最终短期限唤醒代码执行 `npm.cmd run test:python`，在可创建 / 终止真实子进程的环境中完整 463 项通过，294.448 秒，零失败 / 错误。094 的历史 462 项全量及最终 13 / 17 项定向结果原样保留，不覆盖首次失败或把它们计为本轮结果。八份本轮文档的 451 个相对文件链接目标均存在，`git diff --check` 通过；运行目录已被忽略，Git 未跟踪 runs / private-notes。

复现真实执行可使用以下命令；它会创建新任务并调用配置中的模型，不复用本次运行身份：

```powershell
python -m dsh_eval --case fixtures/evaluation/write-retry.case.json --run --runs-root runs/write-acceptance
```

## 风险与后续

只新增一个配置、一个用例、一次真实任务；没有执行真实模型取消、删除、编辑、并发冲突、外部异步工具或跨平台验收。该任务没有在首次超时与重试之间额外读取中间文件状态；超时后未提交写入的细粒度验证仍来自 094 的组件 / 合成反例，不扩大本次轨迹观测范围。

本批未提交、推送或新增远端 CI。原始模型内容、运行输出、安装缓存及本机凭据引用保存在忽略目录，不加入公开仓库。后续真实任务另用新身份记录，不替换历史样本。

## 文档同步

更新当前功能、运行入口、状态化工具说明、用例目录、开发进度、M6 方案与 CHANGELOG。格式与架构未改动；094 修改记录保留当时的无模型范围及验证历史。
