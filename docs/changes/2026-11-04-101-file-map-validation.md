# 修改记录 101 虚拟文件路径与快照复验

日期为 2026 年 11 月 4 日（Asia/Shanghai）。类型为缺陷修复，插件版本为 0.1.2，尚未提交。

## 问题与目标

受控工具允许写入纯空白文件名，但用例无法声明同名的最终文件。含 NUL 的路径也能进入虚拟环境。离线评测仅检查快照文件名和内容是否为字符串。当快照同时包含文件 `a` 与 `a/b` 且摘要匹配时，评测器会执行内容断言，把无效证据计为任务失败。

## 文件修改与实现

- [formats.py](../../dsh_eval/formats.py) 提供共用的文件路径和文件映射校验。初始文件与最终状态期望都在用例预检时检查路径、文本类型和文件与父目录的冲突。
- [environment.py](../../dsh_eval/environment.py) 在操作虚拟文件前使用同一路径规则。保留根目录 `.` 的原有工具语义，写入时继续按当前文件集合检查父子冲突。合法路径按原样使用。
- [evaluate.py](../../dsh_eval/evaluate.py) 在摘要、身份、策略和完成状态通过核对后校验快照文件映射。映射无效时保留录制判定，任务归为 `unevaluable`。映射合法时继续按原断言比较实际与期望内容。
- [test_stateful_writes.py](../../test/test_stateful_writes.py) 增加跨入口路径反例、保留中文及空格的正例，以及快照摘要已重新计算时的离线回归。

## 验证

Windows 本地验证。修复前，对新增用例分别以 unittest discover 的 `-k agree_on_file_paths` 和 `-k impossible_file_map` 筛选执行。前者复现两次非法写入成功，后者复现四种非法映射被归为 `failed`。

| 命令或输入 | 结果 |
| --- | --- |
| `python -m unittest discover -s test -p test_stateful_writes.py` | 15 项通过，覆盖写入、快照、合成录制及续跑报告 |
| `python -m unittest discover -s test` | 首轮运行 466 项，四项进程回收及一组 Web 夹具初始化因环境限制报错。在可创建与回收子进程的环境中完整复验，485 项全部通过，耗时 303.054 秒 |
| 对 `fixtures/evaluation` 下全部 `*.case.json` 调用 `validate_case(load_json(path))` | 20 份公开用例通过 |
| `python -m compileall -q dsh_eval test` | 通过 |
| `python -m scripts.smoke_bridge --mutations` | 首次因 Node fork 返回 EPERM 未启动；在允许真实子进程的环境复验，工具注册和 IPC 的 15 个请求通过，modelCalled=false |
| 对 097、099 的八个任务使用各自冻结的 `case.json` 和 `evidence.json` 调用 `evaluate` | 每项 caseRunId、live 来源、执行、录制、断言及总判定与原归档一致，六项 passed、两项 failed |

## 限制与后续

快照结构检查验证的是受控文件映射的合法性，摘要核对沿用既有机制。历史归档若含本次拒绝的路径，重新评测时适用新规则。八项历史复验使用已有模型轨迹，本轮新增模型任务为零。

## 文档同步

更新 [评测格式](../evaluation-format.md)、[状态化工具](../stateful-tools.md)、[开发进度](../progress.md) 和 [修改索引](../../CHANGELOG.md)。含本记录在内的五份文档共 344 个相对文件链接目标均存在。
