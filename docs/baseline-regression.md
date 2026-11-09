# 基线回归比较

更新：2026 年 11 月 1 日，Asia/Shanghai。实现见 [085](changes/2026-11-01-085-baseline-regression.md)。该入口重新复验两个独立实验的保存证据，判断选定配置中哪些样本发生通过 / 失败变化，不执行模型任务。

## 使用与退出码

在项目根目录运行，输入为已有的 `experiment-result.json` 或显式 `experiment-resume-result.json`：

```powershell
python -m dsh_eval --compare-baseline 'runs/experiments/<baseline-id>/experiment-result.json' --candidate 'runs/experiments/<candidate-id>/experiment-result.json' --output 'runs/regression.json'
$LASTEXITCODE
```

`--output` 可省略，结果始终以 UTF-8 JSON 输出到 stdout。指定输出时父目录须存在，文件必须尚不存在；不会覆盖原结果或已有报告，不自动创建报告目录。普通实验须终态，实验续跑版本 1 / 2 沿用已有两批次 / 连续链核验；不接受 batch-result.json、普通单用例 evaluation.json 或旧 report.json 作为输入。

| 退出码 | outcome | 含义 |
| --- | --- | --- |
| 0 | passed | 全部选定样本完整可比，且没有通过变失败；允许失败保持失败，也允许失败变通过，不表示所有任务通过 |
| 1 | failed | 全部选定样本完整可比，至少一个通过变失败；改善不能抵消退化 |
| 2 | unevaluable | 有缺项、不可比、证据不足，或输入 / 写入错误；已确认的退化仍保留在正常比较结果中 |

有效输入但覆盖不足时，仍生成 `status=compared` 的完整比较 JSON，`hasRegressions` 与逐项列表保留已确认的退化。结构 / 关联错误返回 `status=error`、`exitCode=2` 和 error，不伪造可用的逐项列表。命令行参数错误按 argparse 输出到 stderr 并退出 2。

[086 复查修复](changes/2026-11-01-086-baseline-regression-review.md) 明确要求输入结果的根节点为 JSON 对象；数组或字符串即使含有续跑格式标记也不能进入续跑分支，比较及原报告入口均返回输入错误 2，不以未处理异常的退出 1 冒充退化。

旧 `--report` 的退出码不变：0 仅表示描述性报告生成成功，不承担回归判定。

[091 置信区间](uncertainty.md) 属于单实验 / 显式续跑报告中的配置比较。基线回归仍按已观测的通过 / 失败变化和覆盖情况返回 0 / 1 / 2，不因区间跨零、不可用或样本较少而改写结论，也不计算跨实验区间。

## 配置选择与显式允许变化

每边只选择一套配置。单配置实验可自动选择；多配置实验必须分别指定 ID，不能根据数组位置或名称相似度猜测：

```powershell
python -m dsh_eval --compare-baseline 'runs/experiments/<baseline-id>/experiment-result.json' --candidate 'runs/experiment-resumes/<candidate-resume-id>/experiment-resume-result.json' --baseline-config baseline --candidate-config candidate --allow-config-change model --allow-config-change profile
```

默认要求两边选定的完整 configRef 相同。可重复指定 `--allow-config-change`，仅支持 provider、model、profile、pluginVersion 四个字段。未声明的变化阻断比较；允许 model 变化不同时允许 provider 变化。允许列表与实际 configurationChanges 都写入结果，未发生变化的允许项不会伪造差异。

configurationId 只是每个实验内的选择标签，可以不同；actual 配置和全部录制请求路由仍须分别匹配各自的请求配置。显式允许变化不会跳过路由核对。

`--compare-baseline` 与原 case / batch / experiment / resume / report / browse 入口互斥，必须提供 `--candidate`，不能使用 --run、--plan、--evidence、--reports-root 或宿主 / 运行控制参数。没有比较入口时不能单独使用 candidate、配置选择或允许变化参数。

## 可比性与配对范围

