# 修改记录 026 M6.2 任务录制配置传递

日期：2026 年 10 月 23 日，Asia/Shanghai。类型：修复 / 测试 / 文档。插件版本：`0.1.2`。相关 Git 提交：本批尚未提交；开始 HEAD 为已核实的 `5777f2d`（M6.2），跟踪文件干净。M6.1 登记修复为 `2a22894`。没有自动提交、推送、触发云端 CI 或调用模型。

## 问题与目标

M6.2 的 maxEventBytes 默认 1 MiB，独立记录器和插件 config 可调高，但 Python 的单用例 / 批次 / 实验入口不接受录制参数。configRef 严格限定四个路由 / 版本字符串，隔离准备又新建 profile，不继承用户原 profile。因此合法的大工具结果在 --run 中只能受默认限制，无法按 README 建议显式调高。审查用同一 1.25 MiB 正文证明默认值下拒绝且 inspect invalid，显式 4 MiB 后可完整保存；本批保留原证据。

目标是把 maxEventBytes 与已有 maxPendingBytes 从任务用例传到冻结输入、新隔离 profile 的 eval-lab config 和实际 run.json，保持两个默认值、字段校验、模型实际路由及旧证据语义，不改调度或评测算法。

## 文件修改

| 文件 | 修改前 | 修改后 | 原因 |
| --- | --- | --- | --- |
| `dsh_eval/formats.py` | 拒绝用例顶层 recorder | 用例版本 1 / 2 接受可选 recorder，仅校验两个正安全整数，不修改输入 | 独立归属录制配置，复用现有冻结链路 |
| `scripts/case-host.js` | 新 profile 未设置录制限制 | 准备前校验，复用 src/config.js 解析默认值；profile 的 eval-lab config 与 setup.json.recorder 保存有效两值 | 真正接到隔离插件，禁止静默忽略非法值 |
| `test/case-recorder-config.test.js` | 无准备配置回归 | 四项 Node 回归 | 覆盖准备文件、独立默认 / 限制、非法值与大事件 |
| `test/test_recorder_options.py` | 无用例到准备的配置回归 | 六项 Python 回归 | 覆盖版本兼容、CLI、单用例 / 批次 / 实验冻结、模型覆盖保留及报告快照一致性 |
| `README.md`、`docs/recorder-resources.md`、`docs/evaluation-format.md` | 只说明底层可配置 | 说明任务入口、可选字段、优先级、冻结及核对方式 | 避免建议无法用于真实入口 |
| `docs/single-case-runner.md`、`docs/batch-runner.md`、`docs/experiments.md`、`docs/architecture.md` | 无对应传递约定 | 明确各层沿完整 case 保留，与模型配置分开 | 与实际责任边界一致 |
| `CHANGELOG.md`、`docs/progress.md`、`docs/plans/m6-reliability-validation.md` | M6.2 原验收 | 追加配置传递修复及当前验证 | 原历史结果不覆盖 |

保留 main.py、原用例、仓库 cordis.patch.yml、用户 profile 和既有调度 / 评测 / 报告实现。

## 实现与技术取舍

选择独立可选 case.recorder，而非扩展 configRef、全局 profile 或新增 CLI 覆盖。configRef / requestedConfiguration / evidence.configuration 继续只描述 provider、model、profile、pluginVersion；录制限制是该用例的执行输入。示例字段：

```json
"recorder": { "maxEventBytes": 4194304, "maxPendingBytes": 16777216 }
```

允许省略 recorder、空对象或部分字段；各字段显式声明优先于内置默认，缺省仍为 1048576 / 16777216。Python 要求 type 为 int、范围 1～9007199254740991，拒绝 bool、null、string、小数、非正和超安全范围整数；对象内未知字段也拒绝。Node 准备边界独立检查对象和允许字段，再复用已有 resolveConfig 的正安全整数及默认值，非法值在安装前失败。outputDir 仍由 runner 定位该次 traces，不允许用例覆盖。

validate_case 只验证，不填默认或改变原对象。单用例 case.json、批次 inputs / 执行快照、实验 inputs / expanded / 批次 / 执行快照都利用已有完整 case 保存。实验现有 `{**case, configRef: ...}` 只覆盖模型配置，不动 recorder；后续修改原用例不影响已经冻结的输入。没有新增 batch / experiment 顶层覆盖或配置维度。

prepareCase 在新隔离 profile 的覆盖层增加 `{id: "eval-lab", config: {maxEventBytes, maxPendingBytes}}`，保留安装 bundle 原有插件名称。setup.json 的附加 recorder 对象记录解析后的有效两值；插件按原方式从 config 创建记录器，实际 run.json 也保存两值。新冻结输入与有效配置可以逐层核对，没有修改用户全局文件或分发补丁。

省略和显式当前默认值运行时相同，但仍为不同的冻结输入。现有 report.py 已比较完整冻结 / 执行 case，并对非 configRef 字段计算指纹，故 recorder 自然参与一致性检查；新增回归证明改动执行快照中的录制值会被拒绝，无需修改报告或实际路由算法。离线评测不重新应用 recorder 声明限制历史日志，也不新增录制配置的自动 matched 结论。

