# 修改记录 054 实验级续跑预检与批次绑定

日期：2026 年 10 月 27 日，Asia/Shanghai。类型：功能 / 配置 / 测试 / 文档。插件版本：`0.1.2`。相关 Git 提交：尚未提交；起始基线为 `e3dc29a0f7bd3502e070a23ac8ae9d6a4a9883a4`。

## 问题与目标

052 只有批次级续跑，不能把批次条目映射回实验的用例、配置和重复轮次。此外原实验仅在下游批次返回后写 batchId，中断中的实验没有可核对的批次绑定，不能通过猜测目录来确定来源。

本批增加显式绑定及只读实验预检，输出可复用、明确未开始和阻断样本；保持普通失败、未知状态和缺失来源，不实现实验续跑执行或报告合并。

## 文件修改

| 文件 | 修改前 | 修改后 | 原因 |
| --- | --- | --- | --- |
| dsh_eval/batch.py | 总是内部生成批次 UUID | 可选 batch_id，仍校验 UUID、创建新目录 | 为实验提供明确下游身份；默认行为不变 |
| dsh_eval/experiment.py | 仅终态保存批次关联 | 初始 checkpoint 保存 resumeSupportVersion / batchBinding，实际返回时核对预留身份 | 中断时可验证来源，不将预留当实际执行 |
| dsh_eval/experiment_resume.py | 无实验续跑预检 | 锁定实际批次、核对原计划 / 快照、类型敏感的展开比较及逐样本分类 | 保护跨配置 / 轮次关联及原始证据 |
| dsh_eval/__main__.py | 仅批次续跑入口 | --resume-experiment 仅允许 --plan；明确拒绝 --run | 不把预检误当作模型执行 |
| test/test_experiment_resume.py、test/test_model_providers.py | 缺少矩阵中断 / 绑定检查 | 新增十四项回归，既有冻结检查补预留身份核对 | 正反例与旧报告兼容性 |
| 使用说明、进度、架构、方案和 CHANGELOG | 实验续跑仅为候选 | 标明已实现预检及未实现执行 / 汇总边界 | 保留历史验收和明确下一阶段 |

## 实现与技术取舍

在创建实验的初始 checkpoint 前分配下游批次 UUID，保存 batchBinding，传给原 run_batch。普通 batch 仍自动生成 UUID；实验原 batchId / batchResultPath 在取得实际结果后才填写。预留不表示已启动任务，预检必须找到实际批次并验证与 expanded.batch.json 的来源关系。

复用报告端原指纹 / plan-input 复核和 052 批次预检，在同一批次锁下验证原实验、冻结用例、展开用例和批次输入，并逐项保留 caseEntryId / configurationId / repeatIndex。数量检查先于展开，规范化 JSON 比较区分类型；源位置、配置、轮次错配拒绝。已完成项 fresh inspect / 评测一致才可复用，未知项阻断；不创建领取、输出或执行身份。

当前只增加计划格式 experimentResumePlanFormatVersion=1。原实验 / 批次格式与插件版本不变，新增元信息为可选扩展，旧实验继续可报告，但不能自动取得续跑绑定。executionSupported 始终 false，eligibleForResume 仅是数据条件判定。

## 验证

新增十四项定向回归 / 12.322 秒通过；测试采用既有 synthetic 适配器、真实状态化环境、录制器和 Node inspect，凭据和真实模型不接入。辅助数据在原 runner 路由检查后将 evidence / evaluation / batch 来源统一为 synthetic，未开始项仍未知。

| 场景 | 结果与范围 |
| --- | --- |
| 两用例 / 两配置 / 两轮，完成两项后模拟中断 | 八位置顺序不变，复用二项、拟执行六项；预检前后原文件摘要一致、未启动任务 |
| 执行状态未知、坏录制、源锁占用、原 stop 失败 | 阻断，不重标成功或触发真实模型 |
| 完整评测保存、checkpoint 落后 | 恢复完成事实并保留配置 / 轮次 |
| 原输入文件改变 | 仍使用冻结实验与原 plan-input，不读取旧来源路径 |
| 冻结 / 展开冲突、2 与 2.0 混淆、重复 / 倒序身份、布尔重复编号、错误绑定 / 缺批次 | 拒绝无效关联，不自动猜测或修复 |
| 已完成实验 | 无剩余项，可拟续跑为 false；原报告仍可独立生成且输入不变 |
| 上限、真实 Python CLI、--run 拒绝 | 新上限进入摘要；CLI --plan 不产生文件，执行控制在参数解析阶段拒绝 |

最终 `npm.cmd run test:python` 在获准环境完整执行 285 项 / 84.277 秒，全部通过；`npm.cmd test` 的 87 项 Node 无失败 / 跳过，`npm.cmd run check` 的 43 份 JavaScript 语法及 `python -m compileall -q dsh_eval scripts test` 通过。完整回归覆盖新增绑定对原实验、批次续跑和独立报告的兼容性。

再次调用原报告 API 复核 050 历史实验，新报告 e6ea23f8-b8f3-4efb-9a0a-fe0d114fbb12 的计划 verified，四实际样本 verified / matched / live，保持三通过 / 一失败 / 四 skipped；88 份选定原始文件摘要无变化。实际 CLI 对该旧实验预检返回 2、valid=false、modelCalled=false，原因是缺显式批次绑定，没有创建锁或补跑任务。

没有新增真实模型任务、提交 / 推送或新云端 CI；[053](2026-10-27-053-resume-delivery-ci.md) 的成功 CI 仅对应起始提交。

## 风险与后续

首版仅实现预检，不实施实验续跑、重新领取、回填原 summary / samples、跨批次配置报告或浏览器集成。旧实验缺绑定时拒绝；实际批次尚未创建、执行中未知及原失败策略仍不能自动放行。锁与摘要是当前本地协作 / 一致性机制，不提供签名、多文件事务读取或断电恢复保证。

真实模型续跑验收仍待执行入口实现后单独安排；当前无模型结果不能证明该能力已经完成。

## 文档同步

新增 [实验续跑预检](../experiment-resume.md)，同步 README、docs/progress.md、docs/architecture.md、docs/experiments.md、docs/batch-runner.md、docs/batch-resume.md、docs/plans/m6-reliability-validation.md 和 CHANGELOG。

本轮修改 Markdown 的 345 个本地文件链接均有效，git diff --check 通过；全部 17 份修改 / 新增文件的本机实际凭据值扫描无匹配。runs / private-notes / secrets 没有已跟踪文件，检查产物保存在忽略目录。
