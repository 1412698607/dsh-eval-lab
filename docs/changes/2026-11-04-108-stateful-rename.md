# 修改记录 108 受控单文件重命名

日期为 2026 年 11 月 4 日（Asia/Shanghai）。插件版本为 0.1.2，基线为 `b3bc3fa`，本批尚未提交。

## 目标与技术取舍

评测 Agent 整理文件时，需要区分“改名成功”和“覆盖已有内容”。新增可选工具 `eval_rename`。保留现有文件和目录时，冲突后的第二次尝试才能用于验证 Agent 是否选用了可用目标。源和目标完全相同时也按目标占用处理。

## 实现与文件

- [格式校验](../../dsh_eval/formats.py)允许版本 2 stateful 显式选择工具。[工具注册](../../scripts/lib/tool-bridge.js)声明 path 和 destination 两个必填字符串。默认工具集合保持 read / list。
- [虚拟环境](../../dsh_eval/environment.py)在提交操作时检查源、目标和父子冲突。源文件的删除与目标文件的创建同步完成，复用现有请求缓存、取消、超时和文件快照。排队中的改名会看到先于它提交的其他文件操作。
- [公开用例](../../fixtures/evaluation/rename-no-overwrite.case.json)、[合成适配器](../../scripts/fixtures/mutation-adapter.js)和[回归测试](../../test/test_stateful_mutations.py)覆盖目标占用后的移动、精确读回、旧路径移除与保护文件。另测重复请求、权限、无效路径、超时及取消。
- [Python 组件检查](../../scripts/smoke_bridge.py)与 [Node 组件检查](../../scripts/smoke-bridge.js)新增 rename 场景，使用实际 Cordis 注册和 IPC。

## 验证

| 命令 | 结果 |
| --- | --- |
| `python -m unittest discover -s test -p test_stateful_mutations.py` 及同命令的 `test_stateful_writes.py` | 分别通过 17、15 项。新增公开用例使用脚本驱动，经子进程录制和离线评测，七条断言通过 |
| `python -m scripts.smoke_bridge --rename` | 五请求全部通过，modelCalled=false |
| `python -m unittest discover -s test` | 本地完整 491 项 Python 测试通过，耗时 303.565 秒 |
| `npm.cmd run check`、`npm.cmd test`、`python -m compileall -q dsh_eval scripts test` | 45 个 JS 文件语法检查、123 项 Node 测试及 Python 编译检查通过 |

## 边界与后续

本次覆盖单个内存文件的移动以及失败后的状态。尚无此新用例的真实模型任务。下一项独立验收可用同一公开用例运行一个真实任务，核对录制中的错误呈现、工具顺序和最终快照。

已同步 README、用例目录、架构、评测格式、状态化工具说明、M6 计划、开发进度和 CHANGELOG。21 份公开用例均通过格式校验，10 份变动文档的 594 个相对文件链接目标存在。
