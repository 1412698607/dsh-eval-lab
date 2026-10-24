# 修改记录 034 M6.4 取消场景工作区一致性补验

日期：2026 年 10 月 24 日，Asia/Shanghai。类型：验证 / 文档。插件版本：`0.1.2`。相关 Git 提交：尚未提交。已核实 HEAD 为 `2c60b638d437b2d2b6afd09830bef5e147937924`，分支 `20261024/feat/m6-4-web-lifecycle`。保留 030 至 033 的未提交工作与历史结果，没有提交、推送或新的云端运行。

## 问题与目标

033 的旧取消样本已证明真实页面取消与正常宿主清理，但当时没有 session cwd 观测，实际 README 读取也失败，因此只报告工作区未知，不能声称 fixture 一致。用户新授权仍用现有 deepseek-flash，只追加一个取消任务，保留原样本并同步文档。

本轮目标是新样本的实际 Web Workspace 与冻结 fixture 一致，真实相对路径读取成功之后，在同一任务中实际点击停止并完成普通退出。只执行一个新任务，不重跑正常 / 中断、不改写旧样本。

## 文件修改

| 文件 | 修改前 | 修改后 | 原因 |
| --- | --- | --- | --- |
| README.md、docs/progress.md | 取消工作区缺口待补 | 当前状态为新样本已补齐，累计五次任务，旧未知保留 | 区分新覆盖与历史不足 |
| docs/web-lifecycle.md | 生命周期通过与工作区覆盖的要求需进一步明确 | 新增要求环境两字段均为 true 的门禁及补验步骤 / 结果 | 不能将旧未知当作一致性通过 |
| docs/architecture.md、docs/plans/m6-reliability-validation.md | 033 的取消覆盖局限为当前状态 | 补充 034 的验证范围；架构 / 协议行为不变 | 同步实际验收范围 |
| CHANGELOG.md、本记录 | 无本次补验说明 | 增加独立 034 与链接 | 保留任务数量、过程和证据边界 |

生产代码、测试、用例 fixture 和格式均未改动。本机忽略目录仅新增独立运行证据、离线核对脚本 / 副本及检查结果；私人交接和面试材料同步，不作为公开仓库依赖。

## 实现与技术取舍

复用 033 的 prepare / run、纯观察插件和独立 live 验证器，使用全新 home / Web profile / pnpm store 和 documents 下的 fixture 工作区，只引用既有凭据。实际 provider / model 仍为 deepseek-official / deepseek-flash，禁用额外模型标题请求，不更改任务输入。页面工具在提交前恢复连接，预检确认仍为零任务；实际只点击发送一次。

提交前保存工作区注册表与预检，核对支持的 documentsDirectory 配置、只读 workspaceRoot、实际原生 cwd 和 README 字节。收到真实模型流后继续观察到 read README 成功，才记录取消检查点并点击页面“停止生成”。监督器只读取已有状态，不提前 flush / cancel / appExit；任务结束后再通过 ConPTY 输入 Ctrl+C，等待原生 SIGINT、插件卸载和 native onExit。

离线先运行原 verify_web_live 重新 inspect，明确要求 liveWebVerified、workspaceMatch、workspaceObservationAvailable 均为 true；再核对全部原生事件 cwd、原生序号与录制一致、单任务输入、实际路由和相对路径读取证据。单独只检查 actual-read，不执行取消任务的完整答案 / completed 断言，不把读取成功升级为任务完成。

旧取消样本仍允许在现有生命周期协议中报告通过且工作区未知；本轮不改变兼容性。只有观测可用且实际匹配的新样本才满足“工作区一致性”目标。错误工作区副本拒绝通过；移除 cwd 的副本仍为未知，文档的额外覆盖门禁必须拒绝它。

## 验证

环境：Windows，Node.js `v24.14.0`、Python `3.12.0`，CLI / SessionStore `0.2.0-rc.2`、Cordis `4.0.4`、node-pty `1.2.0-beta.15`；真实子进程与准备过程在获准环境执行。以下命令的场景目录均为本次全新目录，公开说明用可移植占位路径。

