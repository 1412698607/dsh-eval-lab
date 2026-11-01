# 修改记录 069 普通执行入口的 Windows 输出路径预检

日期：2026 年 11 月 1 日，Asia/Shanghai。本轮工作跨 2026 年 10 月 31 日至 11 月 1 日。类型：修复 / 重构 / 测试 / 文档。插件版本：`0.1.2`。相关 Git 提交：尚未提交；已核实起始 HEAD 为 `ee7a9bd558f687fdeef8ea70026370d686589ad1`。

## 问题与目标

062 只在批次 / 实验续跑领取前检查已知 Windows 宿主安装目录限制。普通 run_case、run_batch 和 run_experiment 没有等价的创建输出前检查，过深根仍可先创建身份与归档，再进入注定不适用的普通目录准备路径。

本批将现有保守边界统一为五种布局的共用检查，并补齐普通执行入口，保证已知路径过深时在新身份和输出之前明确拒绝。保留输入校验、实验任务数 / expected 指纹以及续跑源复核的顺序；不移动旧归档或接入扩展路径原型。

## 文件修改

| 文件 | 修改前 | 修改后 | 原因 |
| --- | --- | --- | --- |
| dsh_eval/output_paths.py | 无共用执行布局检查 | 集中五种布局、安装后缀、UTF-16 计量和拒绝提示 | 避免普通执行与续跑各自维护不同长度规则 |
| dsh_eval/runner.py、batch.py、experiment.py | 可在检查深目录前创建新身份 / 产物 | 输入与显式参数校验后、UUID / 目录之前检查各自完整布局 | 提前拒绝已知不适用的根 |
| dsh_eval/resume.py | 内部独立计算三层 / 四层布局 | 保留原包装函数，委托共用检查 | 保持源锁、fresh 摘要和无领取语义 |
| test/test_execution_output_paths.py | 无普通入口路径回归 | 九项检查覆盖五种布局、输入顺序、默认根、预览、真实 CLI 和 Node 边界 | 不以 mock 代替实际文件系统边界 |
| test/test_resume_output_paths.py | 针对旧内部实现替换平台 / 恢复检查 | 改为共用实现的实际所属模块，路径测试恢复真实共用检查 | 六项旧续跑断言继续约束实际行为 |
| test/test_batch.py、test_batch_resume.py、test_browser.py、test_experiment.py、test_experiment_resume.py、test_guarded_acceptance.py、test_guarded_comparison.py、test_model_providers.py、test_recorder_options.py、test_report.py、test_report_plan_snapshot.py | 无模型夹具替换宿主准备，未替换新物理路径预检 | 同时显式替换不执行的真实安装目录限制 | 长临时根不干扰合成输入 / 锁 / 报告验证，路径行为由专用测试验证 |
| README、docs/output-paths.md、single-case-runner.md、batch-runner.md、experiments.md、experiment-resume.md | 普通入口没有统一预检说明 | 记录完整布局、拒绝顺序、重选根及覆盖限制 | 运行方式与新增行为一致 |
| docs/architecture.md、progress.md、plans/m6-reliability-validation.md、CHANGELOG、本记录 | 路径加固仍只有续跑范围 | 同步共用实现、工作区状态与无模型验证 | 历史结果和未覆盖范围分开保留 |

## 实现与技术取舍

1. check_output_root 接收实际选中的根和内部布局名称。标准 UUID 固定预留 36 字符，五种布局分别包含一、二、三、三、四层身份；末尾统一为 home/profiles/headless/.plugin-manager/logs/operation-XXXXXX。构造占位路径不生成随机执行身份，也不创建目录。
2. Windows 使用绝对解析路径的 UTF-16 单元数，保持 247 接受、248 拒绝；非 BMP 字符按两个单元计量。其他平台不套用该限制。路径过深时仍抛出 ValueError，由现有 CLI 返回输入错误 JSON / unevaluable / 退出 2。
3. 普通单用例先校验用例 / 配置及显式身份；批次先验证全部用例；实验先验证全部组合、完整任务数上限与 expected 摘要。通过这些检查后才做输出根预检，再生成新 UUID 和写文件。显式 UUID 参数仍先校验合法性。
4. 实验 / 批次 / 单项的各层检查按实际根分别计算，预测的最终单项安装路径一致。续跑保留原外层检查及批次核心的再次复核，发生位置仍在源锁及 fresh 复核之后、领取之前；错误继续明确没有领取。
5. 采用前置拒绝而非自动改写输出根，避免实际目录与调用方选择不同。没有验证扩展路径的完整运行、证据和报告链路，因此仍不接入准备原型。没有修改输入、录制、结果格式或计划指纹，也不降低任何任务断言。

