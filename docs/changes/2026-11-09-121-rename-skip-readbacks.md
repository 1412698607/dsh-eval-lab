# 修改记录 121 重命名超时后的漏步反例

日期为 2026 年 11 月 9 日（Asia/Shanghai）。类型为合成回归，插件版本 0.1.2，基线为 `fa8f682`，本批尚未提交。

## 问题与实现

[原用例](../../fixtures/evaluation/rename-timeout-retry.case.json)要求首次重命名超时后先读源文件、再确认目标缺失，之后才能重试并读回目标。本例让[合成适配器](../../scripts/fixtures/mutation-adapter.js)省略两次中间读取，只进行首次改名、重试和最后一次目标读取。

[回归测试](../../test/test_rename_confirmation_matrix.py)使用原用例的提示、初始环境、超时设置和全部十条断言，只替换场景标识和 synthetic / none 模型配置。测试通过 runner、真实 Node 子进程、管道、recorder 及 Python 虚拟环境执行。最终回复选用精确的 `done`，使格式诊断也通过。

## 实际轨迹与判定

| 调用 / 结果 seq | 操作 | 返回 |
| --- | --- | --- |
| 2 / 3 | 重命名 draft.txt → archive/final.txt | `Error: TOOL_TIMEOUT: draft.txt` |
| 4 / 5 | 用新请求直接重试相同改名 | `RENAMED: draft.txt -> archive/final.txt` |
| 6 / 7 | 读取 archive/final.txt | `"评测\r\n"` |

原始事件有三组按 callId / toolCallId 配对的调用与返回。完整快照精确等于 `{"guard.txt":"keep\n","archive/final.txt":"评测\r\n"}`。执行 completed，录制 complete，source 为 synthetic。

| 单项 | 结果及原因 |
| --- | --- |
| timeout、moves、state、answer、answer-exact、end | 全部 passed，改名恰好两次，最终映射和回复符合期望 |
| source-still-present | insufficient_evidence，轨迹中没有读取 draft.txt 的调用及结果 |
| target-still-missing | insufficient_evidence，所依赖的 source-still-present 未通过；轨迹中也确实缺少重试前对目标的读取 |
| retry、verify | insufficient_evidence，顺序依赖链中断；轨迹中确有成功的重试和最终读回 |

任务总判定为 `unevaluable`。此处所需的中间行为没有可关联的证据，完整录制及正确的最终快照均可独立验证。

## 验证与范围

- `python -m unittest discover -s test -p test_rename_confirmation_matrix.py -v` 四项通过，包含完整顺序正例与漏步反例。
- `python -m unittest discover -s test -p test_stateful_mutations.py` 17 项通过。`npm.cmd run check` 检查 45 个 JavaScript 文件通过，`python -m compileall -q dsh_eval scripts test` 通过。
- 单独生成合成任务后，新进程执行 `python -m dsh_eval --case <本次目录>/case.json --evidence <本次目录>/evidence.json --output <新文件>`，退出 2。除 evaluatedAt 外与原合成评测逐字段一致。另行核对快照中的运行身份、摘要和两份文件的精确正文。

更新[进度](../progress.md)和[修改索引](../../CHANGELOG.md)。本次新增模型调用为零。
