# 修改记录 042 计划指纹与执行前一致性检查

日期：2026 年 10 月 25 日，Asia/Shanghai。类型：功能 / 测试 / 文档。插件版本：0.1.2。相关 Git 提交：本批尚未提交，HEAD 仍为 `b309aa50b7cf8c9f750b2ff641a653313398e575`，分支 `20261024/feat/m6-4-web-lifecycle`。开始时 041 的 12 份未提交文件全部存在，本批保留并在其上继续，不提交 / 推送或运行模型。

## 问题与目标

040 提供预览，041 可以限制任务数，但两次调用会重新读取源文件。同样数量的任务也可能更换问题、环境、断言或模型配置；只检查数量无法确认实际执行与此前查看的输入一致。本批增加计划指纹与执行前一致性检查。

预览提供版本化 SHA-256 指纹，实际 --run 可显式携带预期摘要。重新加载 / 校验输入后，比对摘要，不一致就在生成 UUID、创建目录和展开任务前拒绝。匹配后冻结同一组已读数据，继续原运行链路。参数可选，保留旧运行行为，本批只做无模型回归。

## 文件修改

| 文件 | 修改前 | 修改后 | 原因 |
| --- | --- | --- | --- |
| dsh_eval/experiment.py | 预览与运行没有输入摘要关联 | 共用 _plan_fingerprint；run 增加仅关键字 expected_plan_sha256，生成身份前检查；新计划 / 结果保存实际摘要，结果另存预期值 | 绑定此次已加载的计划输入与显式预期 |
| dsh_eval/__main__.py | 只有预览和数量上限 | 新增 --expected-plan-sha256，仅用于实验 --run | 不在查看计划或其他模式中静默接受执行检查参数 |
| test/test_experiment_fingerprint.py | 无指纹测试 | 新增 11 项无模型回归 | 覆盖确定性、变化、格式 / 迁移、错误边界、CLI 和副作用顺序 |
| test/test_experiment.py | 041 四样本只检查数量上限 | 四样本携带匹配的大写摘要执行，检查规范化 / 保存；源文件修改测试携带摘要验证冻结数据一致 | 用真实 Node 合成适配器验证正常执行及既有默认兼容 |
| README、CHANGELOG、progress、architecture、experiments、M3 / M6 方案、本记录 | 041 当前入口和边界 | 新参数、指纹载荷、用法、兼容及实际验证 | 文档和实现一致 |

041 的 test/test_experiment_limits.py 和原修改记录保持原内容；本批不修改 JavaScript、录制器、inspect、runner、formats、fixture、report、browser 或 main.py。

## 实现与技术取舍

