# 修改记录 084 行为约束交付验收

日期：2026 年 11 月 1 日，Asia/Shanghai。类型：交付 / 文档。插件版本：`0.1.2`。实现提交：`e185a8eca481bdebde74643f00cb7137a686d755`。

## 问题与目标

核实 082 的工具禁止 / 调用次数约束及 083 边界复查已提交推送，独立核对该精确提交的无模型 CI。原开发与复查中的未提交快照、本地结果和验证边界保留。

## 文件修改

仅新增本记录并同步 CHANGELOG、docs/progress.md；不修改生产代码、测试或固定用例。

## 实现与技术取舍

正常推送现有 `20261027/feat/experiment-resume` 分支，由 `0ba0b93` 快进至 `e185a8e`，没有强制推送。提交包含 082 / 083 的 15 份实现、测试和公开文档。验收核对 push 事件、head_sha、attempt、作业与步骤；不继承其他提交的 CI，也不把本地数量当作云端测试数量。

## 验证

| 操作 | 实际结果 | 范围 |
| --- | --- | --- |
| `git commit` 后 `git rev-parse HEAD` | `e185a8eca481bdebde74643f00cb7137a686d755` | 082 / 083 的 15 份文件完整提交 |
| `git push origin HEAD:refs/heads/20261027/feat/experiment-resume` | 成功，`0ba0b93..e185a8e` | 正常快进推送 |
| [push run 41282287850](https://github.com/1412698607/dsh-eval-lab/actions/runs/41282287850) | completed / success | 精确 head_sha 为实现提交，attempt 1 |
| [job 124776472051](https://github.com/1412698607/dsh-eval-lab/actions/runs/41282287850/job/124776472051) | completed / success，全部 13 个步骤 success | Windows 无模型工作流，作业关联相同 SHA |
| 本轮三份 Markdown 的相对路径、标题锚点、忽略目标及 `git diff --check` | 255 个本地链接 / 107 个目标通过，补丁检查通过 | 纯文档补记，没有重复本地完整代码测试 |

JavaScript 语法、Node 测试、Python 全量回归、Python 编译和合成示例步骤均成功。未读取原始云端日志，具体测试数量不以历史本地 401 / 111 或本轮定向数量替代。

## 风险与后续

未新增模型任务、运行时工具拦截或固定评测集扩展。工具行为约束仍按精确名称 / 参数匹配当前单任务片段，任务外调用和不充分证据不能推定为零次。本记录是实现提交之后的文档补记，其提交与 CI 独立核对。

## 文档同步

CHANGELOG 和 docs/progress.md 补充交付结果并更新当前基线表，082 / 083 历史验证保持原样。
