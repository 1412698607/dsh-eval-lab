# dsh-eval-lab

面向 DeepSeek Harness 的 Agent 行为回归测试项目。第一阶段实现实时会话轨迹记录，为后续测试用例、确定性断言和版本对比提供输入。

## 当前功能

- 作为 Cordis 插件订阅 `session/event`，保留原始事件，包括消息、工具调用、工具结果及轮次边界。
- 每次插件启动创建独立运行目录，每个会话写入独立 JSONL 文件。
- 使用异步写入队列保持同一会话的观察顺序，通过 `session/flush` 和插件卸载等待已排队写入完成。
- 写入失败时记录错误，后续 checkpoint 报错；失败会话停止继续录制，其他会话仍可写入。

接入验证使用本机安装缓存中的 **DSH 0.2.0-rc.2 / Cordis 4.0.4**。插件声明对应的可选 peer，以供 Harness 检查版本兼容性。无需构建，也无需安装依赖即可运行模拟演示和单元测试。

## 本地演示

在 PowerShell 中运行：

```powershell
Set-Location 'D:\codexWorkspace\dsh-eval-lab'
npm.cmd run check
npm.cmd test
npm.cmd run demo
```

`demo` 写入 8 条模拟事件，不调用模型、不产生模型费用。它只展示日志输出，不代表完成真实 Agent 评测。`test` 在同一进程运行，避免部分 Windows 沙箱对测试子进程的限制。

真实组件接入检查：

```powershell
npm.cmd run smoke:host
```

脚本自动寻找 Windows npm 缓存里的匹配版本，加载真实 Cordis 和 SessionStore，挂载插件，创建会话并提交工具调用及结果，然后验证导出的事件与原事件一致。它不启动 Web 服务、不执行真实文件工具、不调用模型，也不修改已有 Harness profile。

若 Harness 安装在其他位置，可以传入它的 `node_modules` 路径：

```powershell
npm.cmd run smoke:host -- 'D:\your-harness\node_modules'
```

## 安装到 Harness

当前配置写入 `D:/codexWorkspace/dsh-eval-lab/runs`。项目换位置时，需要先修改 `cordis.patch.yml` 中的 `outputDir`，该值必须是绝对路径。

以下命令适用于 CLI 的 **web profile**，需要安装版 CLI 所使用的 pnpm 可执行文件可用：

```powershell
Set-Location 'D:\codexWorkspace\dsh-eval-lab'
npx.cmd @deepseek-ai/dsh@0.2.0-rc.2 plugin --profile web add 'D:/codexWorkspace/dsh-eval-lab'
npx.cmd @deepseek-ai/dsh@0.2.0-rc.2 web
```

插件加载后，服务端终端会显示 `[eval-lab] 日志目录：...`。在 Harness 中创建新会话，提交一个需要读取文件的任务；完成后在该目录检查 JSONL 文件中的 `tool/call` 和 `tool/result`。模型凭据使用你已有的 Harness 配置。

如果你运行的是 Harness 桌面版，应使用它实际使用的版本和 **desktop profile**。这里尚未执行桌面版安装，也尚未验证 Web 页面里的真实模型任务；`smoke:host` 验证的是会话组件和插件事件接入。

## 输出结构

```text
runs/
  <run-id>/
    run.json
    <sha256(session-id)>.jsonl
  host-smoke/
    <run-id>/
      run.json
      <sha256(session-id)>.jsonl
```

`run.json` 包含格式版本、插件版本、运行 ID 和启动时间。JSONL 每行包含 `formatVersion`、`runId`、`sessionId` 和完整 `event`。哈希文件名避免会话 ID 被当成路径，原始 ID 仍保存在每条记录中。

日志包含原始会话及工具内容。`runs/` 已加入 `.gitignore`；作品集展示可使用 `demo` 的模拟数据。

## 第一版边界

- 只录制插件观察到的新增事件；不会补齐加载前、恢复会话或 fork 继承的历史。`run.json` 明确标注 `live-events-only`，这些日志不能直接作为完整会话恢复文件。
- 已完成异步写入不代表断电时绝对可靠；强制终止进程可能丢失待写入数据。当前没有跨进程恢复、持久化完成标记、队列上限或日志轮转。
- 当前不执行评测，不生成通过率；也尚未实现状态化工具 mock、测试断言、A/B 重跑和界面。

## 下一阶段

1. 定义测试用例格式：任务、初始文件、工具行为、断言和预算。
2. 实现状态化虚拟文件系统，覆盖“README 路径过时”和“工具失败后恢复”两个场景。
3. 接入 Harness 原有 Agent 循环，对结果断言，区分通过、失败和运行错误。
4. 多次重复比较两组配置，汇总成功率、调用次数、token 和耗时，再添加结果展示页面。

官方接口参考：[会话事件](https://deepseek-harness.github.io/deepseek-harness/en/reference/subsystems/session)、[扩展插件](https://deepseek-harness.github.io/deepseek-harness/en/reference/cookbook/extension-cookbook)。
