# 录制器 CPU、事件循环与持续负载测量

更新：2026 年 11 月 17 日，Asia/Shanghai。

146复查补充了失败测量的recorder / ELD收尾、时间归一化前的有效性检查和非法 / 缺失指标处理，见[复查记录](changes/2026-11-17-146-recorder-profiling-review.md)。下文33对性能数据保持145冻结仪器的原始采集值，新仪器摘要不同，不能将历史结果称作修复后重新采集。

本页说明资源测量版本 2 的方法与本轮结果。测量使用合成事件、独立 Node 进程和真实文件，不调用模型。历史的八类负载与 2026 年 10 月结果仍保留在[录制资源边界](recorder-resources.md)；本轮新增 CPU、事件循环、细分 I/O 和固定轮次持续负载，没有改写历史数据。

可公开核对的逐对数据、摘要、来源哈希和限制见[本轮测量证据 JSON](benchmarks/2026-11-17-recorder-resources.json)，实现与验证记录见[修改记录 145](changes/2026-11-17-145-recorder-resource-profiling.md)。公开 JSON 不包含本机原始日志和绝对路径；重新读取原文件的比较需要本地保留完整测量目录与源码快照。

## 输入与运行隔离

[测量入口](../scripts/measure-recorder.js) 每个场景、每次重复都启动新的 `node --expose-gc` 进程。原有 `long-text`、`oversize`、`sessions-100`、`sessions-300`、`sessions-600`、`sessions-600-batched`、`slow-writes`、`slow-overflow` 的输入大小、顺序、flush 节奏和计数断言保持不变。

新增 `sustained` 使用 4 个会话、500 轮，每轮每会话 4 个事件，每个正文为 4096 字节；共 8000 个事件。每轮 flush，计划起点相隔 40 ms，目标时间约为 20 秒。每轮保存实际起点、落后时间、CPU 和工作时长；迟到后仍只完成规定的 500 轮，不按运行时长追加任务。它覆盖有节奏的连续写入，尚不是长时间稳定性或泄漏测试。

| 参数 | 作用 |
| --- | --- |
| `--scenarios name,name` | 按给定顺序选择场景，不允许重复；省略时仍只运行原有八类，`sustained` 需要显式选择 |
| `--repeats 1..10` | 每场景重复次数，默认 3；每次均为新进程 |
| `--output-dir PATH` | 输出到全新目录；已存在则拒绝。省略时创建 `runs/recorder-resources/<UUID>` |
| `--recorder-module PATH` | 明确选择被测录制器入口，默认当前 `src/recorder.js` |
| `--inspect-module PATH` | 明确选择复验入口，默认当前 `src/inspect.js`；比较时双方应显式使用同一份冻结入口 |

每个成功样本保存 `measurement.json` 和实际运行目录，批次保存 `summary.json`。失败批次保留已完成样本及首个错误，进入worker后的异常另写`failure.json`；producer错误后先尝试关闭recorder，再恢复fs包装，保留原错，所有退出路径关闭ELD。存在`spawn EPERM`等进程权限错误的批次不能视为完成，应保留失败目录，在允许真实子进程的环境使用新目录运行。

## 冻结来源与复现命令

录制器来源包含 `src/recorder.js`、`config.js`、`metadata.js`、`session-status.js` 和 `package.json`。inspect 的来源还包含 `src/inspect.js`，因为它导入录制器中的文件命名函数；仅冻结 `inspect.js` 一个文件不够。测量器来源包含 `scripts/measure-recorder.js` 和 `recorder-measurement.js`。

下面是一次新比较的阶段式 PowerShell 流程，从仓库根执行。第一段必须在待比较优化之前执行；如果当前工作区已经是候选实现，先将 `$baselineSource` 指向明确准备好的基线源码根，不能将候选再次命名为基线。本轮基线对应 `cf2cccfb4801ed1f5228a6cc414dfec33b923ba6`，候选在测量形成时尚未提交。实际文件字节和来源 SHA 以证据 JSON 为准，提交名不替代字节校验。

