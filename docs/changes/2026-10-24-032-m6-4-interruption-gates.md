# 修改记录 032 M6.4 中断验收门禁修复

日期：2026 年 10 月 24 日，Asia/Shanghai。类型：修复 / 测试 / 文档。插件版本：`0.1.2`。相关 Git 提交：基线 `2c60b638d437b2d2b6afd09830bef5e147937924` 已核实，本批尚未提交。

## 问题与目标

本批修复 M6.4 审查中的两个问题，补充回归并同步文档，不运行真实模型。本批开始时分支为 `20261024/feat/m6-4-web-lifecycle`，030 / 031 的未提交改动已存在，全部保留。

031 的中断分支仅要求 fresh inspect 返回 unverified，运行与会话仍为 recording，存在两种误通过：

1. 将 run.json 的 statusFormatVersion 改为 2 后，inspect 已明确表示不支持运行状态格式，验收器仍返回 verified=true。
2. afterSeq=2、日志有三条事件，但状态检查点为空或仅覆盖前一 / 两条事件时，inspect 按通用规则保留 unverified，验收器仍判为中断通过，不能证明操作前的 flush 已覆盖该序号。

目标是在专用生命周期验收器收紧中断正例，保留通用录制检查语义、现有协议与正确录制的兼容性。031 原测试通过是历史事实，不包含这两类反例；本记录补充修正其验证覆盖范围。

## 文件修改

| 文件 | 修改前 | 修改后 | 原因 |
| --- | --- | --- | --- |
| `scripts/verify_web_lifecycle.py` | 版本检查不完整；afterSeq 仅关联日志序号 | 明确录制版本，排除额外未确认原因，比较状态检查点与完整已观察前缀 | 拒绝两个已复现的中断误通过 |
| `test/test_web_lifecycle.py` | 17 项生命周期测试 | 新增 5 项，共 22 项；覆盖版本、空 / 落后检查点、非零序号、临时文件和 CLI 拒绝 | 验证反例及兼容边界 |
| `README.md`、`docs/web-lifecycle.md`、`docs/architecture.md` | 中断干净前缀的判定条件不完整 | 说明版本门禁、检查点覆盖和通用 inspect 的边界 | 保持使用说明与实现一致 |
| `docs/progress.md`、M6 方案、`CHANGELOG.md`、本记录 | 031 的验证范围 | 新增 032 修正、实际回归及后续入口 | 保留原历史结果 |

本批未修改 JavaScript 采集器 / fixture、原 recorder / inspect、dsh_eval 通用评测包、M2.3 脚本或 main.py。

## 实现与技术取舍

继续先调用原 Node inspect，随后明确要求 run.json 的 formatVersion / statusFormatVersion / runManifestFormatVersion 为整数 2 / 1 / 1；会话检查点版本为整数 1。布尔值、字符串、小数形式、缺失或未知版本不能借 unverified 进入中断正例。运行与会话仍须 recording / unverified，整体检查原因须与开放运行清单的原因一致，残留 .tmp 等额外未确认原因被拒绝；不匹配中文诊断文本。

原 inspect 已核对状态检查点与对应原始字节前缀，但允许其后存在未确认尾部。专用验收器读取状态文件，将 writtenCount、writtenBytes、firstSeq、lastSeq、sha256 与 fresh inspect 扫描到的完整前缀比较，要求非空、lastSeq 等于 afterSeq。fixture 在 flush 后不再追加事件，因此此阶段使用完整前缀相等条件；非零起始序号仍允许。这里复用 inspect 的扫描与摘要结果，没有在生产 Python 中另写摘要算法，也没有改变通用 inspect 对未封存日志的处理。

空 / 落后检查点仍可以是通用 inspect 的合法未确认录制；验收器保持 recording=unverified、verified=false、任务 unevaluable、断言 not_run，不将其伪装成日志损坏，也不将场景检查通过算作任务成功。正确三场景的分类、source=synthetic、liveWebVerified=false 及所有格式版本保持不变，历史原始文件不迁移。

