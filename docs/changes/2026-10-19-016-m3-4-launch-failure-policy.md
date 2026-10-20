# 修改记录 016 M3.4 适配器启动失败策略修复

日期：2026 年 10 月 19 日，Asia/Shanghai。类型：修复 / 测试 / 文档。插件版本：0.1.2。相关 Git 提交：已核实 M3.4 主体为 `bbe1b4a`；本批尚未提交。

## 问题与目标

M3.4 审查发现，准备结束后 Popen 在创建执行适配器前抛出 OSError 时，runtime.stage 已是 run，host / supervisor 均为空。调度器只检查退出码和写线程事实，因此把明确未启动的运行错误判成 cleanup_unconfirmed：continue 提前停止，stop 也失去原本的 failure_policy 停止原因。

本批显式保存适配器启动事实，使未创建进程的错误按策略处理，同时保留未知启动、已启动但清理未确认和人工中断的停止边界。启动错误仍是 runtime_error / unevaluable，不改判普通任务失败，不补造会话或录制身份。

## 文件修改

| 文件 | 修改前 | 修改后 | 原因 |
| --- | --- | --- | --- |
| dsh_eval/runner.py | 执行阶段没有区分进程未创建与已创建 | runtime 添加 adapterProcessStarted，成功 / 未启动 / 未知分别记录 | 提供清理判断所需的实际启动事实 |
| dsh_eval/batch.py | run 阶段一律要求退出和写线程证据 | 明确 false 时允许按策略处理，缺失 / null 仍走原检查 | 修复误停且保留未知状态保护 |
| test/test_batch.py | 缺少执行适配器启动失败回归 | 新增三项，包含 continue / stop、缺失 / null 与启动期中断 | 防止误停及错误放行 |
| CHANGELOG、progress、架构、评测格式、批次说明和 M3 方案 | 未说明该启动边界 | 记录新增事实、验证和阶段状态 | 与实现一致并保留历史依据 |
| 本机私人交接 / 面试材料 | M3.4 主体尚未提交的旧交接 | 记录已核实主体提交、本批修复和后续入口 | 不作为公开仓库依赖 |

## 实现与技术取舍

adapterProcessStarted 初始为 false；进入 Popen 调用前置为 null，成功返回进程后置为 true，OSError 启动失败置为 false 后交由原异常路径生成结果。若创建期间发生 KeyboardInterrupt 等无法确认的情况，保留 null，避免把中断前可能已经创建的进程当作不存在。

批次只在执行适配器明确未启动时省去退出证据要求；已启动或事实未知仍使用原适配器退出码、stdinWriterStopped 和专用宿主清理事实。不能以空 supervisor 或缺少字段推定没有进程。人工中断的判断仍优先于清理与 failurePolicy。准备阶段与已有进程清理逻辑保持。

新增字段是 runtimeFormatVersion=1 的可选观察，旧文件缺失按未知处理；不改录制、用例、证据、单项结果或批次格式版本。continue 的首项保留 runtime_error，后项可以独立 passed，整批仍 unevaluable；stop 的后项保持 skipped 和空身份。

## 验证

2026 年 10 月 19 日，Windows / Node v24.14.0 / Python 3.12.0。没有模型调用。

| 命令或操作 | 结果 | 证明的范围 |
| --- | --- | --- |
| 修复前 `python -m unittest discover -s test -p test_batch.py` | 18 项中两个策略子场景失败，启动期中断检查缺字段 | 复现 continue / stop 误归 cleanup_unconfirmed，确认新增回归能发现问题 |
| 修复后相同批次检查 | 18 项通过 | 启动失败后 continue 得到后项 passed，stop 使用 failure_policy；缺失 / null 不放行；人工中断停止；已有清理未知检查保持 |
| `npm.cmd run test:python` | 获准环境 76 项通过（原 73 + 新 3） | 全部 Python 回归，包含真实自建进程的监督与强停检查 |
| `npm.cmd test` / `npm.cmd run check` | 42 项 / 29 个 JS 文件通过 | Node 回归与 JavaScript 语法 |
| `python -m compileall -q dsh_eval test` | 通过 | Python 语法 |
| `python -m scripts.smoke_bridge` | 获准环境真实工具注册 / IPC 四次请求通过，modelCalled=false | 与原实时桥接兼容，不是模型任务 |
| 公开 Markdown 相对链接、fixture 格式及 Git 范围检查 | 30 份 Markdown / 142 个本地链接有效，五用例及批次格式通过；git diff --check 通过 | 无公开链接指向忽略资料，runs / private-notes 仍忽略且无跟踪文件 |

新增测试中的启动失败和 KeyboardInterrupt 为异常注入；continue 后项使用真实 Node 子进程、合成适配器、Python 环境与原录制器 / fresh inspect，不能称为实际 Harness 模型验收或手工按键验证。启动失败结果还使用保存的 case / evidence 离线复验为 unevaluable，实际身份与配置保持 null。本批未复验历史模型轨迹、未重复 smoke:host / check:output，不将历史结果计为本批执行。

## 风险与后续

本次只补适配器启动事实，不扩大进程树或其他平台的清理保证。未知启动或清理仍保守停止；没有新增崩溃恢复、并发、统计或性能 / 成本结论。历史记录 015、真实日志和快照保持。

下一批仍为 M4.1 重复试验与指标口径，随后 M4.2 配置比较与报告、M5；剩两个主要阶段、三个实施批次。本批未自动提交或推送。

## 面试讨论点

空的监督结果不能证明进程未启动；未创建进程也不能伪造退出码。启动事实、资源回收、失败策略与任务结论需要分别表达，异常注入和真实进程 / 模型验证也需要分别记录。

## 文档同步

已更新 CHANGELOG、progress、architecture、evaluation-format、batch-runner、M3 方案，以及本机存在的私人交接和面试材料。命令与参数不变，README 无须调整；公开资料可独立接续开发，不链接私人材料或原始日志。
