# 修改记录 033 M6.4 真实 Web 接入与验收

日期：2026 年 10 月 24 日，Asia/Shanghai。类型：功能 / 修复 / 测试 / 文档。插件版本：`0.1.2`。相关 Git 提交：尚未提交。已核实开始及结束基线 HEAD 为 `2c60b638d437b2d2b6afd09830bef5e147937924`，实际分支 `20261024/feat/m6-4-web-lifecycle`；030 / 031 / 032 的未提交工作与历史结果保留。

## 问题与目标

032 已修复中断验收放过未知状态版本、空 / 未覆盖操作检查点的问题，但当时仅有合成事件和真实专用子进程检查。用户随后选择现有 deepseek-official / deepseek-flash，先补实际 Web 接入，再执行页面取消、正常宿主退出和任务处理中断各一个任务；首次正常任务失败后，另行授权只追加一个正常任务，保留失败样本。共四次任务，未自动重跑取消或中断。

本批增加可核对的实际页面动作、模型流、工作区 / 路由及普通退出来源。真实 Web 有在途事件，不能直接把合成 fixture 的“flush 后停止追加”相等条件套用到真实场景；仍须保留 032 的版本与操作检查点覆盖门禁。

## 文件修改

| 文件 | 修改前 | 修改后 | 原因 |
| --- | --- | --- | --- |
| scripts/web-lifecycle-live.js | 无真实 Web 生命周期驱动 | 新增独立 prepare / run / check-console，冻结 Web fixture、受控工作区和已有凭据引用；ConPTY / 精确 PID 监督 | 采集真实普通信号与强停，不用测试 IPC 代替 |
| scripts/fixtures/web-lifecycle-observer.js | 无纯观察插件 | 只记录原生事件元信息、cwd / sourceKind / 路由、首次模型 chunk、SIGINT / 卸载 | 避免观察器预先 cancel / flush / appExit 改变被测路径 |
| scripts/verify_web_live.py | 无 live 协议验收 | 独立 live 版本 1，关联实际 CUA 动作、模型流、录制 / 路由 / 环境和进程事实 | 合成 source 不能靠改标签升级；后置门禁失败整体 unevaluable |
| scripts/verify_web_lifecycle.py | 共用检查嵌在合成入口 | 抽取共享录制 / 任务门禁，默认严格完整前缀，仅 live 显式允许有效未确认尾部；只数 source.kind=user 的任务输入 | 支持真实上下文事件和在途字节，保持版本 / 非空检查点 / afterSeq 门禁 |
| test/test_web_live.py、test/test_web_lifecycle.py、test/web-live.test.js | 22 项合成生命周期测试，无 live 元信息回归 | 新增 9 项人工 live 元信息测试、2 项共享规则测试和 3 项 Node 回归 | 覆盖来源 / 时间 / 信号、后置门禁、上下文计数、检查点尾部与纯观察行为 |
| package.json | 仅 check:web-lifecycle | 新增显式 live:web-lifecycle，默认测试与 CI 不调用模型 | 区分无模型检查和需要外部页面步骤的真实命令 |

## 实现与技术取舍

prepare 通过既有 CLI 插件管理离线安装本地插件，独立 home / profile / pnpm store，冻结 case 和 fixture。凭据引用已有文件，不复制密钥；只读策略、禁用模型标题请求和遥测。Web 首个 Workspace 由 workspace-controller.documentsDirectory 配置指向本场景的 documents/deepseek-harness/default-workspace，提交前核对注册表和原生 cwd，避免把 CLI cwd 当成 Web 的实际根目录。

观察插件不控制 Agent，只追加 session/event 的身份 / 序号 / cwd / sourceKind / 请求路由、首次模型 chunk、SIGINT 和卸载。外部 CUA 在页面真正提交一次任务、点击“停止生成”，保存操作时间、origin、控件名和截图；监督器的 mark-page-cancel 仅记录已有磁盘检查点。普通退出在 turn/end 后向自己的 ConPTY 写 Ctrl+C，实际触发 CLI SIGINT 清理；此版本 Windows 正常清理 exitCode=130、signal=null。处理中断对自有精确 PID 请求 SIGKILL，native 实际回报 exitCode=1、signal=null；不把请求信号伪造成观测返回值。

