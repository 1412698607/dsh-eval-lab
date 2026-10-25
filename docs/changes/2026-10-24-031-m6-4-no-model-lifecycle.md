# 修改记录 031 M6.4 验收脚本与无模型检查

日期：2026 年 10 月 24 日，Asia/Shanghai。类型：功能 / 测试 / 文档。插件版本：`0.1.2`。相关 Git 提交：基线 `2c60b638d437b2d2b6afd09830bef5e147937924` 已核实，本批尚未提交。

## 问题与目标

用户要求继续 M6.4，先实现验收脚本和无模型检查。已有 M2.3 Web 关闭依赖专用 IPC，取消通过 Agent API 程序化执行，尚未覆盖实际页面取消或普通宿主信号退出。本阶段先固定三个场景的判定与失败行为，在无模型条件下验证实际子进程、录制器和 fresh inspect，后续再接入真实 Web 观察与页面操作来源。

开始时实际分支为 `20261024/feat/m6-4-web-lifecycle`，HEAD 为 `2c60b63`；030 的 CHANGELOG / progress 修改与新记录已有未提交内容，本批保留。030 中创建分支名称是历史，本次不改写该记录。

## 文件修改

| 文件 | 修改前 | 修改后 | 原因 |
| --- | --- | --- | --- |
| `fixtures/evaluation/web-lifecycle.case.json` | 无独立 Web 固定任务 | 版本 1 Web fixture、必要读取 / 答案 / completed 断言 | 为脚本冻结明确输入 |
| `scripts/check-web-lifecycle.js`、`scripts/fixtures/web-lifecycle-child.js` | 无独立三场景采集 | 新目录、真实专用子进程、原录制器、检查点和退出事实 | 将实际文件 / 进程事实与合成事件分开 |
| `scripts/verify_web_lifecycle.py`、`scripts/check_web_lifecycle.py` | 无 M6.4 离线验收及命令 | 严格清单、fresh inspect、场景 / 任务分类、新结果不覆盖 | 拒绝缺证据和旧报告假阳性 |
| `test/test_web_lifecycle.py` | 无新阶段回归 | 17 项事件 / 格式 / 真实进程和损坏反例 | 核对成功、取消、中断及失败边界 |
| `package.json`、`.github/workflows/deterministic.yml` | 无入口；compileall 不含 scripts | 新增 check:web-lifecycle；scripts 纳入 Python 编译检查 | 提供本机入口并覆盖新增 Python 文件 |
| `README.md`、progress、architecture、M6 方案、Web 生命周期说明、CHANGELOG | M6.4 仅计划 | 更新脚本与无模型阶段及实际 Web 未验收范围 | 文档与实际实现一致 |

本机交接与面试材料另行同步，私人文件不作为公开依赖。原 src、通用 runner / evaluate / report、M2.3 脚本与 main.py 没有修改。

## 实现与技术取舍

JavaScript 为每个场景创建独立 case.json / workspace / traces，fork 一个只依赖 Node 和原 recorder 的 fixture，不加载 Harness、模型适配器或凭据。正常场景实际读取 README，工具与答案事件仍为合成；取消通过 synthetic-cancel 让 fixture 追加 aborted/user；处理中断先等待 flush 后的检查点，再 SIGKILL 父脚本自己创建的进程。记录 afterSeq 和实际 close、退出码 / 信号、强停及干预来源，超时不能冒充预期中断。

Python 使用独立 webLifecycleFormatVersion 1 捕获协议及验证版本 1，不扩展通用 evidence。先严格验证格式、来源和进程事实，再重新调用既有 Node inspect，核对运行 / 会话身份及状态，读取连续的匹配任务。正常任务复用 task_view / check_assertions；取消和中断分别保持 cancelled / interrupted、任务 unevaluable 和断言 not_run，不用最终答案要求阻止合法取消。

