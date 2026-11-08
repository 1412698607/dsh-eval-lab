# 修改记录 109 单文件重命名真实模型验收

2026 年 11 月 4 日（Asia/Shanghai），插件版本 0.1.2。运行基线为 `b3bc3fa` 加工作区中的 [108 实现](2026-11-04-108-stateful-rename.md)。本次只运行一个真实任务。

## 输入与判定

使用公开的 [rename-no-overwrite](../../fixtures/evaluation/rename-no-overwrite.case.json)，配置为 deepseek-official / deepseek-flash，headless，任务期限 120 秒。运行前校验用例和 Windows 输出路径，原始用例文件 SHA-256 为 `1df83d12107558adaccb020993b9c2bafe96ab6ca36932349fd08de2c3048ca3`。归档的用例对象与公开输入相等。

运行命令为 `python -m dsh_eval --case fixtures/evaluation/rename-no-overwrite.case.json --run --runs-root runs/rename-109`。caseRunId 为 `20f69dbb-6f65-4d56-8b87-3c5cce3d06cb`，runId 为 `96ec7719-c48e-4a76-a1a9-abc3f2b50647`。命令退出 1，执行 completed，录制 complete，评测 failed，source 为 live。七条断言中六条通过。唯一失败项为 `answer`，期望精确文本 `done`，轨迹中最后的助手文本为 `Done.`。

## 工具顺序与状态

独立读取封存轨迹的 51 条事件。逐条核对 runId、sessionId、六个唯一 callId 及对应结果的 toolCallId，按 seq 检查每项结果先于下一次调用，并核对实际参数、错误标记和精确文本。请求头中的模型与 provider 匹配输入。

| 调用 / 结果 seq | 工具与参数 | 结果 |
| --- | --- | --- |
| 17 / 18 | eval_read，draft.txt | 成功，`"评测\r\n"` |
| 19 / 20 | eval_read，guard.txt | 成功，`"keep\n"` |
| 25 / 26 | eval_rename，draft.txt → guard.txt | 错误，`Error: TARGET_EXISTS: guard.txt` |
| 31 / 32 | glob，模式 `**/*` | 成功，`No files found` |
| 37 / 38 | eval_rename，draft.txt → archive/final.txt | 成功，`RENAMED: draft.txt -> archive/final.txt` |
| 43 / 44 | eval_read，archive/final.txt | 成功，`"评测\r\n"` |

表中带引号的内容按 JSON 转义展示。用例限定两次重命名及相对顺序，允许其他调用。模型还进行了表中所列的两次预读和一次宿主 glob。最终快照标记为 complete=true，包含以下两个文件。

```json
{"guard.txt":"keep\n","archive/final.txt":"评测\r\n"}
```

核对了初始环境摘要、快照的三个运行身份、完整文件映射，以及 evidence 保存的快照 SHA-256 `ba6922e21578ee69d38e687043140b11a3b4d955971560318fc319269542f9f1`。旧路径已消失，保护文件和目标正文均逐字符匹配，专用宿主 workspace 为空。

## 独立复验与验证边界

- 新进程运行 `python -m dsh_eval --case <任务目录>/case.json --evidence <任务目录>/evidence.json --output <独立复验文件>`，退出 1。除 evaluatedAt 外，整个输出与原 evaluation 相等。复验前后对任务目录顶层文件和 traces 内文件共 16 份计算 SHA-256，摘要一致。
- 第二次独立复核从相同冻结输入、原始 JSONL 和 runtime 快照检查六组调用及最终文本，再以独立进程评测。源文件摘要保持，两次复验和原评测除时间外完全一致。
- host 记录专用子进程已退出、退出码 0。监督器无干预、无强停和协议错误，stdin writer 已结束。实际查询时原 CLI PID 4368 已不存在。
- 已结算模型事件 6 个，工具调用 6 次，totalTokens 为 46358，cost 缺失。此结果仅描述一个固定配置和用例。保留失败样本和原始严格断言，未追加模型任务。

同步 [M6 计划](../plans/m6-reliability-validation.md)、[进度](../progress.md)、[公开用例目录](../../fixtures/evaluation/README.md)、[工具说明](../stateful-tools.md)、[README](../../README.md) 与 [修改索引](../../CHANGELOG.md)。原始轨迹与本机运行资料保存在忽略目录。
