# M3.2 单用例真实运行

日期：2026 年 10 月 17 日，Asia/Shanghai。已实现 Python 单用例调度和 JavaScript Harness 适配，插件保持 `0.1.2`。本批在 Windows / Python 3.12.0 / Node.js v24.14.0、CLI / session `0.2.0-rc.2`、Cordis `4.0.4` 验证；没有据此推定其他平台或渠道通过。

## 运行与结果

在仓库根目录执行；以下入口会调用用例指定的真实模型：

```powershell
python -m dsh_eval --case 'fixtures/evaluation/live-read.case.json' --run
```

使用已安装的匹配版本宿主，默认在 Windows npm 缓存查找，也可用 `--host-modules '<已安装宿主的node_modules>'` 明确指定。不会自动下载或更新宿主。每次通过实际 CLI 的 `plugin add link: --offline --ignore-scripts` 安装本地插件到新 home，独立 pnpm store；凭据只引用原 `DSH_HOME`（未设置时为用户 `.dsh`）下的凭据文件路径，不复制密钥或改动原 profile。只支持 headless，默认公开用例为 `deepseek-official / deepseek-flash`。

Python 生成新 caseRunId，保存用例快照、在独立 workspace 写入初始文件，校验 Windows 保留文件名、大小写和文件目录冲突，再调用 Node 准备及运行。宿主使用 read-only 策略，测试用例要求实际 read，参数键为该版本的 `file_path`。不注入答案，不重写 Agent 循环；任意其他工具名 / 参数仍须由相应用例正确声明。

默认输出为 `runs/evaluation/<caseRunId>/`，可用 `--runs-root <父目录>` 改变父目录；运行内部只创建新的 UUID 子目录，不复用工作区或覆盖旧结果。

```text
<caseRunId>/
  case.json                  完整版本 1 / 2 用例快照
  workspace/                 实际初始文件；状态化环境下为空
  home/                      独立 headless profile / session 存储
  pnpm-store/                独立离线安装 store
  setup.json                 本次 CLI / 组件与路径
  control.patch.yml          专用控制插件
  prepare.stdout.log / prepare.stderr.log
  adapter.stdout.jsonl / adapter.stderr.log
  stdout.jsonl / stderr.log  实际 Harness 输出
  traces/<runId>/            原有 run / JSONL / status
  host-result.json           Node 的实际退出、路由、流与清理观察
  runtime.json               Python 阶段、监督器与私有错误信息
  evidence.json              版本 2 清单，允许启动前缺失的事实为 null
  evaluation.json            版本 2 评测结果
```

启动早期失败时部分文件不会存在，不补造会话或录制编号。命令 stdout 为 JSON 结果，退出码仍为 `0` passed / `1` failed / `2` unevaluable 或输入错误。`--run` 自动保存结果，不与 `--output` / `--evidence` 同用。离线复验使用此次目录中的 case.json / evidence.json：

```powershell
python -m dsh_eval --case 'runs/evaluation/<caseRunId>/case.json' --evidence 'runs/evaluation/<caseRunId>/evidence.json'
```

不能用后来改过的公共用例代替历史运行快照。原始内容和本机配置均只保存在已忽略 runs；不要把这些目录作为公开仓库依赖。

## 预算、取消与清理

- 准备阶段由 Python 单独实施 150 秒上限；任务预算从运行适配进程创建后开始，覆盖 Harness 启动和任务执行，不包含离线安装与最终 inspect。
- `budget.timeoutSeconds` 是任务墙钟时间。达到期限后 Python 发 timeout，Node 通过 IPC 请求 Agent 停止 / idle / flush；仍未退出时，Node 10 秒后尝试强停专用 Harness 子进程，Python 15 秒后尝试终止自己创建的整个适配进程树。清理还有独立等待，总退出时间可超过任务预算；不是 token、费用或步骤上限。
- 工具响应和控制帧由独立写线程串行写入，监督循环只入队。若响应阻塞，timeout / cancel 仍会记录；控制帧不能穿插进半条 JSONL，清理期限后仍尝试终止自有进程树。stdin 由写线程关闭，回收后记录 supervisor.stdinWriterStopped；超时后的管道写入错误不覆盖超时分类。详见 [修复记录 014](changes/2026-10-18-014-m3-3-review-fixes.md)。
- Windows 最后手段使用精确的本次进程 PID 和 `/T /F`，仅针对自己仍持有的运行进程；不按名称终止其他实例。权限拒绝时不能宣称树清理成功。POSIX 分组路径已实现，但本批未验证该平台。
- `--cancel-after-stream` 在首个模型请求流 chunk 通知后发送 cancel，适用于受控取消验收；chunk 可能是块边界，不保证已产生文本或执行文件工具。Python Ctrl+C 请求取消路径已实现，本批未单独做手工按键验收。
- 控制插件复用 M2.3 的 IPC 生命周期行为，父控制流断开时请求停止；本批没有单独验证运行中的 Python 被 OS 强杀。

