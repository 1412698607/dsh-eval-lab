# 修改记录 143 受控工具任务内调用预算

日期：2026年11月16日，Asia/Shanghai。类型：功能、修复、测试、文档。插件版本：0.1.2。相关Git提交：尚未提交；开发起点为已核实的 `ff7428512cfc208ded461136023cafe2611cc651`。

## 问题与目标

既有tool_call_count断言在执行后判断录制调用是否符合要求，不能在运行中阻止后续操作。新增可选budget.maxToolCalls，在Python状态化环境接纳合法新请求前限流；超过上限时拒绝操作、取消未提交工作并停止本次任务。范围仅为项目自有受控工具桥接，不是宿主全部工具、模型调用、token或费用上限。

## 文件修改

| 文件 | 关键修改 | 原因 |
| --- | --- | --- |
| dsh_eval/environment.py | 接纳与执行分离，唯一请求预算、缓存去重、拒绝及取消pending、五字段快照 | 在副作用前限制次数，避免重送重复扣减及poll重复收费 |
| dsh_eval/formats.py | case v2 stateful可选非负安全整数maxToolCalls，enforcement布尔和budget_exceeded状态 | 保持输入严格校验与可选扩展 |
| dsh_eval/runner.py | 拒绝响应与tool_budget控制顺序、预算状态保存、清理和分类 | 预算停止不变成普通成功、用户取消或后续清理错误 |
| dsh_eval/evaluate.py | completed预算证据与运行停止原因一致性检查 | 缺标记、摘要、策略或矛盾收据不能被答案掩盖 |
| dsh_eval/web/app.js | 显示工具次数预算超限及警示状态 | 保存结果可区分预算与墙钟超时 |
| scripts/case-host.js、scripts/fixtures/mutation-adapter.js | 传递预算停止，合成记录拒绝并正常封存 | 真实父子进程控制与合成路径保持统一分类 |
| scripts/fixtures/tool-budget-ipc.js、test/tool-budget-ipc.test.js | 真实fork、生产case-host、共享桥接和注册工具体 | 验证Promise拒绝、abort / close、监听器和实际子进程回收 |
| test/test_tool_budget_environment.py、test/test_tool_budget_formats.py、test/test_tool_budget_runner.py | 环境、格式、记录与IPC反例 | 校验0 / N / N+1、失败不退款、去重、无副作用、证据一致性 |
| 工具预算说明、状态化工具、评测格式、运行说明、README、架构、能力、进度、CHANGELOG | 同步字段、语义和验证边界 | 不将当前候选和历史真实模型 / CI验收混为一谈 |

## 关键逻辑与技术取舍

maxToolCalls省略时不补默认值；配置时仅允许caseFormatVersion=2且存在stateful，取值0至9007199254740991，拒绝bool、小数和未知字段。字段属于完整冻结case，沿既有输入指纹传递，不改变旧指纹版本或历史快照。

计数在协议、身份、启用操作及参数结构校验之后，对新requestId、进入pending之前发生；同步handle入口也经过同一接纳逻辑，已有pending不能用handle绕过延期。相同请求重送复用pending或缓存，冲突内容仍拒绝。失败、超时、取消都不退名额。结构合法但INVALID_PATH / NOT_FOUND等业务失败已经占用名额；Host在工具体之前拒绝的参数没有到达桥接，不占用名额。

恰好接纳N次不立即停止；第N+1个合法新请求产生TOOL_CALL_LIMIT_EXCEEDED和专用errorCode，缓存拒绝、标记exhausted，立即cancel_all未提交pending，不改变文件、临时故障次数或拒绝工具的延迟索引。已完成修改不回滚。监督器将拒绝响应排在tool_budget控制之前；写线程允许该拒绝通过，抑制其他停止后的结果；已排队的新请求不再启动工作。

停止沿case-host原取消通道进入子进程，runtime保留独立tool_budget原因。执行状态为budget_exceeded，任务unevaluable、断言not_run；即使录制complete或文件恰好正确也不通过。缺host报告时保留已发生的预算原因；先发生的任务超时 / 取消不被后续预算改写。现有清理宽限与最终进程树回收保持，不宣称总退出硬时限或保证任意宿主一定在停止前录制拒绝结果。

配置预算时新增budgetEnforcement.maxToolCalls及snapshot / supervisor中的toolCallBudget，含版本、limit、admitted、rejected、exhausted。快照参与原environmentSnapshotSha256与输入 / 身份绑定；completed必须有一致收据、admitted不超限、rejected=0、exhausted=false、host / supervisor无停止干预。未配置时不新增这些预算字段。摘要用于一致性核对，不认证一组被同时重写的材料。

