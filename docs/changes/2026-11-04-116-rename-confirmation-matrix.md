# 修改记录 116 重命名确认与超时矩阵

日期为 2026 年 11 月 4 日（Asia/Shanghai）。插件版本为 0.1.2。基线为 `28490d1`，本批尚未提交。

## 目标与公开输入

新增[确认词用例](../../fixtures/evaluation/rename-confirmation.case.json)和[重命名超时重试用例](../../fixtures/evaluation/rename-timeout-retry.case.json)。任务提示预先允许单词 done 的大小写、整词加粗和一个英文句号；确认词匹配是必需项，精确 done 为诊断项。

超时用例的首次 rename 延迟 1500 ms、工具期限 1000 ms，随后延迟为零。断言要求收到超时后先读源，再确认目标 NOT_FOUND，然后重试并读回。每份用例均恰好要求两次 rename，最终映射精确保留目标的 CRLF 内容和 guard 文件。

[实验](../../fixtures/evaluation/rename-confirmation.experiment.json)固定为两个用例、DeepSeek Flash 单配置、两轮，共四项，failurePolicy 为 continue。每任务 timeoutSeconds=120，准备与清理另计。此限制不代表任务内 token 或费用硬限额。

## 实现与验证

- [合成适配器](../../scripts/fixtures/mutation-adapter.js)新增两个脚本场景，使用 `**Done.**` 验证确认词通过、精确诊断失败。
- [组件入口](../../scripts/smoke_bridge.py)新增 `--rename-retry`，Node 对应[真实工具注册与 IPC](../../scripts/smoke-bridge.js)场景。
- `python -m unittest discover -s test -p test_rename_confirmation_matrix.py` 三项通过，包含完整四任务合成实验及报告。必需项通过，四个精确回复诊断均失败。
- `python -m scripts.smoke_bridge --rename-retry` 首次受沙箱 fork EPERM 限制，在允许子进程的环境复验六请求通过，modelCalled=false。既有 17 项变更回归及 10 项 Node 桥接回归通过。

## 边界与接续

本记录验证公开输入和组件。真实四任务结果单独记录，沿用冻结输入且保留失败。旧重命名用例与 109 的历史结果继续使用原规则。同步 README、用例目录、状态化工具、M6 计划及进度。