```powershell
python -m dsh_eval --case 'fixtures/evaluation/live-read.case.json' --run --cancel-after-stream
```

超时导致 turn/end aborted/user 时执行状态仍为 timed_out，保留预算干预事实；显式取消需要相符的 aborted/user 才归 cancelled。它们即使日志 sealed / inspect complete 也都是 unevaluable，断言 not_run。运行 / 路由错误亦单列，不作为模型答案错误计数。

## 配置证据与失败边界

专用插件在 agent/created 观察实际默认选择，在 request/header 观察具体 provider / model；配置由观察结果生成，不能直接复制 configRef 当作实际路由。离线版本 2 再检查原始日志中所有 request/header 路由与清单一致，并与用例期望比较。未知 provider 的请求头只证明尝试该路由，不证明有可用适配器或调用了网络模型。

如果尚未进入请求、没有唯一可观察路由或不存在录制器，对应配置 / runId / sessionId / runDir 可以为 null；completed 缺少唯一实际路由会转 runtime_error。模型服务端实际实现仍不由这些本地事件独立证明。协议、预算实施和来源是明确适配器范围的证据，封存和摘要不是签名。

以下反例可在新用例副本中分别复现，原用例不修改：

| 操作 | 当前结果和实际验证 |
| --- | --- |
| `--host-modules '<不存在的node_modules>'` | 准备错误，runtime_error / unverified / unevaluable；实际录制与会话 ID 为 null |
| 将副本 configRef.provider 改为 `eval-unregistered-provider` | 实际 NO_ADAPTER、Harness 退出 1、录制 complete，任务 unevaluable / 断言 not_run |
| 将副本 budget.timeoutSeconds 改为 2 | 本批在流 chunk 前到达期限，timed_out、aborted/user、正常封存、专用进程退出；更快的未来运行可能在期限前完成，应保留实际结果 |
| `--cancel-after-stream` | 本批实际 chunk 后取消，cancelled、aborted/user、正常封存、专用进程退出 |

首次沙箱 fork EPERM 和测试中的进程树终止权限拒绝不计通过，获准环境重验后才取得真实证据。首次正常任务因 fixture 把工具参数误写为 path，答案及录制正确但无法证明所声明参数，因此 unevaluable；修正为实际 file_path 后新运行 passed，旧结果保留。

## 下一批与限制

M3.2 验证了一条受控真实文件任务及上述异常路径。M3.2 当时没有状态化工具环境或实时 Python 工具桥接；M3.3 已补齐，批次调度和重复试验仍未实现；公开合成演示仍是 M3.1 离线输入。工具环境和真实桥接见下方 M3.3 扩展，下一批 M3.4 实现顺序隔离批次，再做 M4 重复比较和 M5 浏览 / CI。详见 [路线](plans/m3-regression-evaluation.md)、[格式](evaluation-format.md) 和 [修改记录 011](changes/2026-10-17-011-m3-2-single-case-runner.md)。

## M3.3 状态化扩展（2026 年 10 月 18 日）

单用例入口现支持版本 2 状态化用例。Python 在监督循环内即时处理工具请求，Node 转发专用 IPC；状态化环境的文件不写入 workspace。路径、错误、取消和复现命令见 [状态化工具与桥接](stateful-tools.md)。原有 M3.2 历史验证范围保留。
