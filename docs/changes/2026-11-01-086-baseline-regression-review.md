# 修改记录 086 基线比较边界复查与输入根类型修复

日期：2026 年 11 月 1 日，Asia/Shanghai。类型：修复 / 测试 / 审查 / 文档。插件版本：`0.1.2`。起始 HEAD：`f4009f539ab653e72afa880c08266827eca14df2`；本记录形成时 085 尚未提交。

## 问题与目标

复查 085 的可比性、缺失分类与退出码，发现非对象输入包含 experimentResumeResultFormatVersion 字样时会误入续跑分支：数组或字符串没有 get 方法，未处理的 AttributeError 使真实 CLI 退出 1，混淆输入错误与退化。新增反例先复现，再在分流前拒绝非对象 JSON。

## 文件修改

| 文件 | 修改前 | 修改后 | 原因 |
| --- | --- | --- | --- |
| dsh_eval/report.py | 按成员检查直接分流 | 先要求结果根节点为字典 | 畸形输入统一走 ValueError / 退出 2，不吞掉任意异常 |
| test/test_regression.py | 17 项比较回归 | 新增三项，扩展配置变化 / 路由检查 | 覆盖真实退出码、双向缺项、零共有项与精确允许字段 |
| 本记录、基线比较说明、CHANGELOG、docs/progress.md | 085 开发状态 | 补修复与复查依据 | 历史结果保留，当前范围单列 |

## 实现与技术取舍

共用 _load_report_inputs 在检查续跑标记前读取并校验对象类型，比较和原 --report 均受保护。未扩大 CLI 的异常捕获列表，不改变正常实验 / 续跑加载、样本复验、可比性规则或退出码优先级。

确认完整任务（除 configRef）严格一致、配置变化逐字段放行、每侧实际路由仍匹配自己的计划、来源逐对一致、执行身份不能复用。补测同时变化 model / provider 时只允许 model 仍返回 2；即使声明全部配置字段可变，错误实际路由、坏录制与断言证据不足仍不能参与结论转换。

新增缺项测试确认：基线两轮、候选一轮且该轮退化时，保留 regression=1 / missing_in_candidate=1，退出 2；反向比较保留 improvement=1 / missing_in_baseline=1。完全没有共同 entryId 时 compared=0，两侧缺项都列出，不能因没有退化而退出 0。

## 验证

2026 年 11 月 1 日，本地 Windows，无模型调用。

| 命令或操作 | 实际结果 | 范围 |
| --- | --- | --- |
| 修复前 `python -m unittest discover -s test -p test_regression.py -k non_object` | 1 项测试，4 处子用例错误 / 1 处失败；真实 CLI 退出 1 并有 Traceback | 两侧数组 / 字符串包含续跑标记时复现误分流 |
| 加根类型校验并扩展边界后的 test_regression.py 首次全跑 | 20 项 / 26.547 秒，1 处夹具错误 | 新配置双字段测试用了运行器不支持的非 headless profile，在执行准备前被拒绝；改用两个可由合成适配器记录的 model / provider 字段，不放宽运行器 |
| `python -m unittest discover -s test -p test_report.py` | 原 17 项通过 / 21.495 秒 | 共用加载入口修复后的原报告兼容 |
| 改用 model / provider 夹具后 `python -m unittest discover -s test -p test_regression.py` | 20 项全部通过 / 25.790 秒 | 新增三项及扩展的允许字段 / 路由反例，包含真实 CLI 输入错误 2 |
| `python -m compileall -q dsh_eval scripts test`、`git diff --check` | 通过 | 编译与补丁检查 |
| 改动 Markdown 的相对路径、标题锚点和忽略目标检查 | 9 份文档、464 个本地链接 / 115 个目标通过 | 公开链接不依赖私人或运行目录 |
| `git ls-files -- runs private-notes` | 无输出 | 没有跟踪原始运行或私人资料 |

最终比较测试与文档检查已通过。085 的完整 420 Python 是上一轮本地结果，不冒充本轮新验证；提交后按精确 SHA 检查云端完整工作流。

## 风险与后续

修复限于输入根类型；比较仍要求稳定归档，只处理显式选定配置，不进行任务映射、统计显著性推断或模型运行。尚未提交 / 推送或取得本轮新 CI 结果，不预先写为成功。

## 文档同步

更新基线比较说明、进度与 CHANGELOG；085 历史测试和限制保持原样。
