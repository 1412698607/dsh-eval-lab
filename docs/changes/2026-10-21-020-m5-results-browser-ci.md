# 修改记录 020 M5 本地结果浏览与无模型 CI

日期：2026 年 10 月 21 日，Asia/Shanghai。类型：功能 / 配置 / 测试 / 文档。插件版本：`0.1.2`。相关 Git 提交：本批尚未提交；基线 M4.2 为已核实的 `b0de80c`，经 `1725c51` 合并。当前分支 `20261011/feat/results-browser-ci`，开始时工作区干净；旧记录 019 的“尚未提交”为当时状态。

## 问题与目标

M4 已有完整 JSON / Markdown 及原始证据，但查看一次实验需要手工打开多层文件，容易混淆整体分母、实际配置、保存结论与复验结果。公开仓库也没有可在干净环境运行的自动检查入口。

本批提供本机只读结果页面，从用例 / 实验 / 报告进入逐次结论和原始轨迹，保留已有数据语义，再将无模型确定性检查接入 CI 配置。页面只读取保存的结果，不执行任务，也不自动重新验证历史成功。

## 文件修改

| 文件 | 修改前 | 修改后 | 原因 |
| --- | --- | --- | --- |
| `dsh_eval/browser.py` | 无本地浏览服务 | Python 标准库 HTTP、目录索引、关联文件、JSONL 分页与访问边界 | 复用本地 JSON / 证据，不引入后端框架或数据库 |
| `dsh_eval/web/index.html`、`style.css`、`app.js` | 无浏览界面 | 五类列表、搜索 / 筛选、三维状态、分母 / 配对覆盖 / 指标表、证据跳转和文本详情 | 让结果可浏览，原值可追溯 |
| `dsh_eval/__main__.py` | 评测 / 运行 / 报告互斥入口 | 新增 `--browse`、`--cases-root`、`--port`，浏览模式复用只读含义的 `--runs-root` | 显式区分执行、复验与浏览 |
| `scripts/check-syntax.js` | 检查原三个 JS 目录 | 包含浏览脚本 | 前端同样进入确定性语法检查 |
| `.github/workflows/deterministic.yml` | 无持续集成 | Windows、Node 24 / Python 3.12，push / PR / 手动检查，无模型调用 | 干净环境可复现，不依赖本机 Harness 缓存 |
| `test/test_browser.py` | 无浏览回归 | 新增 12 项检查 | 覆盖文件边界、实际 HTTP、只读与关联闭环 |
| README、CHANGELOG、进度、架构、格式、配置报告、M3 路线及结果浏览说明 | 下一批为 M5 | 当前实现、命令、验证、云端首跑边界和后续入口 | 同轮同步实际状态 |

原录制器、runner / batch / experiment / evaluate / report 算法、已有 fixture 和 main.py 未修改。

## 实现与技术取舍

### 读取流程与结论边界

`--browse → 固定 loopback 服务 → 带令牌的目录索引 → 保存结果 / 关联文件 → 原始 JSONL 分页`。服务只提供 GET 读取，不导入或调用任务执行、复验流程；浏览结果不写入磁盘。索引响应使用 `browserFormatVersion: 1`，已有持久化格式不变。

页面读取保存的 summary，不重新计算或纠正它。实验 / 报告保留原计划、全尝试和可评测分母；报告以样本结论计数呈现，不给报告本身补造任务 outcome。来源筛选按保存的单次 / 样本声明，混合来源可同时出现在对应筛选内。逐项显示请求 / 实际配置、三维结果、verification、原保存结论和 changedFields；`verified` 表示“复验已处理”，不能当作通过。

报告配对、条件子集、每指标共同覆盖与右减左差值全部来自原 M4.2 文件，原统计逻辑不变；数值只在页面按六位有效数字显示，缺失不补零。完整 JSON 保留原值。浏览旧 passed 不会发现后来被改坏的轨迹，需要用户显式运行原离线复验入口。

### 本地边界与容量

采用标准库 HTTP 与原生 HTML / CSS / JavaScript，无构建和运行依赖，便于本地文件项目启动；没有新增远程托管或多用户账户。服务仅绑定 `127.0.0.1`，启动令牌放 URL fragment，API 使用请求头认证，拒绝异源 Origin / 不匹配 Host，不开放 CORS，响应不缓存。静态页的脚本 / 样式均本地加载，文件内容用文本节点呈现。

每次读取检查显式根目录与解析后的路径，阻止 traversal、隐藏路径、NTFS 备用流和独立 home / workspace / 私人目录；扫描排除符号目录及 junction，包含指回根目录的循环反例。只支持版本化 JSON、固定报告 Markdown 及哈希名轨迹，无任意脚本 / 输出文本下载。

目录限制 2000 项、JSON / Markdown 限制 8 MiB，超限明确显示；轨迹每页默认 50 行、最多 200 行，保留原行号。超过 64 KiB 的行只给 2048 字节预览，解析失败也保留说明，不能将预览误作完整证据。选择分页而不是一次把所有轨迹塞进页面，代价是无全文搜索与完整大文件下载；目录仍是读取时视图，没有一致快照或写入监控。