监督器从实际 source.kind=user 提交开始设 120 秒超时，结束后撤销；Ctrl+C 之后最多等 10 秒，兜底强停有独立原因，不计场景通过。ConPTY 启动早期 pid=0，在 URL 就绪后重新捕获实际 PID；等待 native onExit 后同步保存证据，再释放可能由 node-pty worker 保持存活的监督 CLI。无模型初次预检虽收到 SIGINT、子进程退出 130，但监督器残留未算整体通过；修正后独立预检退出 0、receivedSIGINT=true。

Python 每次读取当前磁盘并运行原 Node inspect，再核对 run / session、连续单任务、断言、实际路由与原生观察。版本明确为 run 的整数 2 / 1 / 1、会话状态整数 1；中断必须有非空已写检查点覆盖 afterSeq，开放清单以外的不确定原因拒绝。真实路径允许有效尾部，原合成入口仍要求完整前缀相等。没有复制摘要算法、修改 recorder / inspect / dsh_eval / main.py 或迁移原格式。

workspaces 观测若不匹配则拒绝；正常 / 中断还要求路径观测可用。取消样本允许缺该观测，但显式报告未知，不能说环境一致或读取成功。route / environment 等后置门禁失败时，即使独立断言 passed，整体 outcome 改为 unevaluable，不保留误导性的整体 passed。新 live 清单、观察、UI 动作和结果的字段约定见 [Web 生命周期](../web-lifecycle.md)。这些本机证据不是签名，也不是对任意外部来源的真实性保证。

## 验证

环境：Windows；Node.js `v24.14.0`、Python `3.12.0`，CLI / SessionStore `0.2.0-rc.2`、Cordis `4.0.4`，宿主可解析的 node-pty `1.2.0-beta.15`，固定 provider / model 为 deepseek-official / deepseek-flash。真实任务和需要进程权限的回归均在获准环境执行，未将 mock 或 EPERM 计作真实接入通过。

### 四次真实模型任务

| 次序 / 场景 | 实际结果 | 验收和边界 |
| --- | --- | --- |
| 1 normal-exit | 默认 Web Workspace 未绑定 fixture，read README 失败，模型完成了错误说明；监督器误计上下文消息并最终超时强停 | 原报告 PID=0 / timeout 等事实保留，live 验收拒绝；独立任务诊断 answer / actual-read 失败、completed 通过，不是正常退出通过 |
| 2 page-cancel | 模型流后真实点击停止，aborted/user；随后实际 Ctrl+C、SIGINT / 卸载及 exit130，36 条 sealed | cancelled / complete / unevaluable、断言 not_run；live 生命周期通过。此采集尚无 cwd 字段，workspaceMatch=null，原读取失败，未验收 fixture 一致性 |
| 3 process-interrupt | 模型首个 chunk 后对自有 PID 强停，实际 exit1 / signal=null；无 turn/end，run / session 保持 recording | interrupted / unverified / unevaluable、断言 not_run；live 通过且 cwd 匹配。磁盘 16 条有效事件，检查点 14 条截至 seq13，afterSeq13，尾部 seq14 / 15 未确认 |
| 4 追加 normal-exit | 实际 read README 成功并返回 dsh-eval-web-fixture；任务结束后实际 Ctrl+C 清理，25 条 sealed | completed / complete / passed、三项断言通过，live 通过且 cwd 匹配；2 次已结算模型调用、1 次工具调用 |

因此是四次尝试保留一次失败，三类生命周期最终各有通过样本；不是首次 3 / 3，也不是四次任务全部成功。取消 / 中断不计任务成功。单任务可能包含多次模型请求；中断指标不由不完整轨迹补算，取消 token 覆盖不全、所有费用保持 null。elapsedSeconds 是服务启动到退出的时间，含页面等待，不当作模型性能。

### 无模型回归与独立复验

