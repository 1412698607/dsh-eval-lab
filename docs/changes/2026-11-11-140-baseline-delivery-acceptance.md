# 修改记录 140 批次B、C交付与精确提交验收

日期：2026年11月11日，Asia/Shanghai。类型：文档、交付验收。插件版本：0.1.2。相关Git提交：已核实实现 `42bc019bd201f1a734671dd61dc649adb31b406d`，本记录形成时尚未提交。

## 目标与交付范围

[137](2026-11-11-137-baseline-regression-browser.md)比较浏览、[138](2026-11-11-138-synthetic-delivery-check.md)合成交付及[139](2026-11-11-139-baseline-delivery-review.md)复查的24份公开文件已共同提交推送为 `42bc019bd201f1a734671dd61dc649adb31b406d`。139修复异常limitations中断渲染、HTTP守护请求线程未等待退出两项问题。本记录登记该精确提交的独立源码导出、CI及上传核对，137至139的旧候选和未提交表述保留形成时状态。

## 文件修改与技术取舍

| 文件 | 修改 | 原因 |
| --- | --- | --- |
| 本记录、CHANGELOG、docs/progress.md | 记录实现提交、源码导出及独立云端回执 | 本地 / 旧候选结果不替代精确提交CI |
| README、docs/capabilities.md、docs/delivery-check.md | 更新当前交付与验证入口 | 历史候选与已提交版本分别可追溯 |

本次仅资料更新，不改变生产代码、测试、配置或历史模型任务。摘要发布步骤、ZIP内Markdown及网页渲染分别记录；摘要网页渲染继续未验证。五文件比较产物不含完整原证据，上传审计不冒称能够独立重评。

## 已提交源码的仓库外导出验收

对上述完整SHA执行Git archive，核对ZIP提交注释、Git ls-tree成员及安全路径，345个公开文件解包至原仓库之外的新临时目录。ZIP为1,275,875字节，SHA-256为 `7f7099921abd2717c80c842c527dd569d21c5aa2e5f8a43cddd0bcf2489d9a66`；声明源码内容清单摘要为 `7a6c8bb7b90d8c05f3afdfe37590758c086c9c60d8bd79c178a7ae320258a9c2`。未导出.git、runs、私人资料、依赖或缓存，源码及祖先无node_modules。

标准库控制脚本仅在独立子进程从解包源码导入产品模块，清除PYTHONPATH、NODE_PATH、NODE_OPTIONS，禁用用户Python站点包，确认delivery_check模块路径和ROOT指向解包目录。从该目录运行 `npm.cmd run check:delivery -- --output-dir <new-output>`，退出0，八阶段、13次固定合成任务及原0 / 1 / 2符合预期；归档核验不评分，包外fresh报告四样本verified。独立重新计算99个退休源文件、133个比较源文件及53个包文件的摘要，与入口在搬迁前保存的清单一致；345个导出源码文件由控制脚本在命令前后独立核对，字节保持。两根共4次HTTP与深层API检查完成，服务收尾通过，不作为实际DOM显示验收。没有安装Harness、项目依赖或调用模型。

138的338文件旧HEAD与344文件旧候选证明仍保留；本节另行证明包含本次修复的已提交版本，未将旧清单升级为当前字节一致性证据。

## 精确提交CI与产物

本实现的[push运行42870991183](https://github.com/1412698607/dsh-eval-lab/actions/runs/42870991183)与[job130021902708](https://github.com/1412698607/dsh-eval-lab/actions/runs/42870991183/job/130021902708)、attempt1已全部完成。公开API独立核对run / job的完整head_sha、分支与attempt，运行、作业和全部18步均success。

| 检查 | 实际云端结果 |
| --- | --- |
| Python完整回归 | 原作业日志673项 / 581.703秒，OK，无跳过 |
| Node完整回归 | 165项 / 11.534秒全部通过，0失败 / 取消 / 跳过 |
| 语法与原示例 | 45个JS文件语法、compileall、原合成评测和工作流生成成功 |
| 基线门禁示例 | 三次比较原退出0 / 1 / 2，128份源文件摘要保持，modelCalled=false |
| 新交付步骤 | 八阶段completed，13次合成任务、包实际搬迁、verify不评分、包外四样本fresh复验、4次HTTP与深层API收尾成功 |
| 摘要发布与上传 | 两步成功，上传范围仍为五份固定比较文件；没有上传C原始输出 |

正式下载工具取得本run唯一产物，独立读取实际ZIP字节并与API核对：

| 产物项目 | 实际结果 |
| --- | --- |
| artifact ID / 名称 | 13790477376 / synthetic-regression-gates-42870991183-1 |
| 绑定 | workflow_run.id、分支与完整head_sha均匹配本实现 |
| ZIP大小与SHA-256 | 12,276字节；`514d7ab2e60e9595af5933f17ed4c46c5f53b66ad0d59fba208f72fab50f0468`，与GitHub digest一致 |
| ZIP成员 | 精确五个平面文件：incomplete.json、index.json、no-regression.json、regression.json、summary.md，无目录或额外成员 |
| 三份比较与索引 | 三份比较status=compared，索引status=completed，均modelCalled=false；原0 / 1 / 2、覆盖2/2、2/2、1/2；覆盖不足保留regression=1、unavailable=1；索引synthetic且128条SHA-256声明格式正确 |
| summary.md | 908字节UTF8，与三个场景的结论 / 覆盖一致，并保留“演示成功不表示全部任务通过”的说明 |
| 有效期 | 非expired，2026年11月11日02:12:58至11月18日02:12:58（Asia/Shanghai），精确7天 |

下载包不含原源文件，128条源摘要在下载审计中仅核对数量、格式与声明；实际源字节不变由本次CI生成器的前后核对证明。摘要发布步骤与下载文本已验证，摘要网页渲染继续未验证；本次没有进行浏览器操作。

## 文档验证与后续

本次仅资料更新，不重复执行本地全部代码测试；相对开发起点的15份变更文档757个公开相对链接 / 锚点及补丁检查通过，运行代码 / 测试 / 配置不变。资料提交自身的CI也独立核对，不继承实现提交结果。原始运行、源码ZIP与下载审计副本保留在忽略目录，不加入公开提交。摘要网页渲染仍未验证，不扩展真实模型或其他平台验收。