两个用例版本均作可选字段扩展，格式编号保持；旧用例 / 旧证据不需要迁移。旧严格读取器会拒绝含 recorder 的新用例，需要升级；不得据此修改历史快照来通过新检查。

## 验证

运行日期 2026 年 10 月 23 日；Windows、Node.js v24.14.0、Python 3.12.0。四项新增 Node 在未修改生产实现时全部失败；最初五项 Python 中四项因 recorder 字段被拒而失败，一项非法输入测试通过。修复后均通过，再补 CLI 路径和省略 / 显式默认快照检查，最终六项 Python 通过。

| 命令或操作 | 结果 | 证明的范围 |
| --- | --- | --- |
| `node --test --test-isolation=none test/case-recorder-config.test.js` | 四项通过 | 生成 profile / setup、默认 / 部分配置、独立两值、非法参数安装前拒绝、使用生成配置保存大事件 |
| `python -m unittest discover -s test -p test_recorder_options.py -v` | 最终六项通过 | 用例版本 1 / 2、严格值域、不混入 configRef、CLI 到快照、单用例 / 批次 / 实验冻结及模型覆盖、报告拒绝变更、历史输入不归一化 |
| `npm.cmd test` | 完整 79 项通过，无跳过 | Node 生产、配置、录制、inspect 与既有宿主边界回归 |
| `npm.cmd run check` | 36 个 JavaScript 文件通过 | 新旧 JS 文件语法 |
| `python -m unittest discover -s test -p test_evaluation.py -v` | 36 项通过 | 原离线证据与任务门禁 |
| `npm.cmd run test:python` | 获准环境首次 143 项通过；最终新增第六项后完整 144 项通过（41.733 秒） | 最终 Python 测试版本及原真实子进程 / 强停回归，没有模型调用 |
| `python -m compileall -q dsh_eval test` | 通过 | Python 编译检查 |
| 真实离线安装、真实 CLI `--profile headless --dump-config`、真实 Cordis / SessionStore 组件 | 三组通过，详见下表 | profile 修改确实合并到已安装 eval-lab 条目，再用合并后配置挂载组件，不启动 headless 模型任务 |
| 公开相对链接、`git diff --check`、忽略与跟踪核对 | 46 份 Markdown / 300 个相对链接有效；diff 检查通过；runs / private-notes 均忽略且无跟踪文件 | 公开文档不依赖私人材料或原始日志，共 15 个公开修改 / 新增文件 |

Node 单元测试仅隔离安装边界，仍写真实 profile / setup；Python 冻结测试在准备阶段明确停止，不能当成真实模型运行。真实安装与配置合并另行执行：每组先用实际 prepareCase / 离线 CLI 安装到新 home，dump-config 使用真实 Harness 的 bundle / profile 合并算法、保留 eval-lab 原插件 name；从合并条目读取配置，挂载真实 Cordis 4.0.4 / SessionStore 0.2.0-rc.2 并注入人工工具事件，再核对 setup、profile、合并树、run.json、状态和 inspect。

| 用例声明 | 有效 maxEventBytes / maxPendingBytes | 同一 1.25 MiB 正文 | 状态 / inspect |
| --- | --- | --- | --- |
| 省略 recorder | 1048576 / 16777216 | EVENT_BYTES_LIMIT；前三条小事件仍保留 | failed / 1 |
| 4 MiB 单条、8 MiB 队列 | 4194304 / 8388608 | 大事件完整写入，累计四条 | sealed / complete / 0 |
| 4 MiB 单条、1 MiB 队列 | 4194304 / 1048576 | PENDING_BYTES_LIMIT；前三条小事件仍保留 | failed / 1 |

真实配置合并子进程首次在沙箱 spawnSync EPERM，未计为通过；在获准环境执行相同验收后成功。首次不含合并检查的实际准备 / 组件验证也保留为独立范围，不混写成完整接线验证。原失败、原审查证据和新验证各用新目录，不覆写历史。

本轮未重跑八类资源测量、check:output 四场景、旧模型样本或云端 CI；这两处生产修改不改变记录器本体、输出通道和测量算法。上述验证分别说明格式、冻结、真实配置合并和组件行为，不宣称真实模型端到端任务通过。

## 风险与后续

默认单条 1 MiB / 待写 16 MiB 策略保持，超限仍失败且不截断；调高单条上限后仍可能被独立队列上限拒绝。两个字段不是总内存、文件总量、会话数、CPU 或费用硬限额；历史资源测量局限保持。

录制配置属于用例，实验 configurations 只覆盖原模型 configRef；没有 CLI override、录制配置自动匹配或任意插件配置入口。若后续需要这些能力，应单独定义冻结与审计语义，不能通过用户全局 profile 临时补丁绕过当前输入。

下一批仍是 M6.3：先明确实际配置、固定用例与模型调用预算；M6.4 Web 生命周期仍计划。本批没有新模型调用、提交、推送或云端运行。

## 文档同步

更新 README、CHANGELOG、progress、architecture、资源说明、评测格式、单用例 / 批次 / 实验说明和 M6 方案；025 的历史验证不覆盖，公开资料不链接原始日志或私人材料。
