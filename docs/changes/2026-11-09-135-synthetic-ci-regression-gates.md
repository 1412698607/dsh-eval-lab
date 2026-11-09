# 修改记录 135 无模型CI回归门禁示例

日期：2026 年 11 月 9 日，Asia/Shanghai。类型：功能、配置、测试、文档。插件版本：0.1.2。相关Git提交：尚未提交；接续基线为已核实的 `8afe49056d6b055e7db04f5643138d41dc7fe8ac`。

## 问题与目标

原`--compare-baseline`已支持严格的独立实验复验、配对及0 / 1 / 2退出码，但尚无可直接重建的CI示例与合成产物。新增批次A，使维护者能从公开用例生成输入，验证无退化、明确退化及覆盖不足，再在CI查看比较摘要；不增加评分规则或模型任务。

## 文件修改

| 文件 | 修改 | 原因 |
| --- | --- | --- |
| dsh_eval/regression_demo.py | 新增固定合成实验生成、实际比较CLI、预期验证与五文件产物 | 复用已有执行 / 录制 / 评分，验证真实退出码 |
| test/test_regression_demo.py | 新增独立录制、fresh复验、冲突、错误语义及复制checkout回归 | 避免伪造保存结论或依赖私人输入 |
| package.json | 新增demo:regression | 提供本地和CI一致的入口 |
| .github/workflows/deterministic.yml | 新增演示、摘要和限定文件上传三步 | 通过Actions展示可复现的合成比较结果 |
| README、架构、基线比较、能力矩阵与进度 | 同步入口、格式、状态和证据范围 | 区分演示成功、真实门禁及尚待云端验证的配置 |
| docs/ci-regression.md | 新增用法、退出码、产物及真实门禁示例 | 下载结论与完整归档复验边界明确 |

## 实现与技术取舍

同一公开rename-confirmation用例与单配置两轮计划，分别生成baseline、no-regression、regression和incomplete四个独立实验。前两者回复done / done，后两者预先固定为WRONG / done；incomplete另以stop_after=1正常停止，不删除证据。共执行七次实际合成任务，保存synthetic来源和modelCalled=false；实际Node工具进程、recorder、inspect与产品评测器保持。

三个新Python CLI进程执行原比较：无退化为两项unchanged_passed / 退出0；明确退化为一项regression与一项unchanged_passed / 退出1；覆盖不足为一项regression与一项unavailable / 退出2，保留已确认退化。生成器核对JSON正常比较状态、原退出码、计数、来源、身份与计划核验，并要求输出文件和stdout一致。输入错误2不能冒充正常缺证2。失败诊断保留场景、实际退出码及最多2000字符stderr。

生成器只在三个预设场景都正确时返回0，表示示例验证成功。真实门禁继续直接调用`--compare-baseline`并传递原1 / 2，不能以演示包装器的成功替代候选结论；0也不表示所有任务通过。原比较与评测格式不改，新索引独立使用regressionDemoFormatVersion=1，记录身份、路径、三场景、退出码与源SHA-256。

输出目录必须新建，不覆盖已存在路径。inputs / experiments与artifacts分开；比较前后对128份生成源文件核对摘要保持。CI只列明上传三份比较JSON、summary.md、index.json，保留7天，禁用隐藏文件。不上传运行目录通配符或原始录制。摘要以代码文件名呈现，避免在GitHub Step Summary制造无效的相对附件链接；文件从Actions产物入口下载。

摘要和上传在失败后仍处理已经生成的文件，不使用continue-on-error掩盖演示失败。上传使用官方[actions/upload-artifact v7.0.2](https://github.com/actions/upload-artifact/releases/tag/v7.0.2)，已核对[action.yml](https://github.com/actions/upload-artifact/blob/cf430e030ddbb5b0abf93d22962f4752f3646cd9/action.yml)并固定完整SHA `cf430e030ddbb5b0abf93d22962f4752f3646cd9`。原CI检查和15分钟超时保持。

## 验证

Windows、Node.js v24.14.0、Python3.12.0。本地合成 / 子进程检查与云端步骤状态分开记录。

| 命令或操作 | 实际结果 | 范围 |
| --- | --- | --- |
| npm.cmd run demo:regression -- --output-dir runs/ci-regression-demo | 当前最终版本exit0 / 2.749秒，三个实际退出0 / 1 / 2，产物精确五文件 | 公开npm入口与CI相同参数、四实验、七合成任务，128源文件摘要保持 |
| 实际GetShortPathNameW别名作为新进程TMP / TEMP，执行test_regression_demo.py | 当前版本8项 / 6.062秒通过，无跳过 | 真实NTFS短临时根，不依赖模拟路径 |
| npm.cmd run test:python（允许实际子进程与链接的环境） | 641项 / 377.557秒通过，无跳过 | 完整Python回归，含最终版本新八项集成测试 |
| npm.cmd test（允许实际子进程的环境） | 154项 / 6.977秒通过，0失败 / 跳过 | 完整Node回归及Web启动清理 |
| npm.cmd run check；python -m compileall -q dsh_eval scripts test | 45个JS文件语法及Python编译通过 | 语法与编译 |
| 原PowerShell摘要追加命令写入隔离目标、中文探针 | 严格UTF8解码及中文追加通过，环境恢复 | 本地模拟GITHUB_STEP_SUMMARY文件写入，不等于云端渲染或上传 |

完整Python与Node回归均已通过；独立复核未发现新的阻塞问题。git diff --check与八份文档566个相对文件链接目标检查通过。首轮沙箱Node为152通过 / 2失败，均因真实Web子进程spawn EPERM；沙箱Python出现权限相关跳过后停止，未形成完整结果。随后改用允许实际子进程和链接的环境复验，未改测试要求或以mock替代；相关旧测试子进程已确认退出。

当前尚未提交推送，新CI摘要和上传未实测，不沿用8afe490的成功CI。没有新增真实模型调用；本批仅使用新生成合成数据，不修改历史真实轨迹。

## 限制与后续

五文件产物是保存的比较结论，不含完整原归档，保存路径仍指向原运行目录，下载后不能独立fresh inspect。需要搬迁复验时使用显式目录归档包；这些结果也不构成模型可靠性、统计显著性、总体胜率或性能结论。

本批不自动选择真实基线、不配置分支保护、不接入比较浏览页、不新增跨平台声明。后续批次B接入比较浏览和双方证据定位，批次C再做整体新checkout交付验收与当前文档整理。CHANGELOG、进度、架构、能力矩阵及相关使用文档已同步。