只接受 synthetic，liveWebVerified 始终 false。暂不实现真实 Web 启动或操作采集，避免把旧测试 IPC、fixture 自然退出或构造的取消事件误算为实际 Web 验收。中断正例当前限定干净开放前缀；invalid、文件缺失和 inspect 不可用均不能作为中断通过证据。输出目录 / 验证文件采用新建模式，复验另存结果，不覆盖原文件。SHA-256 与本地过程清单均不是签名。

## 验证

在当前 Windows、本机 Node / Python 环境执行。所有本批检查均无模型调用，未启动真实 Web 服务。

| 命令或操作 | 实际结果 | 范围 |
| --- | --- | --- |
| `python -m unittest discover -s test -p test_web_lifecycle.py -v`，首次沙箱 | 7 项事件规则通过；setUpClass 的三次 fork 均 EPERM，整体失败 | 明确保留子进程验证限制，不算通过 |
| 同一命令，获准环境 | 17 项通过，1.028 秒 | 事件与格式边界、真实子进程 / recorder / fresh inspect |
| `npm.cmd run check:web-lifecycle -- runs/web-lifecycle/<new-check>`，获准环境 | 三个独立进程场景均 verified | 实际输出目录由本机交接记录；合成事件不是实际 Web 操作 |
| `npm.cmd run test:python`，获准环境 | 完整 180 项通过，48.692 秒 | 原 163 项及新增 17 项；真实进程清理回归 |
| `npm.cmd test` | 79 项通过，无失败 / 跳过 | 既有 Node 回归 |
| `npm.cmd run check` | 38 个 JavaScript 文件通过 | 原 36 及两个新增脚本 |
| `python -m compileall -q dsh_eval scripts test` | 通过 | 包括新增脚本的 Python 语法 |

独立入口的正常场景为 completed / complete / passed，取消为 cancelled / complete / unevaluable，中断为 interrupted / unverified / unevaluable；后两项断言均 not_run，所有 liveWebVerified 均 false。验证器不读取旧 verification 作为通过条件；截断已通过轨迹、删除整对文件、重标已封存成功、错误输入 / 取消原因 / 工具参数、缺工具结果、超时和无法 inspect 均有拒绝回归。

没有重跑历史真实模型、M2.3 Web、smoke:host / check:output、资源测量或云端 CI；其历史结果保留，不计入本批实测。

最终定向核对：54 份公开 Markdown / 356 个相对文件链接有效，没有链接私人材料或运行输出；本批新增 / 修改文件末尾换行及空白检查通过，progress 分支与实际 Git 一致。三个已保存场景再经独立 Python CLI 重新检查均符合预期，28 份原检查文件摘要保持不变。三个保存的专用子进程 PID 再查均不存在，不推定任意外部进程树均已清理。`git diff --check` 通过，仅有 LF / CRLF 提示；runs / private-notes 仍忽略且无跟踪文件，原 src、dsh_eval、M2.3 脚本和 main.py 的 Git 差异为空。

## 风险与后续

本阶段仅交付脚本与无模型检查，M6.4 真实 Web 生命周期仍未验收。下一步需要真实 Web 启动、只观察生命周期的采集器、页面动作来源和实际平台退出路径；随后按另定配置与数量执行任务。Windows child.kill('SIGINT') 不能证明正常退出，旧测试 IPC 关闭也不能替代普通宿主信号路径。

当前 fixture 的自然退出、手工追加事件及专用 SIGKILL 不代表真实模型行为、任意外部进程树、断电可靠性或可恢复日志。10 秒监督兜底与 30 秒 fixture 孤儿保护不执行 case 的 timeoutSeconds，也不是费用预算。双配置与重复扩展仍待配置及预算。

## 面试讨论点

如何将“场景检查通过”与“任务成功”分开；为什么取消任务可以拥有完整录制但任务仍无法评测；为何强停前先等待已写检查点；为什么 inspect 报错或缺文件不能自动当作成功中断；如何明确合成事件、真实文件 / 进程和实际页面 / 模型行为各自证明的范围。

## 文档同步

同步 README、progress、architecture、M6 方案、新 Web 生命周期说明、CHANGELOG 及本机交接 / 面试材料。保留 030 及既有验证历史；本批未提交或推送。
