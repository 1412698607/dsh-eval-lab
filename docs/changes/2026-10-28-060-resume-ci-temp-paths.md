# 修改记录 060 连续续跑交付复查与 CI 临时路径修复

日期：2026 年 10 月 28 日，Asia/Shanghai。类型：修复 / 测试 / 文档。插件版本：`0.1.2`。相关 Git 提交：本批尚未提交；起始基线为已核实的 `967ab431ac80dc316c1130be8f3826aa610be0ae`，工作区已有 059 的连续续跑修改。

## 问题与目标

交付复查发现基线 [CI run 40538012395](https://github.com/1412698607/dsh-eval-lab/actions/runs/40538012395) 的 Python 步骤失败。精确 head SHA 为 967ab43、attempt 1、job 122308429621。JS 语法和 90 项 Node 回归通过；322 项 Python / 205.309 秒中有一项 failure、四项 error，后续编译和合成示例步骤被跳过。此前进度将此提交的云端状态保留为未核对，本记录补充实际失败原因，不覆盖原本地通过结果。

五项失败均来自测试临时根使用 Windows 短路径 RUNNER~1，而运行器保存的是 resolve 后的长路径。报告的原始文件摘要快照无法 relative_to 未解析的根，领取目录的直接比较也将同一目录当成不同路径。本批修复共享测试夹具的根目录表示，并复查 059 的链路与交付检查。

## 文件修改

| 文件 | 修改前 | 修改后 | 原因 |
| --- | --- | --- | --- |
| test/test_experiment_resume.py | 共享夹具保留 TemporaryDirectory 返回的路径拼写 | 建立输入前将临时根 resolve | 实验、报告、连续续跑夹具与运行器使用一致的目录表示，保留原有身份和摘要断言 |
| docs/plans/m6-reliability-validation.md | 开头仍写第二配置尚未选择，后续步骤分散 | 同步 050 / 059 当前范围，列出交付、六项真实连续续跑候选、八项双配置比较及后续加固顺序 | 区分已实现、合成验证和待执行的真实验收 |
| docs/progress.md、CHANGELOG、本记录 | 缺少基线失败原因和独立复验 | 记录实际故障、修复范围与本轮检查 | 保留历史验证和对应提交边界 |

## 实现与技术取舍

只在共享测试夹具创建时规范化临时根，报告快照和领取比较继续保留原有断言；没有修改产品路径校验、锁、执行或报告统计逻辑。059 的来源链、全部批次持锁、重复领取、running 外层绑定、最终写入失败及版本 1 / 2 / 3 兼容列入复查和现有回归范围。

使用 Windows GetShortPathNameW 取得实际存在的短路径，将其作为 tempfile.tempdir 后执行原五项失败测试。修复前在本机重现同样的一项 failure / 四项 error，排除仅靠字符串替换或模拟 Path.resolve 得到的结论；修复后继续用相同条件复验。此处规范化的是别名，不是支持更长的宿主输出路径。

## 验证

环境：Windows、Python `3.12.0`、Node.js `v24.14.0`。本轮检查不调用模型，保留真实 Python / Node 子进程和内核锁。

| 命令或操作 | 结果 | 证明的范围 |
| --- | --- | --- |
| GitHub Actions run / jobs / 原始日志只读核对 | SHA 匹配，取得 322 项测试的一项失败 / 四项错误及完整堆栈 | 基线真实云端失败，不能由本地通过替代 |
| `python -m unittest discover -s test -p test_experiment_resume_chain.py` | 18 项 / 74.490 秒，OK | 059 连续续跑、锁、领取、损坏 / 未知项、收尾与报告回归 |
| `npm.cmd run check` | 43 个 JS 文件通过 | JavaScript 语法 |
| `npm.cmd test`，首次受限环境 | 89 / 91 通过，两项真实子进程启动为 spawn EPERM | 不计完整通过 |
| 同一 `npm.cmd test`，允许真实子进程的环境 | 91 / 91 通过，无失败 / 跳过 | 原录制、宿主生命周期及版本 3 前端兼容 |
| `npm.cmd run test:python`，修复前普通临时根 | 341 项 / 227.287 秒，OK | 本地正常路径的原有全量结果；未覆盖云端短路径差异 |
| 实际短路径根，修复前执行原五项 CI 故障测试 | 5 项 / 11.553 秒，1 failure / 4 errors | 本地重现云端相同故障 |
| 实际短路径根，修复后执行同五项测试 | 5 项 / 14.310 秒，OK | 保留原断言，云端故障在本地相同条件下消失 |
| 实际短路径根，修复后完整 Python discover | 341 项 / 226.231 秒，OK、无跳过 | 全量回归覆盖短路径夹具、连续续跑、报告和真实子进程清理 |
| `python -m compileall -q dsh_eval scripts test` | 退出 0 | Python 编译 |
| `npm.cmd run demo:eval` | 两个 synthetic 示例生成，modelCalled=false | 与 CI 相同的无模型示例入口 |
| `git diff --check` | 退出 0 | 当前补丁空白检查 |
| 修改 / 新增 Markdown 本地链接核对 | 11 份文档、377 个本地链接均存在且未被忽略 | 公开导航无需本地私人资料 |

实际短路径下的全量复验可在项目根执行以下 PowerShell 命令。系统必须能为新建临时目录返回不同的实际短路径，否则明确报错，不能把普通路径运行当作别名复验：

```powershell
@'
import ctypes
from pathlib import Path
import tempfile
import unittest

with tempfile.TemporaryDirectory(prefix="dsh-ci-path-") as root:
    buffer = ctypes.create_unicode_buffer(32768)
    size = ctypes.windll.kernel32.GetShortPathNameW(root, buffer, len(buffer))
    if not size or Path(buffer.value) == Path(root):
        raise RuntimeError("Actual Windows short path is required")
    previous = tempfile.tempdir
    tempfile.tempdir = buffer.value
    try:
        result = unittest.TextTestRunner().run(
            unittest.defaultTestLoader.discover("test", pattern="test_*.py"))
    finally:
        tempfile.tempdir = previous
raise SystemExit(not result.wasSuccessful())
'@ | python -
```

## 风险与后续

本批不修改生产格式、执行范围或历史失败。059 的真实模型连续续跑尚未验收；当前候选为两用例 / 单配置 / 三轮共六项，需先验证任务边界停止入口，再按原矩阵运行和独立复验。原 050 因 stop 失败而跳过的四项继续保留，不作为续跑验收来源。

短路径别名修复不解决宿主深目录准备失败或 059 页面准备的 WinError 5。原子替换及内核锁仍不提供 fsync、多文件事务或断电恢复保证。当前新提交的云端结果须在提交后独立核对。

## 文档同步

更新进度、M6 当前后续顺序及 CHANGELOG，059 与更早修改记录保留当时快照。未改变架构、数据格式和用户运行命令，README 与 architecture 本批无需新增改动；已有 059 的更新保留。
