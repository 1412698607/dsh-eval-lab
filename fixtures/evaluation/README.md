# 公开离线评测样例

read-project / missing-file 的 case 与 events 文件是人工合成数据，没有调用模型或执行真实文件工具。新增的 live-read.case.json 是可交给真实运行入口的初始用例，文件本身不是已执行证据。

- `read-project.case.json` / `read-project.events.json`：输入要求读取 README 中的 projectName，包含关联的成功工具结果和最终文本。
- `missing-file.case.json` / `missing-file.events.json`：输入允许报告文件缺失，包含 isError 工具结果和预期响应。工具错误在该用例中是任务证据。
- `live-read.case.json`：M3.2 真实 read 的 file_path 参数与项目名称断言；`python -m dsh_eval --case fixtures/evaluation/live-read.case.json --run` 会创建独立文件环境并调用真实模型，不参与合成 demo。

在项目根目录执行 `npm.cmd run demo:eval`，原有 JavaScript 记录器会把两组事件写到被忽略的 `runs/eval-demo/<demo-id>/<runId>/`，生成真实录制格式的 run / JSONL / status，以及独立用例执行编号的 `evidence.json`。它只生成离线证据，不准备或执行用例环境，也不是批次任务调度器。

再对输出中每一组 casePath / evidencePath 执行 `python -m dsh_eval --case <casePath> --evidence <evidencePath>`。完整格式、结果与边界见 [评测格式](../../docs/evaluation-format.md)。

M3.3 新增 `stale-path.case.json` / `retry-read.case.json`：版本 2 的虚拟文件环境，分别验证旧路径失败后发现新文件、同路径暂时失败后重试。使用 `--run` 会调用真实模型；JSON 用例本身不是执行证据，也不参与合成 demo。工具及协议见 [状态化工具](../../docs/stateful-tools.md)。

2026 年 10 月 18 日审查修复：stale-path 的发现断言使用版本 2 空 `arguments`，仅要求正确的 eval_list 成功结果包含目标路径，因此允许 `.` 和 `docs` 两种查找；其余旧路径失败、实际读取与答案断言保持。说明与合成回归见 [修复记录 014](../../docs/changes/2026-10-18-014-m3-3-review-fixes.md)。

M3.4 的 `recovery.batch.json` 是真实执行清单，顺序包含 stale-path、retry-first、retry-reset；后两项显式引用同一 retry-read 用例以检查重置。运行 `python -m dsh_eval --batch fixtures/evaluation/recovery.batch.json --run` 会调用真实模型三次。stale-path 任务已明确实际尝试 README 引用后再选替代文件，避免答案正确但缺少目标故障证据。说明见 [批次运行](../../docs/batch-runner.md)。

M4.1 的 `recovery.experiment.json` 显式声明一个用例、一个配置、两次重复，共两个真实模型任务。运行 `python -m dsh_eval --experiment fixtures/evaluation/recovery.experiment.json --run` 会调用模型；清单本身不是执行证据，也不参与合成 demo。重复状态、样本关联和统计口径见 [重复试验](../../docs/experiments.md)。

M6.3 的 [core 目录](core/README.md) 提供 10 个固定版本 2 用例及单配置、单轮实验清单，覆盖读取、发现、引用、缺失 / 空文件、中文与故障恢复。无模型验收加入正常 Python 测试；真实运行必须显式选择 `--experiment fixtures/evaluation/core/core.experiment.json --run`，共 10 次计划任务，不自动参与 demo 或 CI。验收结果与边界见 [固定评测集](../../docs/core-evaluation.md)。
