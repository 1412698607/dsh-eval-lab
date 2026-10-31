# Windows 执行输出根预检

更新：2026 年 11 月 1 日，Asia/Shanghai。Python 的单用例、批次、实验和两类续跑执行入口共用当前 Windows Harness 安装目录长度检查。它在创建新执行身份与输出之前排除已知过深目录，提示选择更短的 `--runs-root`；不调用宿主或模型。

## 覆盖的布局

下表的 root 为本次实际选中的 `--runs-root`，省略时使用对应默认值。每个身份按标准 36 字符 UUID 预留长度，不生成随机身份。

| 入口 | 默认 root | root 以下的单项目录 | UUID 层数 |
| --- | --- | --- | ---: |
| --case --run | runs/evaluation | caseRunId | 1 |
| --batch --run | runs/batches | batchId/cases/caseRunId | 2 |
| --experiment --run | runs/experiments | experimentId/batches/batchId/cases/caseRunId | 3 |
| --resume-batch --run | runs/resumes | resumeId/batches/batchId/cases/caseRunId | 3 |
| --resume-experiment --run，含连续续跑 | runs/experiment-resumes | resumeId/continuations/batchResumeId/batches/batchId/cases/caseRunId | 4 |

检查将 root 转为绝对解析路径，再追加对应布局及 `home/profiles/headless/.plugin-manager/logs/operation-XXXXXX`；六个 X 对应 Node mkdtemp 的六字符后缀。整个预计目录按 UTF-16 单元计量：247 单元接受，达到 248 单元拒绝。非 BMP 字符占两个单元，不能只按 Python 字符个数判断。

这是当前普通 Windows 安装目录的保守限制。实际 Node 临时目录检查在本机验证了 247 成功、248 拒绝；接受只表示没有命中该长度限制，不保证路径权限、文件名、宿主版本、准备成功或未来模型结果。

## 检查顺序与失败行为

- 单用例先读取并校验用例、headless / 插件版本及显式身份参数，再检查输出根，然后才分配新 caseRunId、创建目录和保存快照。
- 批次先校验清单及全部用例，再检查完整两层布局，然后才分配新 batchId 和冻结输入。每个单用例仍检查自身实际输出根。
- 实验先校验全部用例 / 配置组合、完整任务数上限及预期计划指纹，再检查完整三层布局，随后才分配实验 / 批次身份和保存计划。内层批次、单用例继续检查实际布局。
- 续跑仍在源锁内重新复验并比较 fresh plan 摘要，再检查三层 / 四层布局；检查在新的身份、输出和领取之前，源的单次续跑资格保持不变。详见 [批次续跑](batch-resume.md) 与 [实验续跑](experiment-resume.md#windows-输出根检查)。

长度拒绝沿用既有输入错误 JSON，`outcome=unevaluable`、包含 error 字符串、退出码 2，没有新的执行结果文件。错误包含所需 UTF-16 单元数、247 上限及缩短 `--runs-root` 的提示；普通入口说明没有创建执行输出，续跑入口继续说明没有领取续跑资格。

调用方可以改用更短的绝对输出根后重试，不需要删除或改写原始证据。以下只是运行示例，实际执行会调用清单中配置的模型：

```powershell
python -m dsh_eval --batch fixtures/evaluation/recovery.batch.json --run --runs-root C:/r
```

实验 / 续跑的 `--plan` 没有未来输出根，不调用该检查，也不接受 `--runs-root`；预检通过不保证后来选择的输出根可用。路径控制不进入输入清单或计划指纹，不截断任务矩阵，也不绕过原有输入、断言和失败策略。

## 验证与限制

[071](changes/2026-11-01-071-live-token-stop-acceptance.md) 另在通过检查的短根执行两个用例的四层 UUID 真实 CLI 离线准备，进程均退出；随后普通实验及首轮 / 连续续跑完成四项真实任务，报告和来源关联通过复验。这补充当前短根的端到端证据，未新增独立单用例 / 批次 CLI 的模型验收，也不代表扩展路径或全部 Windows 写入路径已兼容。

[069](changes/2026-11-01-069-execution-output-path-preflight.md) 增加普通入口的前置检查，并让续跑共用同一实现。定向验证覆盖五种布局的 247 / 248 和非 BMP 边界、默认根、创建身份前拒绝、输入 / 指纹优先、真实 Python CLI 无输出拒绝及真实 Node 临时目录边界。旧续跑的无领取、源摘要不变和重新预检行为继续验证。

合成宿主测试不安装真实 Harness，夹具会显式替换该物理安装限制；专用路径测试保留真实检查。合成测试不代表真实模型或长目录宿主端到端验收。

其他平台不套用该 Windows 限制。独立的 `live:prepare`、Web 生命周期脚本及所有可能的 Windows 写入路径不属于本检查的覆盖保证；未接入扩展路径原型，也没有归档搬迁、历史路径重写或模型会话恢复能力。
