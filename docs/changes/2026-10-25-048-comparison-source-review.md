# 修改记录 048 双配置准备复审与合成来源修正

日期：2026 年 10 月 25 日，Asia/Shanghai。类型：修复 / 测试 / 文档。插件版本：0.1.2。相关 Git 提交：尚未提交；已核实本批起始提交 815a9443ac884b9ec6e529c9a84d2948c7437140 包含 047。本批不追加真实模型任务，第二套模型保持未配置。

## 问题与目标

复审 047 的 11 份修改，发现比较测试辅助函数只事后修改 evidence、批次条目和实验样本的 source，遗漏原始 evaluation.json、实验及分组摘要。合成成功实验中，八份证据为 synthetic，八份原始评测仍为 live，实验 sourceCounts 为 live=8、四组各 live=2；报告重新评测后虽然得到 synthetic，savedSummary 仍显示 live。批次本身没有摘要字段，其条目原已标为 synthetic。

这是新测试数据的来源标记不一致，不是本次或 047 实际调用了模型。原始 047 记录、证据和成功 CI 保留；当前说明更正“所有归档来源已统一”的范围，新增成功 / 失败停止两类归档一致性回归。

另原模板测试只断言 candidate.model 为 null；setUp 又会覆盖两个 provider / model，无法锁定原 baseline 配置、candidate.provider 的未选择状态。补齐原始配置完整断言和部分填写拒绝覆盖，保留模板原字节，第二套模型保持未配置。

## 文件修改

| 文件 | 修改前 | 修改后 | 原因 |
| --- | --- | --- | --- |
| test/test_guarded_comparison.py | 只改部分来源字段，单个空值断言 | 补齐原始评测和实验 / 分组计数，新增一项成功 / 停止一致性测试；原测试增加完整配置与部分填写断言 | 保证合成来源、跳过未知和未选择配置的声明一致 |
| docs/guarded-comparison.md | 五项测试，笼统说明归档来源 | 六项测试、具体标记时机和层次、跳过项未知，并链接本复审 | 文档与实际测试一致 |
| CHANGELOG / docs/progress.md | 047 为当前准备状态 | 增加复审发现、修正和新验证；保留旧结果 | 区分历史通过与本次修复 |

## 实现与技术取舍

仍先通过既有 runner 和 Node 合成适配器运行测试，原路由 / 执行检查不变；结束后仅在本测试创建的临时结果中统一来源。已尝试项的 evidence / evaluation、批次条目和实验样本改为 synthetic，再按实际样本重新统计实验和四组的 sourceCounts。跳过项 source 仍为 null，计数仍为 unknown，不补成 synthetic。

没有在执行前更改 evidence 来源，避免跳过 evaluate 中以 live 为条件的原路由校验；也不增加生产 runner 的来源参数或修改格式。只调整来源及其计数，不重新推导已验证的执行、录制、断言、指标和身份。新回归分别核对正常八任务与首项失败后 1 attempted / 7 skipped 的归档、savedSummary 与新报告来源，并确认报告不改写输入。

原始模板完整锁定 baseline 既有配置和 candidate 两个 null；空、只填 provider、只填 model 三种形态的 plan / run 均在 UUID、批次和子进程前拒绝。合成标识只写入测试临时副本，不是实际第二配置选择。

## 验证

2026 年 10 月 25 日，Windows / Python 3.12.0 / Node v24.14.0，全部无模型。

| 命令或操作 | 实际结果 | 证明的范围 |
| --- | --- | --- |
| 新一致性回归修复前：python -m unittest discover -s test -p test_guarded_comparison.py -k archived -v | 1 项 / 1.607 秒，FAILED，两个子场景均 live != synthetic | 成功与停止都能复现原始评测来源遗漏 |
| 修复前独立来源盘点 | evaluation live=8、evidence synthetic=8、实验 live=8、四组各 live=2，批次条目 synthetic=8 | 明确遗漏位置，不虚构批次摘要 |
| python -m unittest discover -s test -p test_guarded_comparison.py -v | 6 项 / 8.631 秒，OK | 新一致性回归、模板加固及原八任务计划 / 配对 / 异常 / 停止回归 |
| npm.cmd run test:python（获准子进程环境） | 249 项 / 61.446 秒，OK | 完整无模型 Python 回归，保留真实本地子进程检查 |
| python -m compileall -q dsh_eval scripts test | 退出 0 | Python 编译检查 |
| 真实 CLI：空 / 仅 provider / 仅 model × plan / run | 六次均退出 2、stderr 空、未建运行目录 | 部分未选择配置也在执行前拒绝 |

JavaScript、生产 Python 和模板均未改，本地不重复未变的 Node 套件；推送后按本次实际新 SHA 独立核对 Windows CI 的 run、job、所有步骤及实际日志，不继承 047 的绿灯。复现和验证输出在忽略的本机 runs 中排他新建，不覆盖旧文件。

提交前范围 / 保护检查通过：73 份公开 Markdown、509 个相对文件链接、5 份预期公开修改、833 份旧文件摘要；runs / private-notes 无跟踪，模板与历史证据不变。

## 风险与后续

修复仅针对 047 的合成比较测试与当前说明，不更改历史日志或真实任务结论。生产行为、版本化协议、用例和模板不变；第二配置保持待填写，真实双配置比较未执行。手工 elapsed 差值仍只验证计算，不能当作速度或费用改善；计划一致、录制完整和任务成功继续分别判断。

## 文档同步
同步比较说明、CHANGELOG 和进度。运行方式、架构和格式未变，因此不改 README / 架构。保留 047 历史记录，新提交的 CI 按实际 SHA 独立核对。
