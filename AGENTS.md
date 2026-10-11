# dsh-eval-lab 开发约定

本项目实现 DeepSeek Harness 的 Agent 轨迹记录与回归评测工具。每批修改保留问题、实现、技术取舍和验证依据。本文件适用于本目录及其子目录。

## 修改与文档同步

1. 修改功能、修复缺陷、调整配置或测试后，在同一轮工作中新增 `docs/changes/YYYY-MM-DD-NNN-topic.md`。按一次可独立说明的改动记录，不需要为每条命令创建文档；同一轮紧密相关的修改可合并。纯文档整理也记录范围，内容可以简短。
2. 使用 `docs/templates/change-record.md`，至少写清日期、问题或目标、修改文件、关键逻辑、技术取舍、验证结果、限制和后续事项。日期按用户所在时区 Asia/Shanghai。NNN 从现有记录的最大编号继续递增。
3. 在 `CHANGELOG.md` 添加到新记录的链接；功能状态或验证范围变化时更新 `docs/progress.md`，架构或数据格式变化时更新 `docs/architecture.md`，运行方式变化时更新 `README.md`。本地存在 `private-notes/interview.md` 时，将相关技术讨论同步到该私人材料；不作为公开仓库依赖。
4. 不覆盖历史验证结果。复验或发现历史判断错误时，在新记录中说明日期和修正，当前状态写入 `docs/progress.md`。
5. 完成前检查文档与实际代码一致、相对链接有效、验证结果可复现。纯文档修改无需重复执行全部代码测试；根据改动选择检查。
6. 本地存在 `private-notes/handoff.md` 时，每批结束更新其当前结果、未完成项、下一批入口和必要的复现命令。新会话先读取本文件，再读取本地交接文档（如存在）、`docs/progress.md` 和相关方案；以实际文件及 Git 状态为准。公开仓库不依赖私人材料即可接续开发。

## 公开与私人资料

- `private-notes/` 保存个人准备材料和本机交接说明，已被 Git 忽略。不得强制添加该目录或恢复向旧的 `docs/interview.md`、`docs/handoff.md` 路径写入。
- 公开 Markdown 链接只指向可提交的文件，不链接私人资料、原始运行日志、缓存或凭据。引用本机路径时使用可移植示例，保留可核对的技术事实。
- `.gitignore` 不会取消已有跟踪或清除提交历史。提交前核对忽略规则和实际跟踪文件，不自动移除已跟踪文件或改写历史。

## 事实与验证

- 明确区分已实现、已验证、计划开发。模拟事件、真实会话组件接入、真实模型端到端任务分别记录。
- `record()` 返回成功只表示排队成功；`flush()` 等待所选检查点的写入完成，不代表 fsync、断电可靠或日志具备持久化完成标记。
- 记录实际执行的命令和结果；没有运行的检查不能写为通过。没有测量的数据不能写为性能提升、成功率提升或成本降低。
- 日志是新增事件片段，不能称为完整会话备份、可恢复日志或确定性重放系统。
- 文档记录相关 Git 提交时，只填写已存在并核实的提交。修改记录编号不等于 Git 提交号。不为文档工作自动提交或推送。

## 项目结构与运行

- `src/index.js`：Cordis 插件入口；`src/recorder.js`：独立日志记录器。
- `scripts/demo.js`：模拟演示；`scripts/smoke-host.js`：真实 Cordis 与 SessionStore 接入检查。
- `test/recorder.test.js`：Node.js 测试。Windows 下使用 `npm.cmd`，当前测试命令在同一进程运行。
- 常用命令：`npm.cmd run check`、`npm.cmd test`、`npm.cmd run demo`、`npm.cmd run smoke:host`、`npm.cmd run check:output`。最后一项需要真实子进程，沙箱出现 EPERM 时报告验证限制，在获准环境或外部终端执行，不能使用 mock 代替。
- 保留用户已有代码，尤其不要因插件使用 JavaScript 就删除 `main.py`。
- `runs/` 包含原始会话与工具内容且已被 Git 忽略；项目说明使用模拟数据，避免将真实运行日志加入版本管理。