| 命令或操作 | 结果 | 证明的范围 |
| --- | --- | --- |
| npm.cmd run live:web-lifecycle -- prepare <新场景目录> page-cancel | 离线准备成功，固定 deepseek-flash，无任务提交 | 独立 profile / workspace，不复制凭据 |
| npm.cmd run live:web-lifecycle -- run <场景目录>；CUA 发送一次、读取后点击停止；随后输入 shutdown | 唯一实际任务取消，原生 SIGINT / 卸载和 exit130，signal=null，无强停 / 错误 | 真实页面取消与普通清理，不用 API 代替点击 |
| python -m scripts.verify_web_live <场景目录> --output <新文件> | 原检查及独立 CLI 复验均退出0，环境两字段均 true | fresh inspect=complete，25 条 sealed；cancelled / complete / unevaluable、主断言 not_run |
| 隔离配置 / 注册表 / 原生事件 / fixture / actual-read 离线核对 | 全部 25 条原生 cwd 匹配，单条读取证据 passed，读取先于取消 | 覆盖目标工作区与实际工具返回，不等同完整任务成功 |
| 新样本的错误工作区副本 | live CLI 退出1、workspaceMatch=false、unevaluable | 不匹配会被拒绝，原样本不变 |
| 删除 cwd 的副本与原取消样本 | 生命周期仍通过，workspaceMatch=null / observationAvailable=false；文档覆盖门禁均拒绝 | 未知不补为已验证，也不篡改原记录 |
| python -m unittest discover -s test -p test_web_live.py -v | 现有 9 项通过，0.016 秒 | 定向元信息 / 路由 / 环境门禁回归，不冒充模型证据 |
| node --test --test-isolation=none test/web-live.test.js | 现有 3 项通过，无失败 / 跳过 | 任务计数、原检查点与纯观察行为 |
| 文件摘要及精确 PID 核对 | 228 份受保护代码 / 历史记录 / 旧证据、18 份新原始证据不变，专用 CLI PID 已退出 | 原样本完整保留，仅查询自有进程 |
| 文档 / Git 检查 | 57 份公开 Markdown、386 个相对文件链接有效，换行 / 空白与 git diff --check 通过 | runs / 私人材料仍忽略且无跟踪，只有既有 LF / CRLF 提示 |

本次 runId 为 `bfa77271-8e95-4c24-85c7-44fac03fae7a`，sessionId 为 `session-cda1d377-6c72-4753-ae69-d521c2476d08`。相对路径 read 的 callSeq=17 / resultSeq=18，返回包含正确 projectName，早于取消检查点 afterSeq=21；部分回答在 seq22，turn/end 在 seq24，为 aborted/user。25 条录制连续、运行与会话均 sealed，页面截图同时展示读取的 fixture 和“已停止”。README 与冻结文件字节保持一致。

首次辅助配置核对误将运行后由宿主规范化的 YAML 当作 JSON，未完成整项离线核对；随后使用宿主现有 YAML 解析器，仅读取相关配置后复验通过，初次 fresh 输出单独保留，没有重跑模型。所有原始 / 派生结果只在忽略目录保存，公开文档不链接日志、缓存或本地认证地址。

本轮实际新增一个任务，运行指标 modelCalls=2 / toolCalls=1，不等于两次任务；取消用量覆盖不全，token 和费用保持 null。elapsedSeconds 为 115.495 秒，包含服务启动和页面等待，不是模型延迟。累计五次（正常两次、取消两次、中断一次），首次正常失败与旧取消未知保留，不能说五次任务全部成功。

## 风险与后续

新取消样本已补齐本机 Windows / 当前 CLI 的工作区一致性缺口。主结果仍 cancelled / complete / unevaluable、断言 not_run；原取消样本工作区仍未知，不能追溯升级。只验证一个新增样本，其他平台 / 版本、desktop / SDK、第二套配置及重复试验未扩展。唯一新增任务额度已使用，后续模型运行需另定范围。

本轮无生产代码 / 协议变更，不重复全部测试；033 的 196 Python / 82 Node / 41 文件语法及 compileall 保持历史结果，不作为本轮重跑成绩。没有云端 CI、资源测量或成本 / 成功率 / 性能提升结论。新增事件、flush / sealed 和摘要继续不提供完整备份、fsync、断电恢复或签名保证。

## 面试讨论点

可以用一个取消任务串联“冻结环境 → 实际 Workspace → 真正读取 → 页面停止 → 原生退出 → fresh inspect”。生命周期 verified 和环境 coverage 是不同事实；旧样本可以取消成立但工作区未知，新样本用注册表、原生 cwd 和工具返回补齐覆盖。单条读取证据 passed 不改变取消任务的三维分类，复验也不能改写原始失败或未知。

## 文档同步

同步 README、CHANGELOG、[Web 生命周期](../web-lifecycle.md)、[进度](../progress.md)、[架构](../architecture.md)、[M6 方案](../plans/m6-reliability-validation.md) 及本机私人材料。033 及更早修改记录不变，当前范围统一以 034 为准；完成前检查链接、换行 / 空白、摘要及 Git 状态。
