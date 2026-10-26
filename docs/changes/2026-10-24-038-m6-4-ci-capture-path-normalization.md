# 修改记录 038 M6.4 CI 采集目录规范化修复

日期：2026 年 10 月 24 日，Asia/Shanghai。类型：修复 / 测试 / 文档。插件版本：0.1.2。相关 Git 提交：尚未提交；已核实 HEAD 为 `103c090b94297442c15a1f38173297a3e550004d`。035 至 037 的未提交改动全部保留，历史修改记录不改写。

## 问题与目标

读取 [run 40075970788 / job 120819263425 的失败日志](https://github.com/1412698607/dsh-eval-lab/actions/runs/40075970788/job/120819263425#step:7:16)，定位 Python 失败并作针对性修复，不运行真实模型。

已登录网页的实际堆栈显示：196 项 Python 测试运行 57.720 秒，只有 test_live_tail_policy_still_requires_operation_checkpoint_coverage 报错。该测试直接调用 verify_recorded_task，在 `run_dir.resolve().is_relative_to(directory)` 处抛出 Trace directory escapes the capture，并未执行到其预期的检查点断言。036 的初始化清理 / 时间门禁修复没有修改这个共享函数，因此不能解决该处路径表示不一致。

## 文件修改

| 文件 | 修改前 | 修改后 | 原因 |
| --- | --- | --- | --- |
| scripts/verify_web_lifecycle.py | 共享函数只解析子目录，父目录依赖调用者预先解析 | 在函数入口增加一行 Path(directory).resolve() | 直接调用与外层 CLI 使用同一种父路径表示 |
| test/test_web_lifecycle.py | 缺共享函数直接接收别名 / 非规范化父目录的覆盖 | 新增 3 项：真实目录别名、via/..、真实子目录别名逃逸 | 稳定复现并保留实际边界检查 |
| README、CHANGELOG、progress、architecture、Web 指南及 M6 方案 | 云端根因未知 / 等待日志 | 记录实际堆栈、规范化修复和本地验证 | 不把本地修复写成云端已通过 |
| 本记录 | 无本批记录 | 保存修复依据、范围、验证与下一入口 | 公开资料不依赖私人日志 |

## 实现与技术取舍

例如显式采集目录 capture-alias 是 capture-real 的 junction：子目录 resolve 后位于 capture-real/traces，父目录仍写作 capture-alias，词法 is_relative_to 会误报越界。共享函数自身没有统一输入，只有 verify_launch / verify_live 两个外层入口会预先 resolve；测试直接调用该函数，因此能暴露这个缺口。

本轮只在共享函数入口规范化父目录，保留子目录 resolve 后的真实包含关系检查。没有删除守卫、缩小用例、将错误改为通过，或放宽版本 / 会话 / 非空检查点 / afterSeq 规则。指向真实采集目录之外的 traces junction 仍在 inspect 之前被拒绝。外层入口原有固定相对 runDir 与关联校验不变，录制器 / inspect / dsh_eval / M2.3 / main.py、JSON 格式与版本均不改。

新增回归用 Windows 实际目录 junction（其他平台用目录符号链接），不依赖磁盘是否启用 8.3 文件名。正常、取消、中断各覆盖 strict / live-tail 两种策略；另外验证等价 via/.. 父路径，以及 traces 解析后实际越界时必须拒绝。链接在测试结束时直接移除，不递归删除其目标。该次云端堆栈未打印临时目录的具体短名，因此不将某个 RUNNER~1 字串记作本次实测；本地真实别名和非规范化路径已复现同一守卫错误。

## 验证

本轮不启动真实 Harness / Web 服务，不调用模型，不触发新的云端任务。日志通过作业日志页面读取，只保存可见失败堆栈摘录，不提取 Cookie、token 或凭据；037 的匿名访问失败与根因未知保留为当时状态。

| 命令或操作 | 结果 | 证明的范围 |
| --- | --- | --- |
| 已登录的原失败 job 页面 | 196 项 / 57.720 秒 / errors=1，堆栈定位共享函数第 94 行 | 103c090 的实际云端失败，不是本地模拟结果 |
| `python -m unittest discover -s test -p test_web_lifecycle.py -k shared_helper -v`，修复前 | 获准环境运行 3 项，合法别名 / 非规范化父路径共 7 个错误，真实逃逸拒绝通过 | 用真实 junction 稳定复现；没有 mock 文件解析或进程 |
| `python -m unittest discover -s test -p 'test_web_*.py' -v`，修复后 | 获准环境 39 项通过，2.758 秒 | 原 CI 失败用例及新别名 / 逃逸、既有生命周期 / live 元信息回归 |
| `npm.cmd run test:python` | 获准环境 202 项通过，48.113 秒 | 完整 Python 回归，含真实合成进程、junction 与本地回环服务 |
| `npm.cmd run check:web-lifecycle -- <全新目录>` | 三场景 verified=true、source=synthetic、modelCalled=false、liveWebVerified=false | 原录制器与真实专用合成进程，正常 passed，取消 / 中断 unevaluable |
| `python -m compileall -q dsh_eval scripts test` | 通过 | 当前 Python 语法 |

收尾核对通过：61 份公开 Markdown / 413 个相对文件链接、包含 035 至 038 的 18 个未提交文件范围及换行 / 空白、分支 / HEAD 和忽略规则一致，337 份受保护旧代码 / 记录 / 原始证据摘要未变。三个独立合成场景的明确自有 PID 46352 / 43660 / 47028 均已不存在；runs 与 private-notes 无跟踪文件。`git diff --check` 通过，仅提示后续 LF / CRLF 转换。本轮未继续改动 JavaScript，036 的未提交改动保留，不重复其 85 项 Node / 41 JS 语法；这些历史结果不计为本轮新验证。

## 风险与后续

本地已修复共享函数的路径规范化缺口，实际云端运行仍是上述失败记录；需要包含 035 至 038 修复的新提交再验收云端，不能将本地通过冒充新的托管运行通过。本轮没有提交或推送。035 / 036 / 037 及原始 live 证据保留；双配置 / 重复与其他平台 / CLI / desktop / SDK 未扩展，取消 / 中断任务结论不升级。

## 文档同步

同步 README、CHANGELOG、进度、架构、Web 生命周期、M6 方案。保留历史记录，公开资料不链接本机原始日志或私人文件；CLI、数据格式和录制语义保持不变。
