# 修改记录 138 固定合成交付检查与源码隔离导出验收

日期：2026 年 11 月 11 日，Asia/Shanghai。类型：功能、配置、测试、文档。插件版本：0.1.2。相关Git提交：尚未提交；Git HEAD仍为 `1717cc997a0a386c64416ff9a95e66751dc2a013`，137批次B也仍在工作区。

## 问题与目标

批次C增加可重复的公开交付检查入口，串联合成演示、原基线比较、目录包实际搬迁、包外fresh报告及只读浏览API。验收需要分别证明已提交源码和当前未提交候选能够独立运行，避免把原工作区的模块、私有资料或依赖安装当作公开源码交付的一部分。本记录先保留入口形成时的定向结果，再补记同日完成的源码导出、完整回归与当前文档整理；摘要网页渲染保留未验证。

## 文件修改

| 文件 | 当前修改 | 原因 |
| --- | --- | --- |
| dsh_eval/delivery_check.py | 新增8阶段检查和独立deliveryCheckFormatVersion=1结果 | 复用公开生成、归档、报告和浏览API，不新增评分器 |
| test/test_delivery_check.py | 新增8项真实集成检查 | 验证原源消失后的搬迁重评、输出冲突、移动边界及HTTP收尾 |
| package.json | 新增check:delivery | 本地公开命令 |
| .github/workflows/deterministic.yml | 配置新增交付检查步骤 | 后续新CI可检查搬迁和浏览API；尚未云端实测 |
| docs/delivery-check.md | 新增命令、八阶段、导出来源与证据范围说明 | 区分检查入口、源码来源证明及网页显示 |
| README、docs/progress.md、docs/capabilities.md、docs/architecture.md、CHANGELOG | 同步当前实现、验证与限制 | 保留B与A证据，不混为本次通过 |
| docs/plans/m3-regression-evaluation.md、docs/plans/m6-reliability-validation.md | 给历史计划增加当前导航说明 | 已完成的双配置矩阵、只读归档不再被旧待办误导；保留原阶段记录 |

## 实现与技术取舍

只使用预先固定的合成行为，工作流6次、基线比较7次合成任务，不调用模型或依赖Harness安装。基线示例原退出码0 / 1 / 2保持；通过检查不是宣称所有候选任务通过。

原始输出leaf先排他创建再resolve。移动前检查解析后的源与目标均在本次新目录内、目标不存在；只改本次生成目录。workflow原源和包都实际rename，确认旧实验路径不可用后才核验包及生成包外新报告。verify的taskEvaluationPerformed=false与后续fresh报告分开，四样本评分 / 诊断 / 原因、源和包文件字节保持。regression-source留在原位，不把它称作已搬迁的独立完整包。

HTTP检查各根只覆盖catalog和指定比较 / 保存报告；深层关联通过ArtifactBrowser API检查，不冒称实际DOM操作。连接和两个服务均有finally收尾。检查结果独立保存，不改原评测 / 实验格式或历史真实轨迹，原始生成内容不自动上传。

源码来源证明放在检查命令之外：命令不执行Git导出或认证版本。已提交HEAD用Git archive导出后在子进程运行该版本已有CLI；公开候选用明确文件清单复制至原仓库之外，再从候选自身运行新npm入口。两者清除子进程的PYTHONPATH、NODE_PATH、NODE_OPTIONS，核对产品模块和ROOT指向各自导出目录，源码及祖先目录没有node_modules；不安装依赖或Harness。控制脚本使用Python标准库，不从当前工作区导入产品模块。文件字节核对不等于文件系统元数据、原子快照或掉电可靠性保证。

## 验证

运行日期：2026年11月11日，Asia/Shanghai。环境：Windows、Python 3.12.0、Node.js v24.14.0。全部为固定合成或离线验证，无新增真实模型调用。

### 入口形成时的定向结果

| 命令或操作 | 实际结果 | 范围 |
| --- | --- | --- |
| python -m dsh_eval.delivery_check --output-dir runs/delivery-check/dev-c-flow-1 | 首个完整CLI退出0 | 13次合成任务、原0 / 1 / 2、128源摘要、52文件包实际搬迁、原源缺失、四样本新报告及4次真实HTTP |
| python -m unittest discover -s test -p test_delivery_check.py -v（允许实际链接环境） | 最终8项 / 28.312秒通过，无跳过 | 正常链路、复制候选源独立CLI、链接 / 冲突 / 边界与HTTP错误收尾 |
| 同一8项首轮沙箱执行 | 6通过、2错误 / 30.399秒，均为实际symlink创建WinError1314 | 未计为通过，没有mock或skip替代实际链接；后续在允许环境完整复验 |
| py_compile、git diff --check | 通过 | 本次新增模块语法与补丁 |

137的664项Python / 164项Node仍属于B当时的回归。上述8项中的候选复制子进程检查也不充当已提交HEAD导出验收；两种来源的独立补验如下。

### 已提交HEAD的干净源码导出

