# 公开离线评测样例

read-project / missing-file 的 case 与 events 文件是人工合成数据，没有调用模型或执行真实文件工具。新增的 live-read.case.json 是可交给真实运行入口的初始用例，文件本身不是已执行证据。

- `read-project.case.json` / `read-project.events.json`：输入要求读取 README 中的 projectName，包含关联的成功工具结果和最终文本。
- `missing-file.case.json` / `missing-file.events.json`：输入允许报告文件缺失，包含 isError 工具结果和预期响应。工具错误在该用例中是任务证据。
- `live-read.case.json`：M3.2 真实 read 的 file_path 参数与项目名称断言；`python -m dsh_eval --case fixtures/evaluation/live-read.case.json --run` 会创建独立文件环境并调用真实模型，不参与合成 demo。

在项目根目录执行 `npm.cmd run demo:eval`，原有 JavaScript 记录器会把两组事件写到被忽略的 `runs/eval-demo/<demo-id>/<runId>/`，生成真实录制格式的 run / JSONL / status，以及独立用例执行编号的 `evidence.json`。它只生成离线证据，不准备或执行用例环境，也不是批次任务调度器。

再对输出中每一组 casePath / evidencePath 执行 `python -m dsh_eval --case <casePath> --evidence <evidencePath>`。完整格式、结果与边界见 [评测格式](../../docs/evaluation-format.md)。
