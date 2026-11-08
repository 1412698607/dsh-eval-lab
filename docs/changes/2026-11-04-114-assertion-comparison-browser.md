# 修改记录 114 同轨迹对照结果浏览

日期为 2026 年 11 月 4 日（Asia/Shanghai）。插件版本 0.1.2。实现基线为 `28490d1`，本批尚未提交。

## 目标与实现

[112](2026-11-04-112-same-trace-assertion-comparison.md) 生成的 JSON 对照报告增加只读浏览入口。

- [browser.py](../../dsh_eval/browser.py)识别版本 1 对照文档及约定的 `assertion-comparison.json` 文件名。目录支持按报告类型、来源和候选结论筛选。
- [前端](../../dsh_eval/web/app.js)并排显示两侧任务、执行、录制及规则摘要，按 ID 展示定义、原文、单项结论、顺序与证据变化，提供“只看变化”选项。
- 事件跳转复用现有轨迹接口。在可访问根目录内读取证据，并核对 runId、sessionId、caseRunId 后才建立关联。超出范围或身份不符时保留报告展示，停用事件关联。

## 验证

`python -m unittest discover -s test -p test_browser.py` 39 项、`node --test --test-isolation=none test/browser.test.js` 38 项通过。覆盖变化筛选、同规则自比、增删项、仅证据变化、inconclusive、事件跳转和旧报告兼容。`npm.cmd run check` 检查 45 个 JavaScript 文件通过。

复核发现报告和证据同时缺少 caseRunId 时，缺失值相等可能误启用事件跳转。修正为三种身份都必须非空且相等，补齐双侧缺少三个字段的反例。修正后的三项比较读取和三项对照前端定向检查通过。四份 112 历史对照均可读取，原始事件位置可以核对。

本轮完整 Python 519 项通过（341.828 秒），完整 Node 130 项通过。全量启动后补齐的身份边界调整另在最终完整 39 项 Python 浏览回归中复验通过。

## 文档同步与边界

同步 README、[浏览说明](../result-browser.md)、进度及索引。页面展示保存结论和原文，浏览本身不会执行评测；原事件内容继续通过文本节点呈现。
