# 修改记录 063 任务边界停止与连续续跑前置验证

日期：2026 年 10 月 29 日，Asia/Shanghai。类型：功能 / 测试 / 文档。插件版本：`0.1.2`。相关 Git 提交：本批尚未提交；已核实起始 HEAD 为 `3f229262a38b1a9229a01b2f90377ced075e09e6`，包含 061 补记与 062 路径保护。该提交新云端 CI 未独立核实。

## 问题与目标

连续续跑已能复核和调度明确未开始项，但缺少可重复使用的任务边界停止入口。通过打断正在执行的模型任务来形成剩余项，会产生未知执行与清理问题，不能用于稳定的原批次 / 两轮续跑验收。

本批增加可选本轮任务数停止控制，在已完成任务清理及检查点之后停止，保留完整原矩阵与无执行身份的剩余项；同时验证短路径完整布局下的真实宿主离线准备。当前不新增真实模型任务。

## 文件修改

| 文件 | 修改前 | 修改后 | 原因 |
| --- | --- | --- | --- |
| dsh_eval/batch.py | 仅按失败、中断及清理结果停止 | 可选 stop_after，完成检查点后停止，保存 stopAfter / stop_after 原因 | 保留下一项尚未开始的可核对边界 |
| dsh_eval/experiment.py、resume.py、experiment_resume.py、experiment_resume_chain.py | 无本轮任务停止控制，续跑外层不透传停止原因 | 执行入口透传参数，结果保存阈值及下游原因 | 本轮只计新批次尝试，跨轮保留完整矩阵 |
| dsh_eval/__main__.py | 无对应参数 | 四类 --run 支持正整数 --stop-after | 拒绝静态预览 / 单用例 / 报告 / 浏览的冲突组合 |
| test/test_scheduler_stop.py、test/test_experiment_fingerprint.py | 无公开边界入口链路回归，旧转发测试仅核对旧参数 | 十一项定向检查，更新默认转发预期 | 验证实际 CLI、策略、身份、源摘要及跨批次报告 / 浏览 |
| fixtures/evaluation/core/continuous-resume.experiment.json | 六任务候选仅在本地预览 | 公开两用例 / 单配置 / 三轮、失败即停候选 | 可复现无模型计划，不自动执行模型 |
| README、批次 / 实验 / 续跑说明、架构、进度、M6 方案、CHANGELOG、本记录 | 缺少边界停止语义，061 / 062 当前状态仍写未提交 | 同步运行控制、结果扩展、已有提交事实及验证范围 | 保留历史记录，不继承旧提交的云端结论 |

## 实现与技术取舍

`--stop-after N` 仅支持批次、实验、批次续跑和实验续跑的 --run。API 使用可选关键字 stop_after=None；入口在读源 / 分配身份 / 输出或领取之前拒绝布尔、非整数和非正值。调度器先核对实际结果与关联、确认清理并保存完成 checkpoint，再检查本轮计数；达到 N 且仍有剩余项时保存 stopped / stop_after，剩余项 skipped / stop_after，所有执行身份和结果保持 null。

失败、无法评测但允许 continue 的任务尝试同样计数。失败停止策略、清理不明、用户中断及 runner 错误优先处理，检查点失败不启动后项。N 等于或大于本批次项数时正常收尾，stopReason=null。续跑历史复用项不计入 N，不继承上一轮阈值，也不改变原失败策略和单次领取保护。

选择执行时单独传入停止控制，而非删减冻结清单，以保留完整分母、矩阵和剩余项依据。stopAfter 是运行元信息，与既有 host-modules / cancel-after-stream 一样不进入原计划指纹；expected SHA 继续约束原输入、规模及源证据，不约束该运行控制。maxSamples 仍检查完整计划 / 全部剩余数。新结果增加可选 stopAfter，续跑外层另透传 stopReason，格式版本、计划指纹算法和旧归档读取保持兼容。参数限制后续调度，不限制任务内模型请求数、token 或费用。

## 验证

环境：Windows、Python `3.12.0`、Node.js `v24.14.0`。定向与完整回归均为无模型检查；合成适配器仍实际启动 Node、使用 Python 工具环境、写入原录制格式并执行 fresh inspect。真实宿主验证仅执行 offline prepare。

