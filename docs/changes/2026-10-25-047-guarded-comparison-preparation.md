# 修改记录 047 双配置八任务无模型准备

日期：2026 年 10 月 25 日，Asia/Shanghai。类型：配置 / 测试 / 文档。插件版本：0.1.2。相关 Git 提交：尚未提交；本批起始提交为已核实的 1ebd29402dcbbb9be29d4caa61977d45b898e398。具体交付结果以 Git / Actions 对应提交及交付记录为准。

## 问题与目标

原第二批计划是两用例 × 两配置 × 两轮的小规模真实比较。本批不追加真实模型，第二配置尚未确定，因此先交付可填写模板和八任务合成链路回归，验证下一步需要的计划约束、配对与失败覆盖；不把准备工作标为真实比较已验收。

## 文件修改

| 文件 | 修改前 | 修改后 | 原因 |
| --- | --- | --- | --- |
| fixtures/evaluation/core/guarded-comparison.experiment.template.json | 只有单配置四任务清单 | 两用例 / 两配置 / 两轮，stop 策略；candidate provider / model 暂为 null | 明确未选择状态，避免默认使用未经确认的真实模型 |
| test/test_guarded_comparison.py | 既有通用报告与单配置回归 | 五项面向该八任务范围的无模型回归 | 把多用例、重复、指纹和配对排除连成完整流程 |
| docs/guarded-comparison.md | 无独立准备入口 | 模板填写、无模型验证、以后预览和报告验收说明 | 可在不依赖私人材料时接续 |
| README / CHANGELOG / progress / experiments / configuration-reports / M3、M6 方案 | 真实第二配置仍待范围 | 增加本批准备状态与链接，保留真实范围边界 | 文档与实际实现一致 |

## 实现与技术取舍

复用既有版本 1 实验与报告、版本 2 用例、顺序 batch / runner；不修改生产执行代码、校验器、配对算法或数据格式。null 只是模板待填写值，现有 nonempty-string 校验在生成 UUID / 输出目录和启动子进程前拒绝。第二配置需显式填写，复用现有字段校验，无需增加模板状态协议或扩大运行接口。

测试在临时目录复制两个既有用例，填入 synthetic / baseline 和 synthetic / candidate；只替换宿主准备和既有 Node 合成适配器。真实 Python 桥接、录制器、inspect、任务隔离、快照指纹和报告继续执行，保存来源明确为 synthetic。两用例按轮次分别形成两对，不跨用例合并。人为指定的 elapsedSeconds 只验证差值计算，不是测量性能。

三个负例在独立合成副本修改候选的路由声明、制造来源声明冲突或截断录制，均只排除 direct-read 第一轮；retry-once 两轮配对不受影响，计划分母仍为 8，报告不改写输入。另首项故意答案断言失败，保留 attempted=1 / skipped=7，四组 planned 均为 2、比较无可用配对。来源负例故意声明 live 后被拒绝，不属于真实模型证据。

## 验证

本机 Windows / Python 3.12.0 / Node v24.14.0；2026 年 10 月 25 日执行，全部无模型。

| 命令或操作 | 结果 | 证明的范围 |
| --- | --- | --- |
| python -m unittest discover -s test -p test_guarded_comparison.py -v | 5 项，5.874 秒，OK | 模板拒绝、八任务顺序 / cap / 指纹、真实本地合成链路、异常排除、停止分母 |
| npm.cmd run test:python（获准子进程环境） | 248 项，60.778 秒，OK | 新增五项与完整既有 Python 回归；不把 mock 代替真实子进程检查 |
| python -m compileall -q dsh_eval scripts test | 退出 0 | Python 编译检查 |
| 真实 CLI：空模板 --plan / --run | 均退出 2，配置空值错误；stderr 空 | 未建运行输出，未启动模型 |
| 真实 CLI：填合成配置后 --plan --max-samples 8 | 退出 0，counts=2 / 2 / 8，modelCalled=false | 八任务静态计划与摘要 |
| 真实 CLI：上限 7 / 第二配置变更后带旧指纹执行 | 均退出 2；stderr 空；目标目录不存在 | 数量 / 指纹约束先于执行 |

证据在忽略的本机 runs 内排他新建，历史文件与失败不覆盖。JavaScript 和既有生产 Python 未改，本地未重复 Node 套件；推送后按本次实际完整 SHA 单独核对最新 Windows CI 的 run / job / 各步骤和实际日志，不沿用 046 绿灯。

提交前检查通过：72 份公开 Markdown / 506 个相对文件链接、11 份预期公开修改、794 份受保护旧文件摘要、忽略规则与空白。生产代码、协议、旧用例和历史修改记录不变，runs / private-notes 无跟踪。

## 风险与后续

第二真实模型、provider 可用性和实际八任务验收仍待选择与执行。当前只有合成双配置验证；既有单配置四任务和全部真实历史不变。计划为八任务不保证八项都会被尝试，也不约束模型调用数、token 或费用。使用短输出根规避已知宿主深目录限制；未修复全局长路径行为。没有并发、续跑、统计推断或模型优胜结论。

## 文档同步

同步 README、CHANGELOG、进度、实验与报告说明、M3 / M6 方案、新比较准备说明。