```powershell
$ErrorActionPreference = 'Stop'
$repoRoot = (Get-Location).Path
$baselineSource = $repoRoot
$profileRoot = Join-Path $repoRoot ('runs/recorder-profile-' + [guid]::NewGuid())
$baselineRoot = Join-Path $profileRoot 'baseline-source'
$candidateRoot = Join-Path $profileRoot 'candidate-source'
$harnessRoot = Join-Path $profileRoot 'harness'

function Copy-RecorderSnapshot([string]$Source, [string]$Destination) {
    if (Test-Path -LiteralPath $Destination) { throw "Snapshot already exists: $Destination" }
    New-Item -ItemType Directory -Path (Join-Path $Destination 'src') | Out-Null
    foreach ($name in @('recorder.js', 'config.js', 'metadata.js', 'session-status.js', 'inspect.js')) {
        Copy-Item -LiteralPath (Join-Path $Source "src/$name") -Destination (Join-Path $Destination "src/$name")
    }
    Copy-Item -LiteralPath (Join-Path $Source 'package.json') -Destination (Join-Path $Destination 'package.json')
}

Copy-RecorderSnapshot $baselineSource $baselineRoot
New-Item -ItemType Directory -Path $harnessRoot | Out-Null
foreach ($name in @('measure-recorder.js', 'recorder-measurement.js')) {
    Copy-Item -LiteralPath (Join-Path $repoRoot "scripts/$name") -Destination (Join-Path $harnessRoot $name)
}
Copy-Item -LiteralPath (Join-Path $repoRoot 'package.json') -Destination (Join-Path $harnessRoot 'package.json')
$measureScript = Join-Path $harnessRoot 'measure-recorder.js'
$inspectModule = Join-Path $baselineRoot 'src/inspect.js'
$scenarioNames = 'long-text,oversize,sessions-100,sessions-300,sessions-600,sessions-600-batched,slow-writes,slow-overflow,sustained'

node $measureScript --scenarios $scenarioNames --repeats 3 `
    --output-dir (Join-Path $profileRoot 'baseline') `
    --recorder-module (Join-Path $baselineRoot 'src/recorder.js') `
    --inspect-module $inspectModule
if ($LASTEXITCODE -ne 0) { throw 'Baseline measurement failed' }
```

先读取基线找出瓶颈，再完成待比较实现，在同一PowerShell会话执行第二段。候选同样复制到新目录，继续运行同一份测量器和基线inspect及其依赖。复制保持原始字节；测量过程不会把CRLF/LF差异归一成相同的来源SHA。

```powershell
Copy-RecorderSnapshot $repoRoot $candidateRoot
node $measureScript --scenarios $scenarioNames --repeats 3 `
    --output-dir (Join-Path $profileRoot 'candidate') `
    --recorder-module (Join-Path $candidateRoot 'src/recorder.js') `
    --inspect-module $inspectModule
if ($LASTEXITCODE -ne 0) { throw 'Candidate measurement failed' }

python scripts/compare_recorder_resources.py `
    --baseline (Join-Path $profileRoot 'baseline/summary.json') `
    --candidate (Join-Path $profileRoot 'candidate/summary.json') `
    --output (Join-Path $profileRoot 'comparison.json')