## 验证

2026 年 10 月 24 日，在 Windows、Node.js `v24.14.0` / Python `3.12.0` 执行。进程回归直接使用获准环境，真实创建 / 退出 / 终止自己的专用 Node 子进程，不使用 mock 替代进程事实。本批没有启动 Harness / Web 服务或调用模型，也没有触发云端 CI。

| 命令或操作 | 实际结果 | 证明的范围 |
| --- | --- | --- |
| 先补测试，`python -m unittest discover -s test -p test_web_lifecycle.py -v` | 22 项执行，4 个方法中的 11 个反例失败，2.022 秒 | 旧实现确实接受未知状态版本、空 / 落后检查点及额外未确认原因，CLI 也误通过 |
| 修复后同一命令 | 22 项通过，1.956 秒 | 新增 5 项及原 17 项；非零起点正例、正确三场景及拒绝路径 |
| `npm.cmd run test:python` | 完整 185 项通过，49.510 秒 | 原 180 项及新增 5 项，无模型全量 Python 回归 |
| `npm.cmd test` | 79 项通过，失败 / 跳过均为 0 | 既有录制器及 Node 适配器回归 |
| `npm.cmd run check` | 38 个 JavaScript 文件通过 | JavaScript 语法 |
| `python -m compileall -q dsh_eval scripts test` | 通过 | Python 编译检查 |
| `npm.cmd run check:web-lifecycle -- <新输出目录>` | 三场景均 verified | 正常 completed / complete / passed，取消 cancelled / complete / unevaluable，中断 interrupted / unverified / unevaluable；后两项断言 not_run |
| 独立 Python CLI 对三份原采集及四份修改后的副本 fresh 复验 | 三正例退出 0；未知状态版本 / 空检查点 / 落后检查点 / 残留替换文件四反例退出 1 | 四反例均 verified=false、recording=unverified，所有 liveWebVerified=false；不继承旧 verification |
| 原文件摘要核对 | 77 份受保护源文件及此前录制、28 份本批原采集文件均未变化 | 修复与离线复验没有改写这些源文件或原证据 |

表中的新输出目录为每批独立目录。新增测试准备较早检查点时按原始行字节生成独立有效前缀，确保反例不是因错误摘要被 Node inspect 提前判为 invalid。新 CLI 输出仍使用新建模式，拒绝覆盖旧结果。

最终文档核对：55 份公开 Markdown / 363 个相对文件链接有效，未链接私人材料或运行证据；修改 / 新增文件的末尾换行与空白检查通过，progress 分支与实际 Git 一致。`git diff --check` 通过，仅有 LF / CRLF 提示；runs / private-notes 仍忽略且无跟踪文件。本批三份采集保存的专用 PID 再查均不存在，不扩张为任意外部进程树保证。

没有重跑历史真实模型、M2.3 Web、smoke:host / check:output、资源测量或云端 CI，不将其历史结果计为本批实测。

## 风险与后续

本次收紧仅适用于当前 synthetic 生命周期捕获。未来真实 Web 中断可能在操作之后继续出现少量在途事件，需要另行定义观察窗口与检查点关联，不能直接放宽为任意 unverified。旧格式或未知版本不自动降级通过，当前有效捕获仍可直接离线复验。

SHA-256 和过程清单不是签名；flush 不承诺 fsync、断电持久化、完整会话恢复或任意外部进程树清理。当前真实 Web 生命周期仍未实现 / 未验收。下一步接入实际 Web 启动、操作来源和只观察生命周期的采集器，再按另定配置与数量运行任务；双配置 / 重复扩展继续待预算。

## 文档同步

同步 README、Web 生命周期说明、architecture、progress、M6 方案、CHANGELOG。030 / 031 和既有验证历史保留。
