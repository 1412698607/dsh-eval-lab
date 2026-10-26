# 修改记录 043 计划输入快照与离线指纹复核

日期：2026 年 10 月 25 日，Asia/Shanghai。类型：功能 / 测试 / 文档。插件版本：0.1.2。相关 Git 提交：本批尚未提交，HEAD 仍为 `b309aa50b7cf8c9f750b2ff641a653313398e575`，分支 `20261024/feat/m6-4-web-lifecycle`。开始时 041 / 042 的 14 份未提交文件全部保留。本批没有真实模型、提交 / 推送或新云端验收。

## 问题与目标

042 可在执行前比对输入指纹，但报告没有复核保存的计划摘要。现有 experiment.json 会把原 casePath 重写为冻结路径，不能直接重建原指纹；依赖 sourceManifest 又会引入原文件变动 / 丢失和目录搬迁问题。本批在无模型条件下补齐原始载荷保存与离线报告核对。

新实验保存完整版本 1 指纹载荷，报告仅从实验目录读取，核对冻结输入后重新计算摘要。旧实验没有快照时仍可报告，计划状态明确 unverified；声明过的快照缺失或矛盾则在 inspect 和输出之前拒绝。计划一致不替代任务成功判断。

## 文件修改

| 文件 | 修改前 | 修改后 | 原因 |
| --- | --- | --- | --- |
| dsh_eval/experiment.py | 只保存摘要，冻结清单改写原路径 | _plan_input 共用载荷定义，新实验保存 plan-input.json，结果新增 planInputPath | 保留可离线重算的原始声明且不改变原摘要算法 |
| dsh_eval/report.py | 报告不使用计划指纹元信息 | 先核对快照 / 冻结输入 / 摘要，再进行原样本复验；JSON / Markdown 增加 planVerification | 报告明确已复核范围及旧记录局限 |
| test/test_report_plan_snapshot.py | 无快照回归 | 新增 8 项无模型测试 | 新旧兼容、搬迁、冲突、安全路径、元信息、重算摘要和坏录制边界 |
| README、CHANGELOG、progress、architecture、experiments、configuration-reports、M3 / M6 方案、本记录 | 042 当前状态与报告旧边界 | 新文件 / 字段、核对顺序、兼容、验收和限制 | 文档与实现一致 |

本批未改 JavaScript、CLI 参数、runner、formats、batch、fixture、browser、main.py、既有测试或 001 至 042 历史记录。041 / 042 累计源码改动继续保留。

## 实现与技术取舍

_plan_input 返回原版本 1 载荷（version、完整已校验 manifest、按条目顺序原始 cases、maxSamples、order），_plan_fingerprint 从同一函数取载荷。摘要版本、序列化与字节算法不变。run 在原预期摘要检查通过并创建本次目录后，以原排他保存函数写 plan-input.json，随后冻结 / 展开原任务；结果以 planInputPath 声明相对路径。--plan 仍只输出 JSON，不保存文件。快照写入失败不启动任务，但可留下未完成目录，没有原子目录发布或 fsync 保证。

report 先读取 / 核对原实验与批次计划，再在逐样本 evaluate / inspect 和输出目录创建前检查计划快照。严格校验实际指纹版本 / 摘要、可选预期摘要，二者声明不一致拒绝；新快照须符合精确字段 / 版本、固定顺序、合法数量上限和完整用例数量。原始 manifest 只允许 casePath 被冻结清单改写，其他字段、条目身份和顺序必须一致；每个原始 case 与对应 inputs 的完整冻结内容必须相同，包括预算、环境故障、原 configRef、断言与 recorder 原声明。最后用原算法重算并比对实际摘要，任务上限也必须与结果一致。只改快照并重算摘要，仍无法掩盖与冻结输入的差异。

快照路径复用现有相对 POSIX / 真实目录包含关系守卫，拒绝绝对路径、越界和目录链接逃逸。报告不读取 sourceManifest 或原用例路径；复制整个实验目录后仍可复核。原始路径保留在载荷内参与哈希，但不作为离线文件读取位置。

新报告仍为 comparisonReportFormatVersion=1，新增 planVerification={status,fingerprint,expectedPlanSha256,inputPath,reason}。verified 表示保存的计划载荷、冻结输入和摘要一致；未声明 planInputPath 的旧结果（含只有 042 指纹的结果）保持 unverified / 明确原因，不补造旧快照，原样本继续复验。已声明快照但文件丢失、未知格式、非法路径或内容冲突时整份报告输入错误，CLI 返回 2，不生成新报告目录；Markdown 也显式呈现计划状态。录制和任务判断仍走原流程，计划 verified 时坏日志仍 unevaluable。

