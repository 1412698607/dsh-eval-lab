# M6 固定评测集

10 个版本 2 用例，共用已有的虚拟文件 read / list 工具环境。JSON 声明任务、初始文件、每路径暂时故障次数和必要证据，本身不是执行结果。

| 用例 | 检查目标 |
| --- | --- |
| direct-read | 读取指定文件并提取字段 |
| nested-discovery | 列目录发现嵌套文件，再读取 |
| reference-chain | 沿 README、索引、目标文件三层引用读取 |
| current-over-archive | 按 README 的权威路径读取，避开过时字段 |
| missing-file | 实际 NOT_FOUND 后报告缺失 |
| empty-file | 区分成功读取空文件与文件不存在 |
| unicode-path | 中文路径与中文字段 |
| retry-once | 同路径一次暂时失败后成功读取 |
| independent-retries | 两个路径分别失败一次，分别恢复并组合答案 |
| stale-then-retry | 旧路径缺失、列表发现当前文件、暂时失败后恢复 |

每项要求关联到真实工具调用的结果、精确最终答案和 completed 结束。目录发现约束成功列表包含目标，允许根目录或相关子目录。六个涉及发现、引用或重试的用例声明 after，要求先行结果返回后才发起后继调用；independent-retries 只约束每条路径自身，允许两路径交错。empty-file 通过 result.textEquals="" 验证工具返回文本为空，空白也不能通过。字段及失败分类见 [评测格式](../../../docs/evaluation-format.md)。断言仍允许无关额外调用及之后的完整合法链，没有指定次数或安全策略检查。

无模型验收：

```powershell
python -m unittest discover -s test -p test_core_suite.py -v
```

该检查从独立参考动作调用真实 Python 状态化环境，经原 Node 记录器和 fresh inspect 验证 10 个正例、10 个无工具证据反例、10 个错误答案反例；另检查逐项工具证据必要性、列表替代路径、故障状态重置、步骤反序、提前发出后继调用、非空 / 空白返回，以及独立路径交错和补做合法链。参考轨迹标记 synthetic，不经过模型或 Harness 工具桥接，不当作真实模型成绩。更细的格式与乱序完成边界可运行 `python -m unittest discover -s test -p test_assertion_constraints.py -v`。

2026 年 10 月 24 日的首次 10 个真实任务使用记录 027 的原冻结断言。记录 028 只加强当前七个用例的断言，未改变任务、环境或配置，也未重跑模型；新旧断言对已有录制的离线检查分别保存，历史快照不改写。详见 [固定评测集验收](../../../docs/core-evaluation.md)。

显式运行下面命令会调用真实模型：

```powershell
python -m dsh_eval --experiment fixtures/evaluation/core/core.experiment.json --run
```

清单选择 deepseek-official / deepseek-flash、一个配置、每项一次，共 10 次计划任务，单任务墙钟预算 120 秒。任务可能包含多次请求、工具调用和提供商内部重试；任务数及超时均不是 token / 费用硬上限。原有 runner 在调用模型前冻结全部输入，每项使用新环境 / home / 会话；取消或无法确认清理时可提前停止，剩余项保留 skipped。完整运行与离线复验说明见 [固定评测集验收](../../../docs/core-evaluation.md)。