## 验证

环境：Windows，Python `3.12.0`、Node.js `v24.14.0`。本批没有模型调用或真实宿主安装；真实 Node 检查只创建独立临时目录，真实 Python CLI 在宿主准备前拒绝。

| 命令或操作 | 实际结果 | 证明的范围 |
| --- | --- | --- |
| `python -m unittest discover -s test -p test_*output_paths.py -v` | 十五项 / 5.596 秒，OK | 九项新增普通入口检查与六项既有续跑检查 |
| `python -m unittest discover -s test -p test_*.py -v`（允许真实子进程环境） | 378 项 / 257.103 秒，OK，0 失败 / 错误 / 跳过 | 含九项新增检查、旧续跑 / 指纹 / 报告 / 用量控制、真实进程监督及 Web 生命周期合成检查；未调用模型 |
| 上述五种布局的 ASCII / 非 BMP 边界 | 247 接受；加一个 ASCII 或用非 BMP 替换一个 ASCII 后为 248，均拒绝 | UTF-16 计量及完整安装后缀预留，未创建实际执行输出 |
| 上述真实 Python CLI 三入口深根拒绝 | 单用例 / 批次 / 实验均退出 2、stdout 为输入错误 JSON、stderr 为空，源文件与目录快照不变 | 不分配新执行产物，不安装宿主或调用模型 |
| 上述真实 Node mkdtemp | 最终普通目录 247 单元成功；248 返回 ENAMETOOLONG 或 ENOENT | 当前 Windows / Node 实际目录边界，不证明其他安装路径均可用 |
| `npm.cmd test`（允许真实子进程环境） | 91 项通过，0 失败 / 跳过 | 既有宿主、录制与前端行为回归 |
| `npm.cmd run check` | 43 份 JavaScript 语法通过 | JavaScript 既有文件保持兼容 |
| `python -m compileall -q dsh_eval scripts test` | 退出 0 | 当前 Python 实现与测试可编译 |
| Python 扫描本轮十一份 Markdown 的链接 / 锚点、Git 跟踪及忽略规则 | 453 个本地链接、98 个不同目标，零错误 | 公开目标存在、未被忽略且已跟踪或属于本次新增资料 |
| `git diff --check`、按路径核对 062 / 067 / 068 历史记录、`git ls-files -- runs private-notes secrets` | 补丁 / 历史记录检查退出 0，隔离目录无已跟踪文件 | 历史记录未覆写，原始产物和私人资料未纳入 |

合成宿主夹具显式替换物理安装预检，仍通过真实 Node 适配器、录制器和 fresh inspect 验证原任务 / 报告语义；专用路径检查不使用该替换。实验预览仍不检查未来输出根，错误输入及错指纹先于路径拒绝。

## 风险与后续

普通执行现在会提前拒绝已知过深的根，不再先创建一份注定在宿主准备遇到该限制的执行归档。这是输入错误，不是模型任务失败；接受根也不保证权限、文件名、安装、网络或任务结果。

此检查只覆盖 Python 评测入口的已知普通安装临时目录。独立 live:prepare / Web 脚本、其他 Windows 写入路径、扩展路径和归档迁移仍未纳入保证；没有恢复模型会话或重写历史绝对路径。旧路径失败、真实样本和 062 / 067 / 068 的验证记录不覆写。

本批没有提交 / 推送、触发新 CI 或新增真实模型验收；起始提交的 CI 不能替代本批验证。

## 文档同步

新增共用输出根说明，同步 README、单用例 / 批次 / 实验 / 续跑入口、架构、进度、M6 顺序及 CHANGELOG；链接仅指向可提交文件，不加入真实原始归档或凭据。