### CI 与模型执行分开

工作流在 Windows 环境依次检查 JS 语法、Node 回归、Python 回归、compileall 与公开合成 demo。测试适配器使用真实 Node / Python 进程、原录制器和 inspect，不需要模型或已安装 Harness。仓库权限仅 `contents: read`，checkout 不保留凭据，15 分钟作业上限，不安装依赖、不配置模型密钥、不上传 runs。

需要固定 Harness 安装的组件 smoke 不加入干净环境 CI。真实模型继续使用单独选择的 `--run` 和用例 timeoutSeconds；本批没有模型自动工作流，也没有新增 token / 费用硬上限。Action 输入已按官方 [checkout](https://github.com/actions/checkout)、[setup-node](https://github.com/actions/setup-node)、[setup-python](https://github.com/actions/setup-python) 用法核对，使用其当前文档中的 v7。

## 验证

2026 年 10 月 21 日，Windows、Node.js `v24.14.0`、Python `3.12.0`。

| 命令或操作 | 结果 | 证明的范围 |
| --- | --- | --- |
| `python -m unittest discover -s test -p test_browser.py -v` | 12 项通过 | 索引 / 刷新、保存值不复验 / 不执行 / 不改写、缺失 / 损坏 / 版本 / 容量、路径与 junction 循环、HTTP 认证 / Host / Origin / 写请求、CLI 与合成实验关联 |
| `npm.cmd run test:python` | 首次沙箱 129 项中四项既有真实进程强停受限；获准环境完整 129 项通过，最终版本再次完整通过 | 原 117 + 新 12；强停未用 mock 代替 |
| `npm.cmd test` | 42 项通过，无跳过 | 原 Node / 录制器与适配层回归 |
| `npm.cmd run check` | 30 个 JS 文件通过 | 原 29 个及浏览脚本语法 |
| `python -m compileall -q dsh_eval test`、`python -m dsh_eval --help` | 通过 | Python 语法与互斥入口可用 |
| `npm.cmd run demo:eval` | 两份公开合成证据生成成功，source=synthetic、modelCalled=false | 原录制器生成示例，不是模型任务 |
| 实际 `python -m dsh_eval --browse` 与本机 HTTP 遍历 | 5 用例 / 8 批次 / 3 实验 / 9 报告 / 31 逐次结果及关联文件，共 292 份；28 份轨迹 / 691 行，无读取错误 | 读取既有保存文件；608 份原 JSON / JSONL 摘要前后一致，未 fresh inspect 历史日志 |
| 实际浏览页面 | 分类、名称搜索、结论 / 来源筛选、报告 / 实验 / 样本 / 证据跳转及分页检查 | 页面交互；用扩展公开合成事件验证多页轨迹，未调用模型 |
| 公开文档 / fixture / 忽略检查、`git diff --check` | 37 份 Markdown、209 个本地链接，五用例 / 一批次 / 一实验格式与原文件摘要检查通过；无私人 / 运行文件跟踪，diff 检查通过 | 公开接续与边界；后续只补充验证文字，不改链接 |

合成集成测试先运行两个显式配置标签的真实适配进程与 Python 状态化工具，生成实验和新报告，再递归浏览关联文件并对比摘要。它验证关联与读取流程，不证明真实模型配置成绩。额外分页样例通过原录制器写入公开模拟事件与 110 条标明 synthetic 的辅助事件，离线检查后作为页面样例，不是新增真实会话。

本批没有新模型调用，没有重跑 `smoke:host` / `check:output` / `smoke_bridge`，没有重新评测历史模型任务。没有提交、推送、创建 PR 或触发托管 CI，不能将本地通过写作云端通过。原验证汇总、历史轨迹及本批本地验收材料保留在被忽略目录，公开仓库不依赖它们。

## 风险与后续

当前浏览信任保存结论，来源仍为声明，不能代替主动复验或证据签名。绝对关联路径迁移后可失效；目录可能在读取之间变化，应使用停止写入后的稳定结果。令牌与路径检查限制浏览服务读取范围，不替代本机文件权限，也不防御有能力同时修改本机证据与代码的用户。

既定 M1 至 M5 的当前功能实现与本地验证完成；下一个验收是提交后首次运行 GitHub CI 并记录其结果，远程 / 多用户、并发、resume、跨实验合并、统计推断及其他渠道仍按需求单列，不宣称已完成。

## 文档同步

已同步 [运行说明](../../README.md)、[结果浏览](../result-browser.md)、[进度](../progress.md)、[架构](../architecture.md)、[格式](../evaluation-format.md)、[配置报告](../configuration-reports.md)、[主路线](../plans/m3-regression-evaluation.md) 与 [修改索引](../../CHANGELOG.md)，并修正单用例指南末尾仍将 M3.4 / M4 / M5 写作未来计划的过时状态。