开发复查修正了两项问题：最初错误地要求接纳数等于录制tool/call数，现移除该约束；真实dsh-tools参数校验探针确认缺path时在bridge之前抛ToolArgsError，合法重试才调用bridge一次。新增合成回归保留4条录制调用、3次接纳且正常通过。另补齐completed声明与runtime停止原因矛盾的检查，防止receipt计数正常但实际已tool_budget停止仍通过。原行为次数断言保持录制意图计数语义，两者不互换。

## 验证

Windows、Python3.12.0、Node.js v24.14.0。全部验证无模型调用；真实fork IPC使用轻量CLI夹具，defineTool采用直接返回定义的函数，不加载Harness runtime。真实dsh-tools 0.2.0-rc.2探针另行验证参数检查时点，只调用工具对象，不运行Agent或模型。

| 命令或操作 | 实际结果 | 范围 |
| --- | --- | --- |
| python -m unittest discover -s test -p 'test_tool_budget*.py' -v（允许真实子进程环境） | 最终30项 / 17.498秒通过，无跳过 | 15环境、6格式、9监督与证据检查，含真实管道 / fork IPC和桥接前参数拒绝反例 |
| node --test --test-isolation=none test/tool-budget-ipc.test.js test/tool-bridge.test.js | 12项 / 0.480秒通过，无跳过 | 新增正常abort及close两种真实fork清理、拒绝传输与旧桥接行为 |
| 既有environment / stateful_writes / stateful_mutations / evaluation.FormatTests | 48项 / 8.900秒通过，无跳过 | 既有写删改、超时、实际子进程及续跑相关兼容 |
| 实际dsh-tools参数探针 | 缺path抛ToolArgsError且bridge调用0次；随后合法参数成功，bridge累计1次 | 真实组件与录制意图 / 接纳计数边界，无模型 |
| 独立持久化IPC验收：maxToolCalls=1、编辑延迟3000ms、并发删除 | budget_exceeded / unevaluable / complete / not_run；admitted=1、rejected=1；最终文件与初态完全相同 | 首项未提交编辑被取消，第二项删除未执行；两个pipe worker、Promise、监听器与真实子进程均收尾，未强停 |
| npm.cmd test；npm.cmd run check | 完整167项Node / 8.981秒、0失败 / 取消 / 跳过；47个JS文件语法通过 | 当前冻结源码的完整Node回归 |
| npm.cmd run test:python（允许真实链接 / 子进程环境） | 完整703项 / 554.612秒，OK，无跳过 | 新预算30项及原全部Python回归 |
| python -m compileall -q dsh_eval scripts test | 退出0 | 当前Python编译检查 |
| 公开相对链接 / 锚点、git diff --check和冻结清单 | 10份变更文档667个链接 / 锚点及补丁检查通过；175份代码 / 测试 / 配置字节保持 | 内联代码中的示例字符串不作为真实链接；没有在完整回归中途改源 |

完整回归后仅追加文档结果，未改变已验源码、测试和配置。独立代码 / 文档复核未发现未处理的确认问题；原始产物与私人资料仍为忽略内容，不加入公开仓库。

首次JS定向受spawn EPERM限制，不能计为通过；允许真实进程环境后上述12项通过。文档命令一次在默认沙箱执行30项 / 17.707秒为29通过、1个IPC组合失败；另用相同输入保存复现，host明确为EPERM: spawn EPERM、childPid=null、预算接纳0。允许环境的独立持久化验收随即通过，失败与成功输出分开保留。首次使用test.test_*模块形式遇到标准库test包遮蔽，只产生导入错误，改用discover后运行上述测试；没有修改产品规则掩盖这些限制。

## 限制与后续

没有新增真实模型验收、正式Harness Agent规划 / 重试验收或新CI。预算覆盖Python实际接纳的自有受控请求，不覆盖原生文件工具、shell、外部服务等旁路。已完成的操作保留；仅保证本受控环境未提交操作在超限取消后不再生效。pending、去重和预算状态属于当前进程，不支持崩溃后恢复余额。

本批尚未提交推送。旧真实轨迹、精确断言及公开演示既有矩阵不改写；当前新合成结果不继承已交付提交的CI。用法与字段见[任务内受控工具预算](../tool-call-budget.md)。

## 文档同步

README、架构、状态化工具、单任务运行、评测格式、能力矩阵与进度增加本功能及明确边界，CHANGELOG链接本记录。已有阶段的历史“尚未实现”保留当时含义，当前能力只声称受控桥接次数上限，不扩大为所有Agent步骤预算。