| 命令或操作 | 结果 | 证明的范围 |
| --- | --- | --- |
| `python -m unittest discover -s test -p test_scheduler_stop.py -v` 初版 | 十项 / 9.289 秒，OK | API / CLI、停止与续跑、策略 / 清理 / 中断、检查点失败及任务上限 |
| 同命令，增加公开候选预览后 | 十一项 / 11.247 秒，OK | 增加原始候选无模型静态预检；合成链路覆盖原实验和两轮续跑 |
| `python -m dsh_eval --experiment fixtures/evaluation/core/continuous-resume.experiment.json --plan --max-samples 6` | valid=true、modelCalled=false，2 用例 / 1 配置 / 6 项 | 仅输入 / 规模验证；指纹 df54bafd7a735d83b47fcca384ec4cc048031964d6e9e1761ac6ec3580579055 与 061 相同 |
| 真实 `runner._prepare`，两个新目录各四层 UUID | direct-read / retry-once 均 prepared=true、processStarted / processExited=true、pathsMatched=true；预计 operation 路径均为 241 UTF-16 单元 | 普通短根离线准备及 home / workspace / controlPatch 关联；CLI / SessionStore 0.2.0-rc.2、Cordis 4.0.4，没有执行 case-host run |
| `npm.cmd run test:python` 首轮受限环境 | 338 项 / 231.108 秒，一失败 / 五错误 | 旧 CLI 转发断言遗漏新增默认 stop_after=None；四项进程树清理及一组生命周期准备受进程权限限制。已更新前者测试预期，后者保留实际环境结果 |
| 同命令，最终允许真实子进程环境 | 358 项 / 224.949 秒，OK，无失败 / 跳过 | 完整无模型回归，包含十一项新增边界停止检查、旧转发断言修正和真实生命周期子进程 |
| `npm.cmd test` 首轮受限环境 | 91 项，89 通过 / 2 失败，spawn EPERM | ConPTY 生命周期子进程未能启动，不能记为通过 |
| 同命令，允许真实子进程环境 | 91 项全部通过，无失败 / 跳过 | 原录制、浏览、真实进程退出兼容 |
| `npm.cmd run check` | 43 个 JavaScript 文件通过 | JS 语法 |
| `python -m compileall -q dsh_eval scripts test` | 退出 0 | Python 语法 |
| 修改 / 新增 Markdown 链接、补丁及跟踪检查 | 十份文档 / 404 个本地链接存在且未被忽略，git diff --check 通过；runs / private-notes / secrets 无已跟踪文件 | 公开资料导航及产物隔离 |

六任务合成实验通过真正的 CLI 参数执行 2 / 2 / 2，不注入 KeyboardInterrupt 形成边界；完成 checkpoint 的下一项仍 pending / 空身份。逐轮预检 reused / newSamples 为 2 / 4、4 / 2，每轮仅新增两项，六个执行身份唯一。最终版本 3 报告六项 verified / synthetic、历史复用 4 / 本轮新增 2；只读浏览能到达六份轨迹，全部历史已有文件摘要不变。另覆盖批次入口停止 / 再续跑及重复领取拒绝。

真实准备的可复现步骤如下；使用新的短根和 UUID，只进入准备阶段。例示 C:/r 必须可写且能通过当前长度检查，产物不加入版本管理。

```powershell
@'
from pathlib import Path
from uuid import uuid4
from dsh_eval.formats import load_json
from dsh_eval.resume import _check_resume_output_root
from dsh_eval.runner import ROOT, _prepare, prepare_workspace, save_json
root = Path('C:/r').resolve()
_check_resume_output_root(root, experiment=True)
for name in ('direct-read', 'retry-once'):
    ids = [str(uuid4()) for _ in range(4)]
    directory = root / ids[0] / 'continuations' / ids[1] / 'batches' / ids[2] / 'cases' / ids[3]
    directory.mkdir(parents=True, exist_ok=False)
    case = load_json(ROOT / 'fixtures/evaluation/core' / (name + '.case.json'))
    save_json(directory / 'case.json', case)
    prepare_workspace(directory, case)
    report = {}
    _prepare(directory, None, report)
    setup = load_json(directory / 'setup.json')
    for key, suffix in (('home', 'home'), ('workspace', 'workspace'), ('controlPatch', 'control.patch.yml')):
        assert Path(setup[key]).resolve() == (directory / suffix).resolve()
        assert (directory / suffix).exists()
    assert report['processStarted'] and report['processExited']
    print(name, 'prepared, exited, paths matched; no model task')
'@ | python -
```

## 风险与后续

仅完成任务边界入口及当前无模型前置范围，真实六任务连续续跑与新双配置八任务比较仍待执行。061 的深目录失败与扩展路径单次准备原型保留，062 的保守长度保护保持；短根下离线准备不证明远端模型、完整启动或所有 Windows 路径可用。已有失败停止批次、未知执行和清理不明继续阻断，不通过修改旧状态恢复资格。

本批没有新增模型样本、提交 / 推送或新云端 CI。061 / 062 已包含于起始 HEAD 的事实单独写入当前进度，不覆盖历史验证或将旧 CI 继承为本批验收。

## 文档同步

更新 README、批次 / 实验 / 两类续跑说明、架构、当前进度、M6 顺序和 CHANGELOG，公开候选只有预览入口；原始准备日志、路径和结果只保存在本地运行目录，公开 Markdown 不链接这些产物。
