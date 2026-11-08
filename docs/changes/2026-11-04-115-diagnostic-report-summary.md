# 修改记录 115 诊断项报告汇总

日期为 2026 年 11 月 4 日（Asia/Shanghai）。插件版本为 0.1.2。基线为 `28490d1`，本批尚未提交。

## 目标与实现

单次评测已保存诊断项结果。批量报告新增覆盖和分项统计，使任务通过时出现的格式偏差可以定位。

- [diagnostics.py](../../dsh_eval/diagnostics.py)从重新评测的断言行统计声明数、四种单项状态及对应的异常 ID。
- [report.py](../../dsh_eval/report.py)在样本中增加 `diagnosticSummary`，无法取得 fresh 评测时为 null。报告总体、分组、来源与历史 / 新增分区使用同一统计。未声明诊断项且成功复验的旧输入为已知零，未复验样本进入缺失覆盖。
- 新报告增加“任务 passed 且有诊断 failed”的样本数。Markdown 中的样本表链接到对应独立评测文件，可以继续查看实际值和断言 ID。
- 浏览器显示相同覆盖和计数，并按样本列出异常诊断 ID，链接至独立评测。旧报告缺字段时继续按原数据展示。

## 验证

`python -m unittest discover -s test -p test_diagnostic_reports.py` 三项通过，覆盖不同单项状态、缺失证据、普通报告及续跑中历史和新增各一个样本。诊断统计由独立评测计算，既有任务判定及样本配对规则继续适用。

原配置报告 17 项、续跑报告 21 项回归通过。独立复核的三项 Python 和四项诊断相关前端定向检查通过。

## 文档同步与边界

同步[配置报告说明](../configuration-reports.md)、[浏览说明](../result-browser.md)、[进度](../progress.md)和 [CHANGELOG](../../CHANGELOG.md)。统计公开分母与缺失覆盖；旧报告没有该字段时界面显示其原有内容。
