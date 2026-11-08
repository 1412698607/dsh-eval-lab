# 修改记录 102 文件映射复查与目录枚举

日期为 2026 年 11 月 4 日（Asia/Shanghai）。类型为缺陷修复与回归测试，插件版本为 0.1.2。起始提交为 `f42047d`。

## 问题与目标

[101](2026-11-04-101-file-map-validation.md) 统一文件路径校验后，虚拟写入仍接受 `"   /leaf.txt"`，但对其父目录调用 `eval_list("   ")` 会得到 `INVALID_PATH`。复查用例重现了该回归。

## 文件修改与取舍

[路径校验](../../dsh_eval/formats.py) 区分文件与目录参数，[受控环境](../../dsh_eval/environment.py) 仅在 list 操作中选择目录规则。文件路径整体必须含非空白字符。目录允许保留空格，仍拒绝空路径、NUL 和非法路径分量。参数保留原文，以便按虚拟文件的同名目录查找。

[环境回归](../../test/test_environment.py) 在同一环境先写入合法嵌套文件，再按其父目录原名枚举，同时检查非法目录参数。最终快照仍逐个校验完整文件路径和父子冲突。

## 验证

- 修复前以 `python -m unittest discover -s test -p test_environment.py -k whitespace_directory` 重现列表结果为 `INVALID_PATH`。修复后环境、写入和变更三个模块分别通过 8、15、14 项。复验命令为 `python -m unittest discover -s test -p <模块文件名>`，文件名分别为 `test_environment.py`、`test_stateful_writes.py` 和 `test_stateful_mutations.py`。
- `python -m compileall -q dsh_eval test` 通过。复查 101 时另对 20 份公开用例完成预检，对 097、099 八份既有模型归档重新评测，执行、录制、断言与总判定均保持（六通过、两失败）。

## 限制与文档同步

本次验证针对内存虚拟工具和离线证据，未新增模型任务。完整本地回归的历史范围见 101，远端结果按实际提交独立核验。已更新[状态化工具说明](../stateful-tools.md)、[进度](../progress.md)和[修改索引](../../CHANGELOG.md)。