## 验证

环境：Windows、Python 3.12.0、Node v24.14.0。全部为静态预览、合成事件 / 真实 Node 适配器子进程及离线 CLI；没有调用真实模型或安装新宿主。完整回归因既有进程清理 / fork 要求直接在获准环境运行，不制造新的受限失败。JavaScript 未改，不重复旧 85 Node / 41 JS 验证。

| 命令或操作 | 实际结果 | 证明的范围 |
| --- | --- | --- |
| `python -m unittest discover -s test -p test_report_plan_snapshot.py -v`，实现前 | 8 项 / 3.570 秒，8 failures / 8 errors | 原实现不保存快照 / 不核对或显示计划状态；真实合成适配器未调用模型 |
| `python -m unittest discover -s test -p 'test_report*.py' -v`，实现后 | 25 项 / 22.505 秒，OK，包含新增 8 项 | 元信息和载荷 / 版本 / 上限 / 顺序 / 完整原始输入、目录搬迁且删除原始来源、新旧兼容、缺失 / 不安全路径、重算摘要仍绑定冻结输入、坏录制不误判任务通过 |
| `npm.cmd run test:python`，获准环境 | 完整 238 项 / 50.878 秒，OK | 现有预览 / 上限 / 指纹及所有 Python 回归，含真实子进程、目录别名和本机服务 |
| `python -m compileall -q dsh_eval scripts test` | 退出码 0 | Python 编译检查 |
| 现有十用例 CLI --plan --max-samples 10，与保存的 042 预览对照 | 退出 0、stderr 空，摘要完全相同 | 提取载荷和新增保存没有改变原指纹；没有执行十用例 |
| 两个新 Node 合成样本，原 runner / batch / experiment 预览 + 预期摘要检查 | completed / complete / passed；保存新快照 | 复用真实录制器和 Python 桥接，仅把宿主准备 / 适配器换为既有无模型 fixture；不是 Harness / 模型验收 |
| 对新合成实验实际执行 Python CLI --report | 返回 0，planVerification=verified、passed=2 | 保存载荷、冻结输入和摘要相符；JSON / Markdown 已生成，原实验 33 文件摘要不变 |
| 对模拟 042 无快照格式的独立副本执行 --report | 返回 0，planVerification=unverified、passed=2 | 旧输入兼容且保留无法复核范围，不伪造快照或改变任务结论 |
| 对快照内容冲突的独立副本执行 --report | 返回 2、stderr 空，Plan input/frozen case mismatch，无新报告根目录 | 全局计划矛盾先于 inspect / 报告输出拒绝，原实验不改 |

证据保存至新忽略目录：baseline.json / baseline-files、419 份受保护旧文件摘要、新测试失败与通过 / 完整回归日志、CLI 预览、合成计划和保存实验、两个反例副本、三次报告 stdout / stderr 与 cli-checks.json。原 041 / 042 证据不覆盖；33 份新合成原实验文件在报告前后摘要一致。交付核对通过：66 份公开 Markdown / 459 个相对文件链接、含 041 / 042 的 18 份预期未提交文件、419 份旧保护摘要、HEAD / 忽略规则和空白；git diff --check 通过，仅有 LF / CRLF 转换提示，runs / private-notes 无跟踪。

## 风险与后续

本批本地开发 / 验证完成，041 至 043 均未提交 / 推送或进行新云端验收。保存完整载荷会再次保存原始任务 / 环境内容并占用磁盘与内存，继续留在忽略的 runs 中，不作为公开夹具；没有新增大小上限、事务快照或签名。

全部快照 / 冻结输入 / 摘要可同时改写，删除元信息也可能伪装成旧格式，本工具不能认证历史来源或证明当时真正执行了预期摘要检查。计划状态独立于实际模型路由、录制、断言和费用事实。真实双配置 / 重复仍待第二配置、次数与任务预算，本批不追加十用例或 60 任务示例。

## 文档同步

同步 README、CHANGELOG、进度、架构、实验与配置报告说明、M3 / M6 方案。历史 001 至 042 不改，不新增公开原始日志或私人材料链接。
