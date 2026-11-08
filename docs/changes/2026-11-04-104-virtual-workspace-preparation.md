# 修改记录 104 虚拟初始文件准备

日期为 2026 年 11 月 4 日（Asia/Shanghai）。类型为缺陷修复，插件版本为 0.1.2。实现基线为 `0b63cce`，本批尚未提交。

## 问题与目标

[102](2026-11-04-102-file-map-review.md) 验证了虚拟工具可以创建并列出 `"   /leaf.txt"`。将同一路径直接声明在初始文件映射时，用例格式校验通过，但 runner 在准备 workspace 时会抛出 `Unsupported fixture filename`。合法的虚拟输入因此无法进入工具执行阶段。

## 文件修改与技术取舍

- [runner.py](../../dsh_eval/runner.py) 在用例校验之后，根据 `environment.stateful` 区分准备方式。虚拟环境只创建专用空 workspace，文件名和内容保存在内存。实际写盘的环境仍先检查 Windows 名称、大小写和文件目录冲突，通过后才创建目录、写入文件。
- [test_environment.py](../../test/test_environment.py) 回归纯空白父目录、大小写不同的文件、仅大小写不同的文件与父目录以及保留名。检查空目录、重复准备拒绝复用、逐个按原名读取及目录枚举。原有磁盘用例继续覆盖冲突时未创建 workspace。
- 用例和快照沿用 101 的相对路径与文件映射规则。此处分支只决定如何准备宿主 workspace，文件格式、启动命令与快照摘要算法保持原样。

## 验证

| 命令或输入 | 结果 |
| --- | --- |
| `python -m unittest discover -s test -p test_environment.py -k virtual_initial_files` | 修复前在准备阶段复现 `Unsupported fixture filename` |
| `python -m unittest discover -s test -p test_environment.py`、`python -m unittest discover -s test -p test_runner.py -k WorkspaceTests`、`python -m unittest discover -s test -p test_stateful_writes.py` | 修复后分别通过 9、5、15 项，覆盖状态化环境和实际磁盘两条准备路径 |
| `python -m compileall -q dsh_eval scripts test`，对公开 `*.case.json` 执行 `validate_case` | 编译检查通过，20 份用例格式校验通过 |
| `python -m unittest discover -s test` | Windows 环境中完整 487 项 Python 测试通过，耗时 294.896 秒 |
| 在 [write-retry](../../fixtures/evaluation/write-retry.case.json) 的初始和期望映射中增加六个虚拟文件，使用 [write-adapter.js](../../scripts/fixtures/write-adapter.js) 执行 `run_case`，再以合成来源调用 `evaluate` | completed / complete / passed，七条断言通过。八文件快照等于期望映射，宿主 workspace 为空，离线复验断言一致 |

合成检查使用 `"   /leaf.txt"`、`A`、`a`、`CON.txt`、`DIR`、`dir/child` 作为六个不同文件，配置为 synthetic / none。首次写入延迟 300 ms，工具期限 100 ms，重试延迟为 0。复用真实子进程、管道及 recorder，替换宿主安装准备和模型适配器。新增真实模型任务为零。

## 文档同步与限制

更新[单用例运行说明](../single-case-runner.md)、[评测格式](../evaluation-format.md)、[状态化工具](../stateful-tools.md)、[进度](../progress.md)及[修改索引](../../CHANGELOG.md)。无模型验证覆盖当前 Windows 环境。本次的虚拟路径可以用于内存操作，若要将同名文件落盘，普通用例仍须通过宿主文件名检查。