1. 两边独立加载冻结清单、样本矩阵与关联文件，重新核对计划指纹。缺少可重算计划输入的旧实验保持 plan unverified，不能通过该回归判定；格式错误或快照被改写直接返回输入错误。
2. 使用 `(caseEntryId, repeatIndex)` 对齐选定配置的完整矩阵。sampleId、数组位置、实验名称及文件路径均不用于跨实验配对。重复次数或用例集合可以不同，但差额会逐项列出并使退出码为 2；重命名 entryId 不自动映射。
3. 共有用例的完整冻结 case 除顶层 configRef 外必须严格相同，包括 caseId、输入提示、环境 / 故障状态、断言、预算、录制限制、modelProviders 及格式版本。taskChanges 列出发生变化的顶层字段。允许配置变化不能放行任务输入变化；外部路由目录也须一致，可预先在两边使用相同完整目录。
4. 不接受相同原实验身份的两份输入，包括原实验对其续跑，也不接受两边选定矩阵共享 caseRunId / runId / sessionId。续跑可以作为某一边的完整结果，但另一边必须是独立实验。
5. 每个共有样本重新运行原 evaluate / inspect，并核对冻结输入、批次 / 用例身份和实际路由。只有 finished、verified、matched、completed、complete、明确 passed / failed 的两侧样本才比较结论。
6. 每对样本的来源声明必须相同且为 live 或 synthetic。跳过、运行错误、缺失 / 损坏证据、路由未知 / 不符或断言无法评测均不能算普通退化或改善。

未选择配置的证据不参与本次结论，但整个实验的矩阵和冻结输入结构仍须通过原加载校验。调度停止阈值、输出目录或实验名称不要求相同；任务预算属于冻结 case，必须一致。少量配对仅描述这些样本，不提供显著性、因果、总体成功率或模型优胜推断。

[088](changes/2026-11-01-088-seeded-order-repeat-distributions.md) 后，两侧元信息新增 executionOrder，披露各自规则和可选随机种子。每侧按自己的冻结计划验证顺序，但两侧可以使用不同种子或固定 / 随机顺序；仍按 caseEntryId / repeatIndex 配对，不按执行位置。允许比较不同顺序不构成因果或独立样本保证。

## 结果 JSON

`regressionComparisonFormatVersion=1`，不改变原实验、评测或配置报告的版本。主要字段：

| 字段 | 内容 |
| --- | --- |
| baseline / candidate | 输入绝对路径、原实验 ID、选定配置、计划复核、选定计划样本数 |
| allowedConfigurationChanges / configurationChanges | 显式允许的字段，以及实际左右值 / 是否允许 |
| comparability | comparable 或 incomplete；全局问题例如计划未核验、未经允许的配置变化、共享执行身份 |
| counts | 各类变化数量，compared 为实际可比项数，total 为两边样本键的并集大小 |
| samples | 对齐键、change、reasons、taskChanges，以及两边新复验的行；不在该边矩阵中的项为 null |
| hasRegressions / outcome / exitCode | 是否存在已确认退化及最终门禁结论；证据不足优先，但不删除已确认退化 |

每个样本的 change：

| 值 | 含义 |
| --- | --- |
| regression | 基线 passed → 候选 failed |
| improvement | 基线 failed → 候选 passed |
| unchanged_passed / unchanged_failed | 两侧结论相同 |
| missing_in_candidate | 基线矩阵有此项，候选矩阵没有 |
| missing_in_baseline | 候选新增此项，没有对应基线 |
| incompatible | 任务输入、来源或全局可比性条件不满足 |
| unavailable | 共有项缺少可比较的执行 / 录制 / 断言 / 路由证据 |

计划中存在但 skipped、证据文件缺失的样本属于 unavailable，区别于矩阵本身没有该项。两侧行保留 saved 结论与新复验 outcome、changedFields、原因和证据路径；不根据旧 summary 或旧 evaluation 的 passed 字段做判断。该格式提供 CLI / JSON；[CI回归门禁示例](ci-regression.md)使用独立合成实验验证原退出语义并发布比较产物，结果浏览器接入仍待后续批次。

## 边界

输入应为停止写入后的稳定归档；读取不是原子快照，不加执行锁、不签名，也不认证 live 声明。比较过程不修改源文件，显式 --output 只排他新建指定文件。写入失败可能留下不完整的新输出文件，不提供原子发布保证。

本功能不会运行 / 重试样本或补齐缺项，不将未知状态补成零或失败，不合并两份实验的统计分母；相同重复编号也不证明样本独立。测试使用合成适配器、真实子进程、原录制器与 fresh inspect；当前没有新增真实模型比较验收。
