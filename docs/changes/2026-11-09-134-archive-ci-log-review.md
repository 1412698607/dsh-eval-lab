# 修改记录 134 归档 CI 失败日志复核

日期：2026 年 11 月 9 日，Asia/Shanghai。类型：文档。插件版本：0.1.2。相关已核实提交：`5c0cd21cea44983db4e27dc3999175fd6d353f56`、`3e0952748b88b508da98ea5771a43fcf615049d3`、`5b0546c3fc7abc164a8ace5c9ff222816a3274cf`。本记录在提交前形成，文档自身的提交与CI按后续新SHA独立核对。

## 问题与目标

[131](2026-11-09-131-archive-ci-and-capability-matrix.md)记录首次归档提交的Python步骤失败，但当时只有公开退出码，未取得具体堆栈。[132](2026-11-09-132-windows-short-temp-fixture.md)独立复现了真实短临时路径下的夹具缺陷，并修正测试根的规范化；[133](2026-11-09-133-archive-delivery-acceptance.md)确认新提交CI成功，仍保留旧失败原因待日志核对的范围。

本次取得对应作业日志并逐项复核，补齐失败原因与后续云端测试数量。原失败及131–133形成时的未知状态保留，不覆盖历史。

## 文件修改与核对方法

新增本记录，更新 CHANGELOG、开发进度的最新结论及能力矩阵的云端证据。生产代码与测试不变，架构和运行方式不变。

按仓库、run、job和attempt读取GitHub Actions日志，核对日志中的检出SHA、运行身份、测试汇总及堆栈；再与当前夹具 setUp、ArchivePaths 的规范根和前缀分支核对。子Agent独立读取同一旧作业日志并逐项复核，无未解释的失败项。本次只做日志 / 源码复核及文档检查，不新跑本地测试或模型任务。

## 旧失败的完整范围

提交 `5c0cd21` 的 run42593809914 / job129081523613 / attempt1：Python命令为 `python -m unittest discover -s test -p "test_*.py"`，实际632项 / 491.958秒，结果4失败、2错误，全部位于 `test_archive_paths.ArchivePathsTests`。[原作业](https://github.com/1412698607/dsh-eval-lab/actions/runs/42593809914/job/129081523613)

| 原用例后缀 | 日志结果 | 与夹具缺陷的对应关系 |
| --- | --- | --- |
| test_windows_logical_prefix_maps_to_listed_files_and_back_without_original_path | FAIL | 输出规范长根与夹具短根比较不等 |
| test_posix_original_paths_are_parsed_without_accessing_the_original_root | FAIL | 同一物理根两种拼写比较不等 |
| test_explicit_context_preserves_defaults_and_restores_after_errors | FAIL | 上下文映射结果与夹具路径拼写不等 |
| test_unlisted_relative_external_and_parent_references_never_fall_back_to_the_filesystem | FAIL | 短根不匹配规范payload前缀，recognizes返回False |
| test_required_hidden_claim_is_allowed_but_other_hidden_or_private_members_are_rejected | ERROR | claim短路径未匹配规范payload根，报outside the declared prefixes |
| test_already_physical_paths_win_when_the_source_prefix_contains_the_bundle | ERROR | 短路径只命中逻辑根，产生带bundle/payload的相对名，报not a listed member or directory |

前三项日志明确显示 `runneradmin` 与 `RUNNER~1` 的差异。ArchivePaths 在构造时规范化物理根，而旧夹具从未规范化的 TemporaryDirectory 名字派生预期路径；剩余三项也落在同一前缀差异上。六项与132实际短TMP复现对应，当前 setUp 的 `Path(temporary.name).resolve()` 在派生所有路径前统一根，解释并覆盖本次日志中的全部失败。无需放宽成员、原路径不回退或链接校验；不据此推广为任意外部短路径输入兼容能力。

## 修正后作业的实际日志

三个作业均为当前开发分支push、attempt1。已核对的成功作业各14步全部completed / success；日志环境均为Windows Server2025、Node.js v24.22.2、CPython3.12.10，与本地Windows / Node v24.14.0 / Python3.12.0的结果分开记录。

| 已检出提交 | run / job | Python日志 | Node与语法日志 |
| --- | --- | --- | --- |
| 3e0952748b88b508da98ea5771a43fcf615049d3 | 42596591126 / 129090609599 | 633项 / 510.040秒，OK | 154通过、0失败 / 取消 / 跳过，45个JS文件语法通过 |
| 5b0546c3fc7abc164a8ace5c9ff222816a3274cf | 42598338973 / 129096385204 | 633项 / 406.839秒，OK | 154通过、0失败 / 取消 / 跳过，45个JS文件语法通过 |

[修正作业](https://github.com/1412698607/dsh-eval-lab/actions/runs/42596591126/job/129090609599) · [交付文档作业](https://github.com/1412698607/dsh-eval-lab/actions/runs/42598338973/job/129096385204)。这些数量取自本次实际读取的对应日志，补充而不改写133当时只核对步骤状态的事实。

## 验证、限制与后续

本次仅文档，git diff --check 与4份文档390个相对文件链接目标检查通过；日志复核阶段没有重新执行本地全量测试。后续文档提交的CI按新SHA独立核对，不继承上述两个成功提交的结果。原始日志不加入公开仓库。结论限定上述失败作业及已核对的两个成功提交，不将无模型CI解释为模型可靠性、性能或跨平台结论；无需追加生产修复。
