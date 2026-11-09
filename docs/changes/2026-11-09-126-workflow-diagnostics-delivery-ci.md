# 修改记录 126 工作流与诊断交付验收

日期：2026 年 11 月 9 日，Asia/Shanghai。类型：文档。插件版本：0.1.2。已核实实现提交：`4ef9d8f66c0b5fee771835ab887ea7156775148e`。本记录形成时，文档补记尚未提交。

## 目标与范围

核对 [122 计划](2026-11-09-122-workflow-diagnostics-plan.md)、[123 批次 A](2026-11-09-123-reproducible-workflow-demo.md)、[124 批次 B](2026-11-09-124-structured-assertion-diagnostics.md)及[125 复查修复](2026-11-09-125-workflow-diagnostics-review.md)的共同交付。实现、测试、工作流配置与文档共 28 份公开文件，提交并推送至 `20261109/feat/experiment-rule-impact`；推送后本地 HEAD 与 origin 分支均为上述完整 SHA，工作区干净。

本次仅新增交付记录，更新 CHANGELOG 和进度。不改实现或重写历史验证。runs、private-notes 和原始运行内容保持忽略，未加入提交。

## 实现及本地验证

已交付可重复三场景工作流、实验预览浏览、结构化原因与依赖展示，以及复查发现的两项修复：合成适配器应用冻结录制限额、诊断视图按原保存断言排序。评分聚合、历史结果续跑与规则预览核心核对保持。

125 的本地验证为完整 565 项 Python / 330.531 秒、145 项 Node / 7.687 秒、45 个 JS 文件语法、compileall、原 demo:eval 与新 demo:workflow 生成通过。十二份变动文档的 593 个相对文件链接目标有效；具体输入、命令、反例及范围保留在原记录中。全部新增轨迹为合成数据，没有新增模型任务。

## 精确提交的云端 CI

通过公开 GitHub Actions API 按完整 head_sha、分支和 push 事件筛选，再核对作业 head_sha、attempt、状态及每个步骤。未用旧基线 CI 代替本次结果。[运行](https://github.com/1412698607/dsh-eval-lab/actions/runs/42575116183) · [作业](https://github.com/1412698607/dsh-eval-lab/actions/runs/42575116183/job/129020974952)

| 项目 | 核对结果 |
| --- | --- |
| 提交 | 4ef9d8f66c0b5fee771835ab887ea7156775148e |
| 分支 / 事件 | 20261109/feat/experiment-rule-impact / push |
| 工作流 | Deterministic checks (no model calls)，Windows，Node 24 / Python 3.12 |
| run / attempt | 42575116183 / 1 |
| job | 129020974952 / deterministic |
| 运行 / 作业 | 均 completed / success |
| 步骤 | 全部 14 项 completed / success |

14 项包括环境准备、checkout、Node / Python 设置、JavaScript 语法、Node 测试、Python 评测与浏览测试、Python 编译、原合成示例、新工作流生成复验，以及三个 post 步骤与作业完成。新增 `Generate and recheck synthetic workflow` 确认为 completed / success，证明公开 checkout 上的无模型入口已在本次 CI 执行成功。

本次核对到运行、作业和步骤状态，没有读取云端测试日志的具体测试数量。上述 565 / 145 / 45 是本地执行记录，不能写成云端实测数量。

## 限制与文档同步

CI 为 Windows 无模型验证，不提供真实模型表现、其他平台或断电持久性结论。历史失败和补验记录保留。本记录只登记已完成的实现 SHA；后续文档提交是新的 SHA，其 CI 需要独立核对。

更新 CHANGELOG 和 docs/progress.md，明确当前实现交付及其精确提交的 CI。纯文档补记按补丁与相对链接检查验证，未重复运行本地全部代码测试。

本次三份文档共 350 个相对文件链接目标有效，git diff --check 通过。