| 命令或操作 | 结果 | 证明的范围 |
| --- | --- | --- |
| node scripts/web-lifecycle-live.js check-console <全新目录> | 修正后 native SIGINT 收到、子进程 exit130、监督器退出0，modelCalled=false | 普通 ConPTY Ctrl+C 路径，无模型 |
| python -m unittest discover -s test -p test_web_live.py -v | 9 项通过 | 人工元信息的拒绝门禁，不冒充真实页面 / 模型证据 |
| npm.cmd run test:python | 最终 196 项通过，57.089 秒 | 原真实子进程回归、24 项共享生命周期测试及新 live 门禁 |
| npm.cmd test | 82 项通过，无失败 / 跳过 | 新 3 项 Node 回归及既有录制 / 宿主测试 |
| npm.cmd run check | 41 份 JavaScript 语法通过 | 包含新监督器、观察插件和 Node 测试 |
| python -m compileall -q dsh_eval scripts test | 通过 | Python 编译检查 |
| python -m scripts.verify_web_live <单场景目录> --output <新文件> | 四保存样本独立进程复验：首失败退出1，其余三个退出0 | 重新 inspect，不依赖原 verification 成功；不启动模型 |
| 真实录制隔离副本的独立 CLI 复验 | 八反例全退出1、verified / liveWebVerified=false | 未知状态版本、空 / 未覆盖操作检查点、残留替换文件、旧成功后截断、非页面取消来源、缺原生 SIGINT、错误工作区；后置环境失败整体 unevaluable |
| 摘要与进程核对 | 38 份本批原始证据、77 份受保护源文件 / 旧证据摘要未变；四实际 CLI PID 与最终控制台预检 PID 均不存在 | 仅精确自有 PID，无任意外部进程树保证 |
| 文档 / Git 核对 | 56 份公开 Markdown、374 个相对文件链接有效；换行 / 空白、当前分支及 git diff --check 通过 | runs / private-notes 仍忽略且无跟踪；仅 LF / CRLF 提示，无自动提交 |

本机忽略的验证目录保留原始失败 / 成功、页面截图、操作和生命周期事实、独立副本及命令输出。无模型回归不依赖这些原始运行目录，公开仓库不提交原始会话、bootstrap 令牌、缓存或凭据。本批未运行新的云端 CI、重复资源测量或 desktop / SDK 模型任务。

## 风险与后续

本批授权四次任务已使用。取消样本完整工作区一致性仍未覆盖，需要另定是否补验；其他平台 / CLI 版本、desktop / SDK、第二套配置和重复试验仍待范围及预算。当前实际页面步骤依赖外部 CUA，仓库命令不提供自动浏览器驱动或人工动作来源的通用验收协议。新协议仅增加独立文件，旧 synthetic 版本 1、M2.3 与通用评测入口保持兼容。

新增事件仍不是完整会话备份或确定性重放，flush / sealed 不保证 fsync、断电可靠或崩溃恢复。open / invalid 保留自己的含义，不把检查失败统一解释为“预期强停”。没有任务成功率、成本或性能提升结论。没有自动提交 / 推送。

## 面试讨论点

沿一个 Web 取消任务解释：先观测到原生流和已写前缀，再实际点击页面停止，核对同任务 aborted/user；随后真正向 ConPTY 输入 Ctrl+C，观察 SIGINT / 卸载并等待 onExit，最后 fresh inspect 得到 complete，但任务仍 unevaluable。可讨论为何观察器不能提前 flush、Windows kill(SIGINT) 与输入 Ctrl+C 的区别、CLI cwd 与实际 Workspace 的差异、原生上下文消息为何不算新任务，以及真实尾部与操作检查点如何分开验证。首轮失败及有限覆盖是证据的一部分，不归因于模型质量。

## 文档同步

同步 README、[Web 生命周期](../web-lifecycle.md)、[架构](../architecture.md)、[进度](../progress.md)、[M6 方案](../plans/m6-reliability-validation.md) 和根 CHANGELOG；本机私人交接 / 面试材料更新但不作为公开依赖。031 / 032 的历史结果不覆盖，当前范围与修正统一写在本记录。