指纹版本 1 载荷为 version=1、完整已校验 manifest、按 cases 条目顺序加载的原始 cases 数组、maxSamples 和 order。使用 Python json.dumps（ensure_ascii=False、sort_keys=True、separators=(",", ":")、allow_nan=False）生成紧凑排序键 JSON，再按 UTF-8 编码计算 SHA-256。返回 planFingerprint={version:1,sha256:<小写摘要>}；完整载荷与用户命令见 [实验说明](../experiments.md#计划指纹与执行前一致性检查)。

覆盖清单名称、失败策略、条目 / 配置身份及顺序、相对 casePath、重复次数、全部原始用例内容（包含会被实验 configRef 覆盖的原 configRef）以及本次任务上限。保留 recorder 省略 / 空 / 部分 / 显式默认的差别；预览带上限后，运行遗漏或改上限也会不匹配。文件空白、对象键顺序、Unicode 转义写法和绝对来源目录不参与；搬迁时保持相对清单路径和内容可得同一摘要。相对 casePath 改写即改变摘要，因此重跑已改写路径的冻结清单应重新预览。

run_experiment 保留原四个位置参数和 041 的 max_samples，仅增加可选关键字 expected_plan_sha256=None。预期值必须严格为 64 位十六进制，可大写，规范后再比较；非法值先于文件读取拒绝。随后执行原数量 / 全输入预检，计算本次摘要并比较，匹配后才生成运行身份、创建目录、冻结已读数据、展开和调用原 batch。不会在摘要检查之后重新读取源用例。传入预期摘要不能跳过原输入校验或上限检查。

--expected-plan-sha256 仅接受实验 --run，错误模式 / 缺参数由 argparse stderr / 2 处理。执行模式的非法摘要或不匹配沿用实验输入错误 JSON（outcome=unevaluable、error）/ 2，没有实际结果目录、执行身份或模型调用。错误描述包含预期和实际摘要；原任务 0 / 1 / 2 不变。新实验结果保存 planFingerprint 和 expectedPlanSha256（未传为 null），原输入 / 结果版本仍为 1，旧结果无需这些新元信息字段。未修改离线报告算法，也不把计划指纹与报告 taskFingerprint 混用。

## 验证

环境：Windows、Python 3.12.0、Node v24.14.0。本批没有真实模型 / Harness / Web 任务，没有提交、推送或新云端。JavaScript 未改，不重跑或将旧 85 Node / 41 JS 检查记作本轮结果。已知既有完整套件在受限环境无法完成真实进程树终止 / fork，依据 041 的实际失败，本批完整回归直接在获准环境执行，没有伪造新的受限失败。

| 命令或操作 | 实际结果 | 证明的范围 |
| --- | --- | --- |
| `python -m unittest discover -s test -p test_experiment_fingerprint.py -v`，实现前 | 首批 9 项 / 0.094 秒、18 errors | 原 API / CLI 无指纹和检查参数；之后追加非法 CLI 摘要及输入校验不可跳过两项回归 |
| 同命令，实现后 | 最终 11 项 / 0.243 秒，OK | 稳定摘要、JSON 表示 / 整体搬迁、清单 / 后续用例 / 上限 / 原录制声明变化、非法摘要 / 模式、只读 / 无运行副作用及真实 Python CLI |
| `python -m unittest discover -s test -p 'test_experiment*.py' -v` | 最终 37 项 / 3.838 秒，OK；较早 35 项 / 4.418 秒保留 | 原实验 / 预览 / 数量上限与新摘要；真实 Node 合成适配器四样本匹配执行、大小写规范、结果留痕、默认不继承和冻结输入不受后续原文件变化影响 |
| `npm.cmd run test:python`，获准环境 | 完整 230 项 / 48.553 秒，OK | 当前全量 Python，包含真实子进程 / 目录别名 / 本机浏览等既有回归，没有模型调用 |
| `python -m compileall -q dsh_eval scripts test` | 退出码 0 | Python 编译检查 |
| 现有十用例 CLI `--plan --max-samples 10`，再按公开载荷独立计算 SHA-256 | 退出 0、stderr 空，valid=true / modelCalled=false、counts=10 / 1 / 10，指纹与独立计算一致 | 实际 stdout 新字段和文档载荷一致，没有运行任务 |
| 同清单 `--run --max-samples 10 --expected-plan-sha256 <错误摘要>`，指定新 --runs-root | 返回 2、stderr 空，明确 fingerprint mismatch / 实际摘要，输出根不存在 | 在真实执行入口启动前拒绝；未试跑匹配摘要下的真实模型 |
| 同执行入口传 bad-hash；--plan 传合法预期摘要 | 前者实验错误 JSON / 2、stderr 空；后者 argparse stderr / 2、stdout 空 | 摘要格式与模式限制，没有运行目录或模型调用 |

证据根在新忽略目录保存：开始时冻结 Git 状态、041 累计 diff、拟修改文件副本，以及 387 份旧代码 / 记录 / 原始证据 / 041 检查材料摘要；各轮测试和 CLI 输出新建保存，禁止覆盖历史。交付核对通过：65 份公开 Markdown / 448 个相对文件链接、包含 041 的 14 份预期未提交文件、387 份旧文件摘要、HEAD / 忽略规则和空白。git diff --check 通过，仅有 LF / CRLF 转换提示；runs / private-notes 无跟踪，041 原记录 / 测试及旧证据摘要均保持。

## 风险与后续

本批实现和本地验收完成，041 / 042 均未提交 / 推送，未验收新云端。指纹与预期参数都可由调用方替换，SHA-256 不是签名或来源认证；运行多文件读取没有事务锁，不保证所有文件来自同一瞬间。计算包含完整原始输入，新增序列化与 UTF-8 缓冲，没有新增文件字节 / 内存硬上限。

指纹不包含绝对输出目录、宿主模块、服务 / 凭据、代码版本或运行控制（--host-modules / --cancel-after-stream 等），也不证明实际路由、宿主可用、任务通过或费用受限。保持任务数与模型调用数分开。真实双配置 / 重复比较仍待第二套配置、重复次数和实际任务预算，不自动执行十用例或 60 任务示例。

## 文档同步

同步 README、CHANGELOG、进度、架构、实验说明、M3 / M6 方案。保留 001 至 041 历史记录及所有原始证据，不新增公开私人材料 / 运行日志链接。
