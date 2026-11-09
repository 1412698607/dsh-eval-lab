# 修改记录 129 实验原因汇总交付验收

日期：2026 年 11 月 9 日，Asia/Shanghai。类型：文档。插件版本：0.1.2。已核实实现提交：`00d2df9dfa54dc286e930da2e53b4b37ff05636a`。

## 目标与范围

[127 实验原因汇总](2026-11-09-127-experiment-assertion-causes.md)和[128 复查修正](2026-11-09-128-assertion-cause-report-review.md)的 18 份公开文件已共同提交并推送至 `20261109/feat/experiment-rule-impact`。本记录登记该精确提交的 CI，原验证、修正和当时未提交状态保留。

## 验证

本地复查完整 583 项 Python / 421.426 秒、152 项 Node / 7.725 秒、45 个 JS 文件语法、compileall 和工作流生成复验通过；十份文档的 594 个相对文件链接目标有效，见 128。历史四任务离线验收与源摘要保持见 127，本次没有新增模型任务。

通过公开 Actions API 按完整 head_sha、分支及 push 事件筛选，核对运行、作业 head_sha、attempt 与每一步状态。[运行](https://github.com/1412698607/dsh-eval-lab/actions/runs/42588984655) · [作业](https://github.com/1412698607/dsh-eval-lab/actions/runs/42588984655/job/129065642009)

| 项目 | 结果 |
| --- | --- |
| SHA | 00d2df9dfa54dc286e930da2e53b4b37ff05636a |
| run / attempt | 42588984655 / 1 |
| job | 129065642009 / deterministic |
| 环境与事件 | Windows、Node 24 / Python 3.12、当前开发分支 push |
| 运行 / 作业 | completed / success |
| 全部步骤 | 14 项 completed / success，包含新增工作流生成复验 |

核对到步骤状态，未读取云端日志的具体测试数量；583 / 152 / 45 是本地记录。后续归档功能是独立改动，不继承此提交的 CI 结果。

## 文档同步与限制

新增本记录并更新 CHANGELOG、进度。纯文档按补丁与相对文件链接检查验证，不重复运行本地代码测试。旧失败、模型观测与历史状态不改写；本次 Windows 无模型 CI 不推广为其他平台或模型表现结论。