对已核实的 `1717cc997a0a386c64416ff9a95e66751dc2a013` 执行 `git ls-tree -r --name-only` 与 `git archive --format=zip --output <archive.zip> <SHA>`，核对ZIP提交注释、338个成员名和安全路径后解包。导出不含.git、runs、private-notes、node_modules或缓存。ZIP为1,229,457字节，SHA-256为 `ad3b4f79e8037e7fa4ba5403c6fe17904eaf9e441a1032c79a9821690707fcda`；338文件内容清单摘要为 `76e74299936c40a3f0256e75e95e7041a8f9f1e13ff593bd11232e47497f00a8`。

以解包源码为cwd，独立子进程依次运行 `python -m dsh_eval.workflow_demo --generate-only`、`python -m dsh_eval.regression_demo`、`python -m dsh_eval.archive_bundle export`、`python -m dsh_eval.archive_bundle verify`、`python -m dsh_eval --report`，每项指定本次新输出路径，五个CLI均退出0。原源和包实际搬迁、原路径不可用后，52个payload文件加1份manifest通过核验；包外fresh报告四样本均verified / matched / synthetic / passed，汇总、诊断与原因保持，包括一项任务通过但诊断偏离。源、包、独立基线比较输出及338个已列源码文件字节保持。

该版本不含B和C的新模块，模块查找确认delivery_check不存在，因此这份结果仅证明旧已提交版本的既有CLI交付，不证明未提交B/C或新check:delivery。

### 当前公开候选的仓库外隔离导出

从Git跟踪文件和明确列出的六个新增公开文件导出344份源码 / 文档。新增文件是137、138号记录、delivery-check说明、新检查模块及delivery / regression浏览两份测试。拒绝越界、链接和junction成员，排除.git、runs、私人资料、依赖目录及缓存；源码位于原仓库之外的临时目录，输出也在该隔离目录内。

候选全清单SHA-256为 `0e0a12dbd73d646fb1b51d5b371e60f83e8eee6251befcf6f5f1e358609be1d5`，运行代码 / 测试 / 配置清单为 `1849dbacaca732a07f9ce7195dbc8e1fa070812614761cea4826a6fd4f7a3004`。以候选源码为cwd运行 `npm.cmd run check:delivery -- --output-dir <new-isolated-output>`，退出0，用时14.184秒，模块来源及ROOT均属于候选自身。

八阶段完成13次固定合成任务，0 / 1 / 2符合预期；实际移动并复验52个payload文件加1份manifest，原源不可用后在包外fresh重评四样本。汇总、诊断、原因、分组及保存比较字段保持。独立标准库审计再次核对99个工作流源文件、133个比较源文件（含5份产物；其中128份是生成器核对的原输入 / 实验源）及53个包文件，字节摘要一致。两个根共4次实际HTTP请求和深层只读API检查通过，两个服务线程停止、套接字关闭。

344个声明源码文件在隔离运行中保持。该全清单标识导出时的候选快照；随后补记本次文档验收结果改变了部分文档字节，170份运行代码 / 测试 / 配置仍与已验候选匹配。此导出含未提交B/C，不是新的Git提交或已提交干净checkout，也不证明摘要网页DOM显示。

### 当前候选完整回归

| 命令 | 实际结果 | 范围 |
| --- | --- | --- |
| npm.cmd run test:python | 672项 / 458.055秒，OK，无跳过 | 包含B/C新增测试；实际链接、子进程与HTTP环境 |
| npm.cmd test | 164项 / 7.336秒全部通过，无失败、取消或跳过 | Node录制、宿主适配及浏览前端回归 |
| npm.cmd run check | 45个JS文件语法通过 | 当前JavaScript源码 / 测试 |
| python -m compileall -q dsh_eval scripts test | 退出0 | Python模块语法 |
| 文档相对链接 / 锚点及git diff --check | 13份变更文档的738个相对链接通过，补丁检查通过 | 目标属于公开文件集合，无悬空文件或锚点；不检查外部网址状态 |

完整回归与隔离验收后只补记文档，没有改变已验运行代码、测试或配置。结果不继承A的云端CI，也不将合成指标解释为真实模型效果。

## 风险与后续

本批请求的源码隔离导出、完整回归和文档整理已完成离线范围。摘要网页渲染仍未验证；A已有摘要发布步骤与下载Markdown的核对保持原范围，不能升级为网页显示验收。本轮不再进行网页操作。

B/C仍未提交推送，新增CI步骤尚无对应提交的云端结果。输出保存在忽略目录，不上传原始生成内容，CI仍只发布原先五份基线比较文件。此次只搬迁普通工作流实验包，完整基线比较源留在原处；没有扩展regressionComparison归档支持或搬迁后调度执行。默认输出需要新叶目录，失败 / 中断可能保留部分输出。

## 文档同步

README、进度、能力和架构新增交付检查入口、实际范围及来源区分。当前摘要修正续跑结果整合、M3以后能力、072历史十用例双配置两轮矩阵及130只读归档的陈旧待办；072四十项仍为39通过 / 1严格格式失败，不修改旧用例规则或把历史失败转为通过。M3 / M6方案保留原更新时间和阶段结果，仅增加导航说明；既有历史记录和2026年10月25日的阶段判断不覆盖。CHANGELOG链接本记录，命令与限制见[固定合成交付检查](../delivery-check.md)。
