# 修改记录 011 M3.2 单用例真实 headless 运行

日期：2026 年 10 月 17 日，Asia/Shanghai。类型：功能 / 测试 / 文档。插件版本：`0.1.2`。相关 Git 提交：本批尚未提交；已核实 M3.1 基线 `868529d`。沿用分支 `20261015/feat/eval-workflow`。

## 问题与目标

M3.1 可以检查离线轨迹，但初始文件和超时预算仅是声明，不能从用例自动取得真实运行证据。M3.2 需要由 Python 准备隔离环境和新执行身份，调用实际 Harness，采集配置 / 退出 / 干预事实并交给离线评测，分别识别正常任务、启动 / 路由错误、超时和取消。

本批完成受控文件任务的真实单用例闭环，不增加状态化工具、实时 Python 工具桥接、批次或统计报告。后续还剩 M3.3、M3.4、M4、M5 四个主要阶段；按 M4.1 / M4.2 拆分为五个实施批次，渠道和录制加固另按需求计。

## 文件修改

| 文件 | 修改前 | 修改后 | 原因 |
| --- | --- | --- | --- |
| `dsh_eval/runner.py` | 无通用真实用例调度 | 新执行 / 文件环境、准备和运行监督、预算 / 取消、退出回收、证据与评测保存 | 不另写 Agent 循环，实际执行原用例声明 |
| `scripts/case-host.js` | 固定 M2.3 场景脚本 | 复用实际 CLI 离线安装和 IPC 启停方式，观察实际路由 / 进程事实 | Harness 生命周期与宿主接口保持 JavaScript |
| `scripts/fixtures/case-control.js` | 仅旧流 / 取消控制器 | 复用原控制器，增加 actual selection / request/header 观察 | 区分请求配置与实际路由；不改历史控制器 |
| `dsh_eval/__main__.py` | 只支持离线参数 | 新增 --run / --runs-root / --host-modules / --cancel-after-stream | 明确真实运行与离线模式，自动新建结果 |
| `dsh_eval/formats.py`、`evaluate.py` | 版本 1 强制存在身份 / 配置 | 兼容版本 1，版本 2 可空实际事实与 runtimeReport；正常 live 任务再次核对日志请求路由 | 启动失败不填假 ID / 假配置 |
| `fixtures/evaluation/live-read.case.json`、fixture 说明 | 只有合成用例 | 可实际执行的文件读取用例，参数为宿主实际 file_path | 公开用例可复现，真实输出仍忽略 |
| `test/test_runner.py`、`test/test_evaluation.py`、`test/case-host.test.js` | 30 Python / 36 Node 项 | 新增 14 Python / 3 Node 项，总计 44 / 39 | 文件准备、兼容、路由、防假完成、真实监督 / 强停及协议反例 |
| README、进度、架构、路线、格式、单用例说明、CHANGELOG | M3.2 仍为计划 | 同步实际入口、边界、证据与下一批 M3.3 | 当前文档与代码一致 |

未改 `src/`、录制 run / JSONL / status 协议、`main.py` 或既有 M2.3 prepare-live / run-live / live-control / verify_live；没有提交或推送。

## 实现与技术取舍

1. 保持 caseFormatVersion 1。Python 生成新 caseRunId 子目录和快照，实际写入独立 workspace 的文本文件；除了用例基本路径校验，补查 Windows 保留名、大小写与文件目录冲突，不复用已有目录。
2. Node 找到并校验固定版本宿主，通过实际 CLI 在新 home / pnpm store 离线安装本地插件；只引用原凭据路径，设置独立 read-only workspace、请求的默认 provider / model，关闭额外标题请求和遥测。没有下载新宿主或更改原 profile。
3. Python 准备阶段有独立 150 秒期限；任务墙钟预算覆盖适配启动和实际任务，之后为清理和 inspect，不宣称总退出硬上限。达到预算后通过 Node IPC 停止 Agent、等待 idle / flush；Node 10 秒后尝试强停 CLI，Python 15 秒后尝试终止仍存活的自有进程树。Windows 用确切 PID，权限错误不能当作回收成功。
4. 实际 selection / request/header 由专用控制插件观察，headless 首 session、末 final 和结束事实也需一致。实际配置从请求头生成；请求未知路由只证明发生尝试，不证明网络模型调用成功。Python 不把 configRef 原样当作实际配置。
5. 启动失败可能先于 recorder / Agent，新增 evidenceFormatVersion 2 和 evaluationFormatVersion 2，允许 runId / sessionId / runDir / configuration 为 null，可选私有 runtimeReport。版本 1 保持严格兼容，不修改原录制协议；版本 2 正常任务重新核对日志全部请求头路由，不匹配不能通过。
6. case / evidence / evaluation / runtime 按新文件保存，不覆盖历史。runtime 记录阶段、监督器和私有异常细节；Node host-result 保留 CLI 版本、实际路由、流、退出码 / 信号和 childClosed。缺报告时仍保留已实施的超时事实，不伪造完成。
7. 正常任务才进入普通断言；未知路由是 runtime_error，超时和取消为 timed_out / cancelled，录制有效性独立保留。超时借用宿主 aborted/user 停止接口时仍记录 timed_out，不能因为日志封存或底层取消原因就判任务通过。

## 验证

2026 年 10 月 17 日，项目根目录，Windows / Python `3.12.0` / Node.js `v24.14.0`；CLI / session `0.2.0-rc.2`，Cordis `4.0.4`，模型任务 `deepseek-official / deepseek-flash`。

