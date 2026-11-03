# 修改记录 106 普通工作区文件名控制字符检查

日期为 2026 年 11 月 4 日（Asia/Shanghai）。类型为缺陷修复，插件版本为 0.1.2。基线为 `acf3a0a`，本批尚未提交。

## 问题与目标

在 Windows 上，为普通用例依次声明 `first.txt` 和含制表符的文件名。调用 `prepare_workspace` 时，旧实现创建了 workspace 并写出第一个文件，直到打开第二个文件时才抛出 OSError。文件名检查漏掉了 U+0001 至 U+001F，这些字符在 JSON 中可由转义序列传入。

## 实现与取舍

[runner.py](../../dsh_eval/runner.py) 在已有的落盘名称检查中逐字符检查每个路径分量。完成全部路径检查后，再创建 workspace 并写入初始文件。该规则限定在普通文件用例的准备阶段，文件正文和内存虚拟路径继续按各自的规则处理。NUL 已在输入格式层拒绝。

[工作区回归](../../test/test_runner.py) 将有效文件放在首位，对 31 个控制字符分别测试文件名和父目录名，每次均要求报出名称错误且 workspace 不存在。[虚拟环境回归](../../test/test_environment.py) 增加带制表符的内存文件，核对原名和读回值。

## 验证

| 命令或输入 | 结果 |
| --- | --- |
| 修复前用临时目录、有效首文件和含制表符的第二个文件调用 `prepare_workspace` | 复现 OSError，workspace 和首文件均已存在 |
| `python -m unittest discover -s test -p test_runner.py -k WorkspaceTests` 和 `python -m unittest discover -s test -p test_environment.py` | 6 项工作区和 9 项虚拟环境测试通过，含 62 组磁盘路径反例 |
| `python -m compileall -q dsh_eval scripts test` | 通过 |
| `python -m unittest discover -s test` | Windows 本地完整 488 项 Python 测试通过，耗时 320.431 秒 |
| 对公开 `*.case.json` 执行 `validate_case` 并检查本轮改动文档的相对文件链接 | 20 份用例有效，5 份文档中的 326 个相对链接目标均存在 |
| `python -m dsh_eval --case <input.json> --run --runs-root <短临时目录>` | 退出 2，runtime_error / unevaluable。runtime 保存 workspace 阶段及 Unsupported fixture filename，workspace 未创建，安装准备与适配器均未启动 |

CLI 复验输入由 [live-read](../../fixtures/evaluation/live-read.case.json) 复制，将 files 替换为 JSON 对象 `{"first.txt":"keep","bad\tname.txt":"invalid"}`。本批没有模型调用。

## 限制与文档同步

此次修正针对能从输入名称预先确定的错误。其他磁盘 I/O 故障仍按 runner 的运行错误处理。已同步[单用例说明](../single-case-runner.md)、[进度](../progress.md)和[修改索引](../../CHANGELOG.md)。
