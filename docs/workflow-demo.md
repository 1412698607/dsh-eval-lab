# 可重复的离线工作流演示

2026 年 11 月 9 日，Asia/Shanghai。此入口生成预先编排的合成任务，通过实际子进程管道、Python 状态化工具、JavaScript recorder、独立 inspect 和既有评测器计算结论。所有任务的来源为 `synthetic`，索引、脚本配置和运行事实声明 `modelCalled=false`。它验证记录、评分与浏览流程，不提供真实模型表现数据。

## 从新 checkout 运行

需要 Python 3.12+ 和 PATH 中的 Node.js 22.8+。此演示只导入仓库公开代码和标准库，无需安装 Harness、配置凭据或安装前端依赖。在项目根目录执行：

```powershell
npm.cmd run demo:workflow
```

命令先新建 `runs/workflow/<UUID>`，生成、独立复验全部内容，再以前台方式启动本机只读浏览服务。终端输出 JSON，其中 `url` 是带本次令牌的完整地址。打开该地址，选择“工作流演示”，打开索引，按顺序查看三个场景：

| 场景 | 实际结论 | 查看内容 |
| --- | --- | --- |
| 完整重试步骤 | completed / complete / passed | 首次改名超时，读源、确认目标不存在，再重试并读回；完整最终文件映射通过 |
| 跳过中间读回 | completed / complete / unevaluable | 最终文件和回复正确，但 source-still-present 缺证，三个后继条件也缺证；六项 passed、四项 insufficient_evidence |
| 四样本规则影响 | compared，分母 4，可对照 4 | 原确认词规则四项通过；候选必需精确 `done` 只使 timeout-retry 第一轮的 `**done**` 样本转为失败，其余三项仍通过 |

在评测页可以查看用例期望、断言结论、最终文件映射和工具事件。第三个场景展开 `sample-000002` 的 `answer`，可以比较同一原文的两侧规则，并跳到实际答案事件。此处的变化只来自离线重评，不修改冻结用例或旧结论。“变化断言”也包含规则改变但结果保持通过的条目。

终端按 Ctrl+C 停止；Windows 下 npm 的批处理包装可能继续询问 `Terminate batch job (Y/N)?`，输入 Y 结束包装进程。关闭网页不会停止服务。也可直接运行 `python -m dsh_eval.workflow_demo`，省去 npm 包装。

## 仅生成与再次浏览

自动化或 CI 使用生成模式，校验预期结论后退出，不启动浏览服务：

```powershell
npm.cmd run demo:workflow -- --generate-only
```

默认每次生成新 UUID 目录和运行身份。也可指定一个尚不存在的目录；已有目录、文件或父路径冲突均拒绝，不覆盖旧产物：

```powershell
npm.cmd run demo:workflow -- --generate-only --output-dir runs/my-workflow
python -m dsh_eval --browse --cases-root runs/my-workflow/inputs --runs-root runs/my-workflow
```

默认随机选择空闲端口；生成并浏览时可用 `--port 8765`。生成模式退出 0 表示三个场景及独立复验符合预设，包括预期的 unevaluable 反例和规则翻转；它不表示每个样本任务都通过。输入读取、输出冲突、生成结果不符或服务绑定错误退出 2。生成期间人工中断退出 130；已写出的诊断产物保留，未完成时不发布成功索引。服务绑定失败时已经完成的产物仍可另行浏览。

## 输出与独立复验

| 文件或目录 | 内容 |
| --- | --- |
| workflow-index.json、index.md | 三个有序场景及实际保存结论、结果路径、来源和模型调用声明 |
| inputs/ | 公开用例派生的合成配置、实验清单、预先固定的四条回复和候选规则 |
| tasks/ | 完整步骤和漏步任务的 case、synthetic、evidence、runtime、evaluation 与真实 recorder 输出 |
| experiments/ | 两用例各两轮的冻结实验、批次和四份任务归档 |
| reports/ | 使用原冻结输入独立复验的四样本报告 |
| experiment-assertion-preview.json | 实验断言预览版本 1；四类转移、不可对照数量、逐项规则和证据关联 |
| archive-sha256.json | tasks、experiments、inputs 在复验前的逐文件 SHA-256，复验后再次核对 |

从索引选定一项任务，使用该任务目录下的冻结输入和证据独立评分；漏步反例退出 2 属于预期：

```powershell
python -m dsh_eval --case <任务目录>/case.json --evidence <任务目录>/evidence.json
python -m dsh_eval --report <实验目录>/experiment-result.json --reports-root runs/rechecked-reports
python -m dsh_eval --compare-experiment-assertions <实验目录>/experiment-result.json --candidate runs/my-workflow/inputs/strict-rule-map.json --output runs/rechecked-preview.json
```

源归档前后摘要一致仅证明本次离线操作未修改选定文件，不是签名或断电可靠保证。原运行路径使用现有本地归档约定；此入口不提供目录迁移工具。

## 执行边界与格式

`run_synthetic_case()` 在创建 evidence 时写入 `source=synthetic`，跳过 Harness 安装和仅针对安装器的 Windows 路径长度预检，其余文件创建、监督、清理、环境快照和评分仍使用实际代码。synthetic.json 版本 1 保存固定场景和可选最终回复，runtime 增加合成来源、模型未调用声明和脚本配置。evidence 和 evaluation 格式不变。

合成适配器同样应用用例 recorder 声明的 maxEventBytes / maxPendingBytes，输出目录仍固定于本次任务 traces。容量过小导致实际录制无法完整验证时，不会静默回退默认限额并判任务通过。[125 复查修正](changes/2026-11-09-125-workflow-diagnostics-review.md)

实验与批次使用内部 `_synthetic_replies` 映射，必须完整覆盖预先展开的样本或入口 ID，并在创建输出前检查；普通执行保持原调用路径。合成批次和实验标记 `executionMode=synthetic`、`modelCalled=false`，暂不声明 resumeSupportVersion 或实验 batchBinding，因此不能转入真实任务续跑。需要再次演示时生成一个新归档。

`workflowDemoFormatVersion=1` 是独立索引，保存 workflowId、workflowName、generatedAt、source、modelCalled、status、输出与报告路径，以及有序 scenarios（ID、标题、说明、结论和 evaluationPath / previewPath）。浏览器仅打开配置根目录内的关联文件。预览的源证据按钮额外核对 caseRunId、runId、sessionId；事件定位继续核对原始行的运行身份和序号。原文使用文本节点显示。

合成 assistant/message 仍计入现有 `metrics.modelCalls` 事件计数，评测页标为“合成模型事件”，不代表真实模型调用。没有模型用量时 token 和费用继续保持缺失。

2026 年 11 月 9 日批次 B 已增加[结构化原因与依赖](evaluation-format.md#结构化原因与依赖诊断124)。重新生成的任务含独立 assertionDiagnostics，页面在断言卡片之前显示首个缺证步骤和直接依赖链。漏步场景的 source-still-present 是原始缺证，target-still-missing、retry、verify 分别受前一项阻断。retry / verify 还可定位实际成功结果；明确保留前置未满足的警示及原 insufficient_evidence 结论。完整步骤展示通过链。生成器和独立复验同时核对这些诊断与原结论，不改变四样本规则影响。

批次 A 已有产物保持原样，缺少诊断时浏览器显示诊断不可用。需要新诊断可重新生成工作流，或使用冻结用例与证据离线评测到新文件；不能将浏览旧文件说成重新评分。实现与兼容验证见[124](changes/2026-11-09-124-structured-assertion-diagnostics.md)。