| 命令或操作 | 结果 | 证明的范围 |
| --- | --- | --- |
| `npm.cmd run check` | 25 个 JS 文件通过 | 含新宿主适配 / 控制插件 / 协议测试 |
| `npm.cmd test` | 39 项通过，0 失败 / 跳过 | 原 36 项 + 3 项 headless 协议边界 |
| `npm.cmd run test:python` | 获准环境 44 项通过 | 原 30 + 新 14；无模型的格式、文件环境、路由反例与真实进程监督 / 强停测试 |
| `python -m compileall -q dsh_eval test/test_runner.py test/test_evaluation.py` | 通过 | Python 语法 |
| `python -m dsh_eval --case fixtures/evaluation/live-read.case.json --run` | 新运行 passed / completed / complete / passed；25 条、42626 字节 | 实际 read、file_path 参数、callId 返回、答案与结束，完整单用例闭环 |
| 同入口，`--host-modules runs/nonexistent-host` | runtime_error / unverified / unevaluable；实际身份和配置 null | 真实准备错误，没有调用模型 |
| 新用例副本：provider=`eval-unregistered-provider`，其他同读取用例 | NO_ADAPTER，退出 1，18 条、36047 字节，sealed / inspect complete；runtime_error / unevaluable，断言 not_run | 实际未知路由拒绝，不算模型答案错误或成功网络请求 |
| 新用例副本：timeoutSeconds=2 | timed_out / aborted-user，18 条、35911 字节，sealed / complete，unevaluable | 本次任务在首 chunk 前超时，IPC 停止并正常清理；配置仍由请求头采集 |
| 同读取入口，加 `--cancel-after-stream` | cancelled / aborted-user，19 条、36336 字节，sealed / complete，unevaluable | 实际流 chunk 后程序化取消；不是手工页面取消，也不保证已执行工具 |
| 对上述正常 / 路由 / 超时 / 取消 PID 执行 `Get-Process -Id <本次PID> -ErrorAction SilentlyContinue` | 全部不存在，host childClosed=true、forceStopped=false | 本次专用 CLI 已退出，未假定任意外部工具树 / 其他平台均验证 |
| 无模型真实子进程测试：超时、流触发 cancel、无效协议 shutdown、超清理期限强停 | 监督器发送实际控制消息并等待退出；强停获准环境通过 | 不是模型任务；专用 test 子进程，失败时测试清理器仍回收本进程 |
| 版本 2 路由反例：同时改期望与清单，不改原始请求头 | unevaluable / insufficient_evidence | 不能仅改清单让不符配置通过，合成轨迹测试不代替真实任务 |
| `npm.cmd run smoke:host` | 6 条人工真实组件事件与封存通过 | 原组件接入回归，无模型 |
| `npm.cmd run check:output` | 获准环境 normal / write-error / abrupt-exit 均通过 | 真实子进程输出与既有 0 / 1 / 2 边界，未用 mock 替代 |
| 使用每次保存的 case.json / evidence.json 再次离线 evaluate | 正常仍 passed，其余分别 runtime_error / timed_out / cancelled，录制均 complete、断言 not_run | fresh inspect 与当前版本 2 逻辑复验，未新调用模型或覆盖历史结果 |
| `git diff --check`、提取 Markdown 相对引用后检查存在性及 git check-ignore、`git ls-files runs private-notes` | diff 通过；23 份公开、2 份私人 Markdown 共 101 个本地链接有效；公开目标无忽略依赖；runs / private-notes 无跟踪内容且忽略有效 | 文档与公开 / 私人隔离；仅有 CRLF 提示 |

首次真实运行在沙箱被 fork EPERM 阻止（未产生录制，不计通过）。首次获准正常任务仍为 unevaluable：fixture 将工具参数写为 path，实际宿主为 file_path，答案和录制正确也不能满足该断言；修正公开用例后创建新运行通过，旧结果保留。Python 强停测试也曾因沙箱拒绝 taskkill 失败；增加测试异常清理并在获准环境重跑后通过，没有跳过该测试。

复现真实异常时使用新副本修改上述单一字段，保留原用例；未来模型速度不同，超时副本也应以实际是否到达期限为准。使用每次运行输出的明确 caseRunId 和 case.json / evidence.json 进行离线复验，不依赖私人目录或“最新日志”。

## 风险与后续

- 真实任务与异常均限定当前 Windows / 固定组件和受控文件任务；没有验证 POSIX、桌面 / SDK、手工 Ctrl+C、Python 中途 OS 强杀或任意外部工具子进程树。相关兜底路径实现与验证分别描述。
- 墙钟预算包含启动和任务，准备 / 清理另计，不支持 token、费用或步骤预算。source、profile 与进程事实由适配器提供，本地事件不证明模型服务端实现；摘要不是签名，sealed 也没有 fsync 保证。
- 任务环境是普通初始文件，不是状态化工具模拟。下一批 M3.3 先做确定性 Python 环境，再做真实工具注册和实时请求 / 响应桥接，分别验证路径过时与暂时工具故障后恢复。M3.4 再实现隔离顺序批次。
- 没有计算成功率、性能、token 或成本改善，没有把这些少量正常 / 异常运行当作重复统计样本。

## 文档同步

已同步 README、进度、架构、M3 路线、格式、单用例说明、公开 fixture 说明、CHANGELOG。历史结果保留在对应记录；公开链接不依赖 runs 或私人材料。相对链接、Git 忽略 / 跟踪和差异空白检查通过。
