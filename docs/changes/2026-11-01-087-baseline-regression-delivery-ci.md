# 修改记录 087 基线回归比较交付验收

日期：2026 年 11 月 1 日，Asia/Shanghai。类型：交付 / 文档。插件版本：`0.1.2`。实现提交：`124f2c06d50d5438e02b04fd659c613fd5453cc8`。

## 问题与目标

核实 085 基线比较和 086 输入根类型 / 退出码边界修复已完整提交推送，并独立核对精确提交的云端检查。原开发与复查阶段的失败、未提交快照和本地验证保留。

## 文件修改

新增本记录，更新 README 中当前交付引用、CHANGELOG 与 docs/progress.md；不修改实现、测试或固定用例。

## 实现与技术取舍

现有分支 `20261027/feat/experiment-resume` 正常快进，由 `f4009f5` 推送到 `124f2c0`；包含 085 / 086 的 14 份实现、测试和公开文档。验收按精确 head_sha、push 事件、attempt、作业与步骤核对；不以其他提交或本地结果代替云端验收。

## 验证

| 操作 | 实际结果 | 范围 |
| --- | --- | --- |
| `git commit` 后 `git rev-parse HEAD` | `124f2c06d50d5438e02b04fd659c613fd5453cc8` | 14 份文件完整提交 |
| `git push origin HEAD:refs/heads/20261027/feat/experiment-resume` | 成功，`f4009f5..124f2c0` | 正常推送，无强制覆盖 |
| [push run 41286345807](https://github.com/1412698607/dsh-eval-lab/actions/runs/41286345807) | completed / success | 精确实现 SHA，attempt 1 |
| [job 124788317285](https://github.com/1412698607/dsh-eval-lab/actions/runs/41286345807/job/124788317285) | completed / success，全部 13 个步骤 success | 作业关联相同 SHA，Windows 无模型检查 |
| 本次四份 Markdown 的相对链接、标题锚点、忽略目标及 `git diff --check` | 334 个本地链接 / 115 个目标通过，补丁检查通过 | 仅文档补记，本轮不重复本地完整代码测试 |

已核实 JavaScript 语法、Node 测试、Python 全量回归、Python 编译与合成示例步骤均成功。未读取原始云端日志，不将历史本地 420 项或本轮定向数量作为实际云端测试数量。

## 风险与后续

没有新增模型任务或模型表现结论。基线比较仍限于稳定归档、显式配置、严格任务 / 来源 / 执行身份匹配；缺项或不可比不能通过门禁。此文档补记在实现提交之后单独提交，其 CI 独立核对。

## 文档同步

README 的最新已验收实现引用及进度基线表随本次交付更新，085 / 086 的历史记录保留。
