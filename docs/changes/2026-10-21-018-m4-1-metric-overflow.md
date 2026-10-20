# 修改记录 018 M4.1 指标单值与汇总溢出修复

日期：2026 年 10 月 21 日，Asia/Shanghai。类型：修复 / 测试 / 文档。插件版本：0.1.2。相关 Git 提交：已核实 M4.1 主体为 `1a6cf69`；本批尚未提交。

## 问题与目标

M4.1 审查发现，可选 runtime.elapsedSeconds 写入有效 JSON 整数 10**400 时，number 中 math.isfinite 的浮点转换抛出 OverflowError，导致原本 passed 的录制无法生成评测结果，CLI 也直接抛错。两个有效有限值 1e308 的汇总则得到 Infinity，保存后无法被项目自己的严格 JSON 解析器读回；整数累计后混入浮点数也可能直接抛出溢出异常。

本批让异常指标保持缺失或明确的汇总失败，保留任务结论、其他合法指标、覆盖数量和统计分母。原始录制及旧实验结果保持不变。

## 文件修改

| 文件 | 修改前 | 修改后 | 原因 |
| --- | --- | --- | --- |
| dsh_eval/metrics.py | 数值转换可能抛错，字段和 / 汇总未检查有限范围 | 超大单值返回无效，复用受保护求和，汇总失败为 null 并附 reason | 隔离指标错误与任务评测，保持输出可读 |
| test/test_metrics.py | 缺少超大整数与累计溢出检查 | 新增四项，覆盖单值、token 字段和、缺失覆盖和 JSON 往返 | 防止静默产生非有限汇总 |
| test/test_evaluation.py | 异常耗时仅覆盖负值与布尔值 | 新增一项，原录制器 / fresh inspect / CLI 验证超大耗时 | 保留 passed、执行 / 录制 / 断言及正常指标 |
| CHANGELOG、progress、架构、格式、实验说明与 M3 方案 | M4.1 主体范围与历史验证 | 数值范围、可选 reason、修复验证及当前入口 | 对齐实现，保留 017 原验证 |
| 本机私人交接 / 面试材料 | 主体尚未提交的旧交接 | 已核实主体提交、本批结果和下一批入口 | 不作为公开仓库依赖 |

## 实现与技术取舍

number 继续严格接受非负 int / float，拒绝布尔值和非有限值；捕获超大整数转换的 OverflowError，返回无效。这里的有限范围指可表示为有限浮点数，不把超大整数视为可用指标，也不把有效整数转换、截断或补零。

token 的每个字段仍要求全部消息覆盖，且没有失败尝试。单值增加相同数值范围检查，字段和复用受保护求和；只有受影响的字段保持 null，模型 / 工具计数和其他 usage 字段保持。

实验汇总先剔除无效单值并记入 missingSamples，再对有效子集求和。捕获混合算术的 OverflowError，并检查浮点 Infinity 或超出范围的整数和；失败时 observedTotal / observedMean 均为 null，保留实际 observedSamples / missingSamples，增加可选 reason。没有把汇总溢出误报成所有单值缺失，也不重算或改变任务通过比例。

两个调用点复用同一受保护求和，避免只修实验汇总却继续产出不可汇总的 token 字段。未通过宽泛异常捕获掩盖整个评测或调度错误；指标层完成处理，原 evaluate、CLI、runner 和 JSON 写入逻辑无须变动。实验和 metrics 均继续使用版本 1，原始录制协议保持。

## 验证

2026 年 10 月 21 日，Windows / Python 3.12.0 / Node v24.14.0；没有新的模型调用。

| 命令或操作 | 结果 | 证明的范围 |
| --- | --- | --- |
| 修复前运行新增指标与超大耗时回归 | 复现 OverflowError、Infinity、超大 token 字段未被排除 | 新增回归能发现已审查问题及同类求和边界 |
| `python -m unittest discover -s test -p test_metrics.py` | 修复后 11 项通过 | 超大正 / 负整数、有限浮点和 / 整数和 / 混合求和、其他字段及样本覆盖保持、严格 JSON 往返 |
| `python -m unittest discover -s test -p test_evaluation.py` | 修复后 32 项通过 | 原录制器与 fresh inspect，异常耗时保持 passed / complete，CLI 返回 0；已有证据反例继续通过 |
| `npm.cmd run test:python` | 获准环境 100 项通过（原 95 + 新 5） | 完整 Python 回归及既有真实自有进程 / 管道清理 |
| `npm.cmd test` / `npm.cmd run check` | 42 项 / 29 个 JS 文件通过 | 既有 Node 回归与语法 |
| `python -m compileall -q dsh_eval test` | 通过 | Python 语法 |
| `python -m scripts.smoke_bridge` | 获准环境真实工具注册 / IPC 四次请求通过，modelCalled=false | 与实时桥接兼容，不是模型端到端验收 |
| 两个历史实验的四个实际执行分别离线 evaluate，前后核对原 JSON / JSONL SHA-256 | 三维分类均保持、四项仍 passed，原文件摘要一致 | 正常历史路径与证据保留；没有新的实际执行 |
| 公开 Markdown 相对链接、输入格式及 Git 范围检查 | 33 份 Markdown / 167 个本地链接有效，五用例 / 一个批次 / 一个实验格式通过；git diff --check 通过 | 无公开链接指向忽略资料，runs / private-notes 仍忽略且无跟踪文件 |

最终实验 e3933155-4d89-4b1b-8b58-07148c38154f 的两项新复验指标与保存结果一致，已结算尝试 3 / 4、totalTokens 22531 / 30240。首轮实验 64f05fc5-c751-4a6c-8161-a5a19c7c0471 的原报告仍保留当时的缺失指标，新复验取得尝试 3 / 3、totalTokens 22512 / 22750；这是记录 017 已说明的 step 边界修正结果，未覆盖旧报告，不是本次溢出修复改变正常计数。

超大数值和错误 runtime 是合成反例，集成检查使用真实 Node 录制 / inspect 与 Python CLI，不代表模型实际报告过这些数值。本批没有重跑真实模型任务、smoke:host / check:output 或更早 M3 模型轨迹。

## 风险与后续

可选汇总 reason 是版本 1 兼容扩展；观察数量非零而总和 / 均值为 null 时，应展示原因，不能当作零或全量缺失。当前选择在总和超范围时同时放弃均值，不另引入高精度统计或无穷大表示。对有效普通数值，原分母及指标保持。

下一批仍为 M4.2 配置比较与报告，然后 M5 浏览与 CI，剩两个实施批次。未新增价格、统计推断或性能 / 成本结论。本批未自动提交或推送。

## 面试讨论点

有限单值不保证有限总和；可选指标不能击穿任务评测。单值缺失和汇总失败有不同覆盖语义，需要保留观测数量、原因和原始证据，而不是补零、丢弃样本或修改任务结论。

## 文档同步

已同步修改记录、CHANGELOG、progress、architecture、evaluation-format、experiments、M3 方案及本机私人交接 / 面试材料。命令与参数不变，无须修改 README。历史记录 017 和原始实验文件未覆写，公开文档不依赖私人资料或运行日志。