if ($LASTEXITCODE -ne 0) { throw 'Comparison rejected' }
```

[比较器](../scripts/compare_recorder_resources.py) 要求双方环境、场景顺序、重复数、输入与采样协议一致；测量器和 inspect 的完整来源必须相同。录制器及其依赖允许不同，但逐文件差异会列出。比较器实际读取来源文件并校验 SHA，同时核对每个 `measurement.json`、实际输出和完整场景 × 重复集合，结束前重新检查源文件。源码快照必须保留，不能只保留其摘要声明；来源缺失、变化或少样本时拒绝比较，不扫描其他批次补齐。

主比较按“全部基线，再全部候选”的顺序执行。为观察顺序影响，本轮另外对 `sessions-600-batched,sustained` 执行三轮交错确认，次序为 B1、C1、C2、B2、B3、C3，每组使用 `--repeats 1`，共 12 个新进程。可在上面的快照保留不变时执行：

```powershell
$confirmationOrder = @(
    @{ side = 'baseline'; round = 1 }, @{ side = 'candidate'; round = 1 },
    @{ side = 'candidate'; round = 2 }, @{ side = 'baseline'; round = 2 },
    @{ side = 'baseline'; round = 3 }, @{ side = 'candidate'; round = 3 }
)
foreach ($item in $confirmationOrder) {
    $sourceRoot = if ($item.side -eq 'baseline') { $baselineRoot } else { $candidateRoot }
    $groupName = 'confirm-{0}-{1}' -f $item.side, $item.round
    node $measureScript --scenarios 'sessions-600-batched,sustained' --repeats 1 `
        --output-dir (Join-Path $profileRoot $groupName) `
        --recorder-module (Join-Path $sourceRoot 'src/recorder.js') `
        --inspect-module $inspectModule
    if ($LASTEXITCODE -ne 0) { throw "Measurement failed: $groupName" }
}
foreach ($round in 1..3) {
    python scripts/compare_recorder_resources.py `
        --baseline (Join-Path $profileRoot "confirm-baseline-$round/summary.json") `
        --candidate (Join-Path $profileRoot "confirm-candidate-$round/summary.json") `
        --output (Join-Path $profileRoot "confirmation-$round.json")
    if ($LASTEXITCODE -ne 0) { throw "Confirmation rejected: $round" }
}
```

确认轮号来自显式组名，每组 summary 的内部 repeat 均为 1。三个比较文件各含两对样本，保留为独立的确认数据，不与主比较合并成六次重复。

## 指标窗口与单位

`process.cpuUsage()` 的原始 user/system 单位是微秒。六个阶段为 `baseline-gc`、`setup`、`input`、`producer`、`close`、`final-gc`；阶段互不重叠，阶段之间的采样和记账开销仍包含在总 CPU 中，因此阶段和不要求等于总量。CPU 是进程所有线程及仪器开销的累计时间，可以大于墙钟时间；本机 Windows 的短窗口还会出现明显量化值，零值不证明没有消耗 CPU。API语义见[Node24.14.0 CPU时间说明](https://nodejs.org/download/release/v24.14.0/docs/api/process.html#processcpuusagepreviousvalue)。

`producer` 包含 record 调用、循环、flush、等待期间的实际 I/O 和周期等待。flush 逐次 CPU 是 producer 的子集，不能再次与阶段总量相加。record 延迟统计的是调用耗时，`true` 仍只表示排队成功。`workloadMs` 从生产开始计到 close 完成；吞吐分母使用这段墙钟时间，分别给出尝试、接受、写入事件和写入字节每秒，不把失败场景的尝试数当作写入数。setup、输入创建、最终 GC 和 inspect 不在吞吐窗口内。

事件循环延迟使用 `monitorEventLoopDelay({ resolution: 10 })`，纳秒转为毫秒。预热 20 ms 后 reset，再每 20 ms 检查是否已有首个样本，最长等待 1 秒；实际 arming 时长和样本数保存下来。最后一次 GC 后另观察 20 ms，等待末段阻塞被定时器采到，再关闭直方图。延迟统计包括 arming/tail 的观察样本和定时器名义间隔，不等于“超过 10 ms 的额外延迟”；操作系统可能使实际等待更长。count 为 0 时，最小值、最大值、均值和分位数均为 null。

ELU 单独保存 active、idle 和总时长，以及 `active / (active + idle)`；分母为零时 utilization 为 null。其窗口覆盖基线 GC 到最终 GC，排除上述 arming/tail 等待。ELU 描述事件循环活动比例，不是进程 CPU 利用率，不能替代 user/system CPU 时间。

事件循环API的采样、单位与ELU边界见[Node24.14.0性能测量说明](https://nodejs.org/download/release/v24.14.0/docs/api/perf_hooks.html#perf_hooksmonitoreventloopdelayoptions)。

I/O 统计拆分 append、清单/status write 和 rename 的尝试数、完成数、成功写入字节与累计耗时。初始同步清单写入也计入；rename 的 bytes 为 0。并发调用的耗时会重叠，累计 I/O 时间不是总墙钟时间，也不是磁盘扇区写入量。慢写场景仅在 append 前人为等待 15 ms，随后仍执行真实追加。unlink 的诊断计数来自独立探针，不混入性能样本。

内存仍在 GC、批次边界和 10 ms 定时器采样，最大值是采样最大值。测量器保留 memory samples、rounds、flushCalls、enqueueTimes 等数组，其增长也在进程内存中；约 20 秒曲线或 GC 后差值不能据此证明录制器泄漏。

## 内容一致性与原始字节

每个样本保存真实文件SHA、字节数和来源SHA。比较先核对计数、错误、close结果、状态与真实trace摘要，并独立验证startedAt / updatedAt为有效的生成ISO时间，不能通过规范化抹掉无效日期。之后仅把顶层runId换成同长度固定UUID，清单startedAt/status updatedAt换成固定ISO时间，inspect.runDir换成`<run-directory>`，已校验的status/inspect trace摘要映射为归一化trace摘要。事件正文中的同名字段保持不变，成员数组和事件顺序保持不变。

比较指标只接受对应结构中的有限数字或明确null；字符串、布尔、列表及错误的对象结构不能被静默跳过。派生内存差值、flush CPU合计或比例所需值缺失时保持null；空flush调用集合的已观测合计为0，零分母比例为null。非法和溢出指标拒绝比较，不生成一个删去坏指标的成功报告。

JSONL 必须先逐字节满足规范 UTF-8 JSON 与 LF 行尾，额外空白、CRLF、重复键或无效编码不能通过重新序列化隐藏。清单/status 按 JSON 结构比较，保留真实字节长度；等长排版差异可能得到相同结构摘要，但仍会列入原始文件 SHA 差异。完整 inspect 的结果、原因、计数和状态均参加比较。

因此“归一化内容相同”与“原始字节相同”是不同结论。本轮各对样本的 runId/时间不同，原始摘要不同；33 对均通过计数、错误、close、归一化文件与 inspect 核对，没有把不同的原始 SHA 宣称为相同。

## 2026 年 11 月 17 日结果

环境为 Windows `10.0.26200` x64、Node `v24.14.0`、AMD Ryzen 5 9600X，12 个逻辑处理器。主比较为九类各三对，确认比较为两类各三对，分组统计保持独立。下表墙钟取 `workloadMs`，CPU 为 user + system，均转换或保留为毫秒；每格是该侧三个样本的中位数。变化率列是每对 `100 × (candidate − baseline) / baseline` 的中位数，不能从两侧中位数重新相除；零分母或缺值为 null。

| 主比较场景 | 墙钟：基线 → 候选 ms | 配对墙钟变化率 | CPU：基线 → 候选 ms | 配对 CPU 变化率 |
| --- | ---: | ---: | ---: | ---: |
| long-text | 49.377 → 47.088 | -6.649% | 47 → 78 | +34.043% |
| oversize | 41.707 → 39.028 | -3.957% | 79 → 77 | 0.000% |
| sessions-100 | 126.453 → 110.264 | -10.146% | 220 → 296 | +25.200% |
| sessions-300 | 364.669 → 332.051 | -8.907% | 781 → 813 | +6.018% |
| sessions-600 | 739.366 → 674.489 | -8.397% | 1704 → 1281 | -14.108% |
| sessions-600-batched | 1925.654 → 1683.343 | -12.583% | 3687 → 3296 | -7.272% |
| slow-writes | 294.247 → 338.405 | +5.260% | 94 → 31 | -45.813% |
| slow-overflow | 63.650 → 61.697 | -1.478% | 15 → 0 | -82.979% |
| sustained | 19972.115 → 19972.092 | -0.005% | 4735 → 5375 | +20.444% |

| 交错确认场景 | 墙钟：基线 → 候选 ms | 配对墙钟变化率 | CPU：基线 → 候选 ms | 配对 CPU 变化率 |
| --- | ---: | ---: | ---: | ---: |
| sessions-600-batched | 1962.762 → 1777.696 | -10.119% | 4015 → 3563 | -2.358% |
| sustained | 19971.877 → 19968.397 | +0.003% | 6250 → 6250 | +5.254% |

原有错误场景仍保持 `oversize` accepted/written = 1/1、16 个 failed 与 1 个 sealed、inspect 1；`slow-overflow` 为 4/2、1 个 failed 与 1 个 sealed、inspect 1。其他场景 inspect 0；持续负载每次均写入 8000 个事件。预期失败没有被统计成正常录制成功。

独立 `sessions-600-batched` 诊断发现，基线在成功rename后仍执行了3307次unlink，全部返回ENOENT。优化仅在[session-status.js](../src/session-status.js)成功替换后跳过这个已无对象可删除的清理动作，候选同一诊断的unlink次数为0；rename重试机制保持，重试成功同样跳过unlink，临时写入失败或rename最终失败仍走原有清理路径。没有改变录制器排队、序列化、状态格式、flush/close或inspect协议。

分批 600 会话的墙钟下降在主比较与交错确认中均出现，这支持移除冗余清理的本地价值。CPU 不能作同样结论：持续负载主比较配对变化率中位数为 +20.444%，范围 -16.103%～+27.854%；交错确认中位数为 +5.254%，范围 -19.628%～+6.256%。方向混合，既不证明 CPU 节省，也不足以断言稳定 CPU 回退。其他场景也有不同方向的墙钟或 CPU 变化，不作整体性能提升声明。

145冻结版本的完整回归为718项Python（450.791秒）、181项Node（8.145秒）、50文件JS语法及Python编译通过，无跳过；146修正后的当前回归见[复查记录](changes/2026-11-17-146-recorder-profiling-review.md)。三个重复仅作描述性观察，未作显著性检验；文件系统缓存、线程调度、GC和测量开销仍会影响结果。没有新增长期稳定性、操作系统内存高水位、OOM、断电或fsync保证。
