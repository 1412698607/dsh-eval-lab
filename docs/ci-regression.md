# 无模型CI回归门禁示例

本示例复用[基线比较](baseline-regression.md)，从公开用例生成四份独立合成实验，调用真实CLI验证退出码，不调用模型、不安装Harness。需要Python3.12+、Node.js22.8+。

当前实现、本地复查及云端验证状态见[135修改记录](changes/2026-11-09-135-synthetic-ci-regression-gates.md)和[136复查记录](changes/2026-11-09-136-synthetic-regression-review.md)。

## 本地运行

在项目根目录执行：

```powershell
npm.cmd run demo:regression
# 自动化可指定一个尚不存在的目录：
npm.cmd run demo:regression -- --output-dir runs/ci-regression-demo
```

默认写入新的`runs/regression-demo/<uuid>/`。指定目录已存在（包括悬空链接）时退出2且不覆盖；再次运行默认命令生成新的实验和运行身份。完整源文件位于inputs / experiments，比较产物单独位于artifacts。生成器输出JSON索引并退出，不启动浏览服务。

冻结用例、配置、entryId和两轮重复在四个独立实验中相同，行为在运行前固定：

| 场景 | 基线 | 候选 | 比较结果与原退出码 |
| --- | --- | --- | --- |
| no-regression | 两项通过 | 两项通过 | 两项unchanged_passed，0 |
| regression | 两项通过 | 第一项回复WRONG，第二项通过 | 一项regression、一项unchanged_passed，1 |
| incomplete | 两项通过 | 第一项回复WRONG，完成一项后按stop_after=1停止 | 一项regression、一项unavailable，2；已确认退化保留 |

四个实验共执行七次合成任务，使用真实工具子进程、录制器和独立inspect。三个比较使用新CLI进程重新检查双方证据；生成器核对进程退出码、比较状态、计数和来源，并检查比较前后源文件摘要不变。覆盖不足场景通过正常调度停止构造，不删除或重写保存证据。

演示退出0表示三种预设结果都符合预期，**不表示三个候选都通过门禁或模型任务全部通过**。输入 / 生成 / 预期核对错误退出2，中断退出130；发生错误时可能留下未完成目录。

## CI摘要与产物

[确定性工作流](../.github/workflows/deterministic.yml)在原检查后运行演示，把summary.md发布到作业摘要，并上传明确列出的五份文件：

- no-regression.json、regression.json、incomplete.json：原比较器的完整JSON结果；
- summary.md：场景、退出码、覆盖和已确认退化；
- index.json：版本1演示索引及源摘要。

产物名包含run_id和run_attempt，保留7天。摘要和上传步骤在失败后仍处理已存在文件，早期失败没有文件时跳过 / 警告；没有continue-on-error，不覆盖原失败。上传只列出五个固定路径，源inputs、experiments、JSONL及其他runs目录不上传。原始失败诊断仍查看作业日志；下载比较文件需使用Actions产物入口。

这些产物只包含固定合成数据的比较结论。保存路径指向原CI工作目录，下载后的五文件集合不包含完整证据，不能当作可独立重评的归档包；本地重新运行命令可生成一套新的完整输入。把下载目录设为浏览根后，可在[基线回归比较页面](baseline-regression.md#比较浏览)查看三份比较；缺少配置范围内的完整源时，双方证据提示不可用。需要搬迁既有证据时使用[只读归档包](archive-bundles.md)。

## 在真实门禁中使用

将已有稳定实验交给原比较命令，保持非零退出码，例如PowerShell步骤：

```powershell
python -m dsh_eval --compare-baseline 'runs/experiments/<baseline-id>/experiment-result.json' --candidate 'runs/experiments/<candidate-id>/experiment-result.json' --output 'runs/regression.json'
exit $LASTEXITCODE
```

输出父目录须存在，输出文件须尚不存在。这里0表示完整可比且无退化，1表示完整可比且有退化，2表示覆盖不足、不可比或输入错误。真实门禁不使用演示程序的“预期反例成功”语义，也不通过忽略错误或强制exit0绕过1 / 2。

该演示不自动选择真实实验、不调用模型、不配置分支保护，也不从固定合成样本推断模型可靠性、总体胜率或性能变化。浏览页面只显示保存结论及可访问关联，不自动生成新比较。
