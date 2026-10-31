# 修改记录 062 Windows 续跑领取前输出路径保护

日期：2026 年 10 月 29 日，Asia/Shanghai。类型：修复 / 测试 / 文档。插件版本：`0.1.2`。相关 Git 提交：尚未提交；已核实起始 HEAD 为 `35cf77078beef07b764febd596eee1d7f7610bda`。061 的验收补记及三份文档更新在本轮开始时已存在，保持保留。

## 问题与目标

实验续跑的 continuations / batches / cases 与四层 UUID 使 Windows 普通宿主目录过深。061 的真实 CLI 离线准备已出现 mkdtemp ENOENT，但批次核心会先写永久领取记录，再进入宿主准备，导致已知路径错误也占用源的单次续跑资格。

本批选择在领取前明确拒绝当前 Windows 普通安装目录无法支持的输出根。批次、首轮实验和连续实验入口均在新身份 / 输出 / 领取之前检查，并保留旧源，使调用者能选用更短输出根再次执行。没有接入只验证过离线准备的扩展路径原型，也不重置已存在的领取。

## 文件修改

| 文件 | 修改前 | 修改后 | 原因 |
| --- | --- | --- | --- |
| dsh_eval/resume.py | 批次核心创建身份、领取后才发现宿主准备路径错误 | 共用 Windows 输出根检查，在 UUID / 领取前计算预计安装目录 | 阻断已知路径错误，保留续跑资格 |
| dsh_eval/experiment_resume.py、experiment_resume_chain.py | 外层先创建结果目录后才进入批次核心 | 实验完整四层布局在外层 UUID / 输出之前检查 | 首轮与连续入口均不留下新的误导性 running 结果 |
| test/test_resume_output_paths.py | 无领取前路径回归 | 六项检查覆盖边界、UTF-16、其他平台、三个执行入口及真实 CLI 拒绝 | 确认拒绝没有身份分配、输出或源文件变更，源仍可预检 |
| test/test_batch_resume.py、test/test_experiment_resume.py | 合成适配器已替换宿主准备，仍运行在较长临时根 | 合成夹具同时替换宿主目录限制；新增路径用例单独恢复真实检查 | 合成报告 / 锁等回归不受未安装的 Harness 约束影响，路径行为独立验证 |
| README、架构、两份续跑说明、进度、M6 方案、CHANGELOG、本记录 | 未说明输出根会在执行时额外拒绝 | 同步拒绝时序、限制、重选输出根与预检边界 | 区分当前保护与未来长路径支持 |

## 实现与技术取舍

检查在已有源锁内、重新核对证据与预期摘要之后运行。用固定 UUID 占位计算最终目录，不调用 uuid4、不创建目录、锁文件或领取。批次根包含 resumeId / batches / batchId / cases / caseRunId；实验根增加外层实验续跑与 continuations，合计四层 UUID。末尾追加 home/profiles/headless/.plugin-manager/logs/operation-XXXXXX，覆盖 mkdtemp 的六字符随机后缀。

Windows 按绝对路径的 UTF-16 code units 计量，长度达到 248 时 ValueError 拒绝，要求更短 --runs-root；批次核心再次复核。其他平台不套用限制。CLI 仍用既有版本 1 错误结果、outcome=unevaluable、error 字符串和退出 2；计划和正常结果格式、指纹及单次领取协议不变。预检没有输出根参数，所以只表示源允许续跑，不能证明未来输出路径可用。

采用保守目录保护，而不把扩展路径准备原型直接接入运行，是因为该原型尚未完成启动、证据路径和报告关联验证。当前保护只排除已知普通目录长度问题，不保证权限、安装、模型或全部 Windows 路径行为，也不释放实际运行失败后的领取。

## 验证

环境：Windows、Python `3.12.0`、Node.js `v24.14.0`。本轮没有模型调用。新增入口回归使用原合成证据、真实 Node inspect / 内核锁及 Python CLI；不是模型端到端续跑。

| 命令或操作 | 结果 | 证明的范围 |
| --- | --- | --- |
| `python -m unittest discover -s test -p test_resume_output_paths.py -v`，初次 | 六项中五通过 / 一错误，CLI 测试误取只属于预检的 valid 字段 | 修正测试为既有执行错误的 outcome / error 字符串，产品错误格式未改 |
| 同命令，目录边界细化前 | 六项 / 5.974 秒，OK | 三入口拒绝、无领取 / 输出、源摘要不变和真实 CLI；当时尚未细化目录上限 |
| 真实 Node `fs.promises.mkdtemp`，预置不同长度的普通路径前缀 | 最终目录 247 单元成功；248 / 249 / 250 / 258 / 259 为 ENAMETOOLONG；260 为 ENOENT | 不能只按 260 文件路径上限判断；最终保护采用目录上限 248（不含） |
| 同新增测试命令，最终 247 单元上限 | 六项 / 6.061 秒，OK | 247 接受、248 拒绝；ASCII 换为非 BMP 字符增加一个 UTF-16 单元也拒绝 |
| `python -m unittest discover -s test -p test_experiment_resume.py` | 26 项 / 32.573 秒，OK | 原实验预检 / 执行兼容 |
| `npm.cmd run test:python`，边界细化前已启动的一轮 | 347 项 / 227.997 秒，OK | 中间版本完整回归；不代替最终收紧后的完整结果 |
| `npm.cmd run test:python`，最终目录上限版本 | 347 项 / 224.871 秒，OK、无跳过 | 最终代码的完整无模型回归，包含六项新增路径保护 |
| `npm.cmd run check`、`npm.cmd test`，允许真实子进程的环境 | 43 个 JS 语法、91 Node 通过，无失败 / 跳过 | 原录制、宿主生命周期和浏览兼容 |
| `python -m compileall -q dsh_eval scripts test` | 退出 0 | 最终 Python 语法 |
| 修改 / 新增 Markdown 链接及补丁检查 | 九份文档、364 个本地链接存在且未被忽略，git diff --check 通过 | 公开导航与补丁空白检查 |

真实目录边界检查在新的忽略目录中建立前缀，仅运行 Node mkdtemp，不启动 Harness 或模型。所用最终目录长度包含随机生成的六字符后缀；UTF-16 计数由对应 Python 断言与 Node 返回的 length 交叉核对。新增三个入口回归在预期拒绝时禁止 uuid4，比较全部原文件 SHA-256，随后再次预检仍 eligible / canResume；CLI 回归保留 stderr 为空和退出 2 的检查。

## 风险与后续

当前 Windows 默认根和较深 checkout 下的相对根可能直接被拒绝，需要足够短的绝对输出根；这不是通用长路径兼容修复。已有领取仍保持单次保护，未知执行 / 清理及 stop 失败仍阻断。源可预检不表示可执行输出路径、宿主安装、凭据或远端模型均可用。

061 的嵌套路径准备失败和扩展路径原型结果保持原样。未来若接入扩展路径，需要单独验证完整宿主启动 / 执行 / 证据与报告关联，再调整当前保守检查。任务边界停止入口和六项真实续跑仍待验收；本轮未新增真实样本、提交 / 推送或新云端 CI。

## 文档同步

更新 README、架构、批次 / 实验续跑说明、进度、M6 方案和 CHANGELOG；061 及更早修改记录保留历史快照。
