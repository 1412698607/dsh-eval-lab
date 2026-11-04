# 修改记录 111 确认词匹配与离线对照

日期为 2026 年 11 月 4 日（Asia/Shanghai）。插件版本 0.1.2。基线为 `b3bc3fa` 加 107–110 工作区改动，尚未提交。

## 目标与实现

[109](2026-11-04-109-live-rename-acceptance.md) 的最终回复是 `Done.`，严格断言期望 `done`。[110](2026-11-04-110-assertion-roles.md) 已允许选择回复是否影响总判定。本次增加单项匹配方式，供要求返回一个确认词、但允许少量排版差异的任务使用。

- [格式校验](../../dsh_eval/formats.py)仅在版本 2 的 `final_text` 上接受 `"match":"confirmation_token"`。期望值须为单个 ASCII 字母词。
- [评测器](../../dsh_eval/evaluate.py)比较整条回复，仅接受大小写变化、配对的整词加粗和最多一个英文句号。使用有限的拼写形式使 `**Done.**` 可以通过，同时拒绝 `not done`、`**done** but failed` 等带附加内容的回复。已有任务级证据核验、工具断言和角色聚合继续生效。
- [结果浏览器](../../dsh_eval/web/app.js)显示已保存的匹配规则、原文与单项结论。缺省精确匹配的结果行保留原结构。格式与示例见[确认词匹配](../evaluation-format.md#确认词匹配)。

## 同一轨迹的三种判定

使用 109 冻结归档的 `caseRunId=20f69dbb-6f65-4d56-8b87-3c5cce3d06cb`。复制其用例，仅为 `answer` 增加 `"match":"confirmation_token"`，仍作为必需项。三次分别运行 `python -m dsh_eval --case <相应规则用例> --evidence <原证据> --output <新的评价文件>`，没有执行新的模型任务。

| 规则 | 回复单项 | 任务 | CLI 退出码 |
| --- | --- | --- | --- |
| 109 原始必需、精确匹配 | failed | failed | 1 |
| 110 派生诊断、精确匹配 | failed | passed | 0 |
| 111 派生必需、确认词匹配 | passed | passed | 0 |

三份输出的实际文本都是 `Done.`，answerSeq 都是 48。核对原始规则及 110 派生规则与各自既有结果，除 evaluatedAt 外完全一致。111 的输出与原评测有相同的运行身份、配置、预算执行、执行与录制状态、指标及六条其他断言明细。原任务、公开用例与先前复验等共 22 份选定来源文件 SHA-256 保持一致。

## 限制与文档同步

`python -m unittest discover -s test` 通过全部 502 项（333.786 秒），`npm.cmd test` 通过 125 项。`npm.cmd run check` 检查 45 个 JS 文件，`python -m compileall -q dsh_eval scripts test` 通过。独立复核再次执行三种规则的离线 CLI，并检查 468 组匹配边界。21 份公开用例通过格式校验，本轮工作区 14 份变动文档共 654 个相对文件链接目标存在。

此匹配方式适用于单词确认语。中文短语、同义改写、任意 Markdown 渲染和多句自然语言含义都超出本规则范围。既有精确输出的用例、公开重命名用例及历史失败样本继续按原标准计分。已同步 README、架构、评测格式、浏览器说明、进度及修改索引。
