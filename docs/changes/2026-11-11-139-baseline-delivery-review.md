# 修改记录 139 批次B、C复查与边界修正

日期：2026年11月11日，Asia/Shanghai。类型：修复、测试、文档。插件版本：0.1.2。相关Git提交：本记录形成时尚未提交；起点为已核实的 `1717cc997a0a386c64416ff9a95e66751dc2a013`。

## 问题与复查范围

复查[137比较浏览](2026-11-11-137-baseline-regression-browser.md)和[138离线交付检查](2026-11-11-138-synthetic-delivery-check.md)的全部源码、测试、配置与文档。范围包括普通 / v1 / v2来源图、身份和规范路径、双方证据、过滤原索引、安全文本、真实搬迁、HTTP收尾、源码导出来源及五文件上传边界。确认两项问题并定点修复，其余范围未发现新的阻断问题。

1. 比较结果的limitations条目直接进行字符串转换。合法JSON对象如 `{"toString":null,"valueOf":null}` 会触发 `Cannot convert object to primitive value`，整份详情未插入，保存完整JSON的入口也无法显示。新增回归先确认修复前失败，再复用已有安全显示函数保留对象JSON文本；null显示缺失，HTML仍作为文本。
2. 交付检查只回收serve_forever线程和监听套接字，ThreadingHTTPServer的默认守护请求线程不在server_close的等待范围中。真实HTTP handler已发完响应但在finish阶段仍被Event阻塞时，原helper已经返回，而两个实际请求线程仍存活。仅将本次自建服务的daemon_threads设为False，使server_close等待这些线程；新增正常请求与HTTP错误两条真实收尾回归。既有浏览服务默认值不改，不把停止监听误当作全部请求线程退出。

## 文件修改

| 文件 | 修改 | 原因 |
| --- | --- | --- |
| dsh_eval/web/app.js | limitations条目使用已有regressionValue | 异常保存元数据不使整页渲染中断 |
| test/browser.test.js | 新增对象 / null / HTML文本回归 | 核对详情与完整JSON入口仍可用 |
| dsh_eval/delivery_check.py | 仅本次检查服务使用非守护请求线程 | server_close实际等待所有已创建请求线程 |
| test/test_delivery_check.py | 新增真实handler.finish受控等待，覆盖成功和错误路径 | 验证回收顺序和线程真实终止，避免检查空_threads集合 |
| README、docs/architecture.md、docs/delivery-check.md、docs/capabilities.md、docs/progress.md、CHANGELOG | 同步修正、验证范围及交付状态 | 保留137 / 138原结果，不沿用旧候选证明新版本 |
| docs/result-browser.md | 补齐现有工作流生成、比较门禁、新交付检查及五文件上传说明，编译范围补入scripts | 通用CI命令清单与实际工作流一致 |

## 实现与技术取舍

不改变原评分、比较JSON格式、门禁0 / 1 / 2或关联ID守卫。前端复用既有文本转换，不引入新序列化层。HTTP修正局限于交付检查自己创建的服务；等待请求线程完成与主服务线程join分开，不扩大为通用浏览器生命周期重构，也不宣称清理有总耗时硬上限。反例使用真实HTTP请求和线程，Event仅控制真实handler收尾时点，没有模拟线程退出。

138中的338文件旧HEAD导出、344文件候选导出和672 / 164完整回归保留形成时范围；该候选在本次修复之前，不能作为修复后运行代码一致性的证明。B/C交付仍需当前代码回归和精确提交的独立CI与上传核对。源码导出、实际HTTP / API、前端单元测试与摘要网页显示属于不同证据。

## 验证

日期同上，Windows、Python3.12.0、Node.js v24.14.0；固定合成 / 离线检查，无新增模型任务。

| 命令或操作 | 实际结果 | 范围 |
| --- | --- | --- |
| python -m unittest discover -s test -p test_regression_browser.py -v | 实际链接环境20项 / 16.197秒通过，无跳过 | B后端来源、身份、链接 / junction、规范位置及只读边界 |
| 同一20项首轮沙箱执行 | 20项 / 16.349秒，2项因WinError1314跳过 | 仅记录环境限制；不作为最终无跳过证明，后续完整复验如上 |
| node --test --test-isolation=none test/browser.test.js | 73项 / 212.4097毫秒全部通过，无跳过 | 原前端行为及新增limitations渲染反例；新增项修复前已失败 |
| python -m unittest discover -s test -p test_delivery_check.py -v | 实际链接环境9项 / 28.624秒全部通过，无跳过 | 搬迁、输出冲突、CLI和正常 / 错误请求线程收尾 |
| 同一9项首轮沙箱执行 | 7通过、2个既有symlink权限错误 / 30.837秒 | WinError1314环境限制，后续实际链接环境完整复验如上 |
| 在测试进程内移除本次daemon设置，运行新增HTTP收尾回归 | 1项 / 14.873秒，两个subTest按预期失败 | 磁盘源码未修改；旧行为在真实handler仍阻塞时提前返回，反例确实能发现缺陷 |
| npm.cmd test；npm.cmd run check | 165项 / 7.088秒通过，无失败 / 取消 / 跳过；45个JS文件语法通过 | 修复后完整Node回归与语法 |
| npm.cmd run test:python | 673项 / 420.176秒，OK，无跳过 | 修复后当前全部Python回归，实际链接、HTTP和子进程环境 |
| python -m compileall -q dsh_eval scripts test | 退出0 | 当前Python语法 |
| 文档相对链接 / 锚点、git diff --check、代码清单 | 14份变更文档749个相对链接通过，补丁检查通过，170份代码 / 测试 / 配置自最终回归启动后保持 | 链接目标属于公开文件集合，不检查外部网址状态 |

最终源码、文档及验证范围独立复核通过。原始运行、依赖与私人资料无跟踪文件，不加入提交。本记录形成时尚未提交推送，新CI和产物尚未核对，摘要网页渲染继续未验证。

## 风险与后续

当前验证环境为Windows；真实链接、HTTP与子进程需要环境支持，不以mock或跳过替代。CI仍只上传三份比较JSON、summary.md和index.json，不包含原始录制，不是可独立重评的完整归档。没有扩大真实模型、归档格式或搬迁后调度执行范围。

## 文档同步

当前架构和命令说明补充请求线程等待与异常元数据边界，README、能力矩阵及交付说明明确138为修复前候选，通用浏览说明同步实际CI命令。进度与CHANGELOG链接本记录。137 / 138保留当时的实现、失败、复验和未提交快照；当前交付状态随后以新提交和云端回执明确记录。
