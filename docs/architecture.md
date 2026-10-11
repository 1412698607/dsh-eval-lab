# dsh-eval-lab 架构与技术取舍

当前架构实现 Harness 事件到本地日志的记录链路。插件入口适配宿主，独立记录器处理文件与状态，演示和测试分别验证数据输出及宿主接入。

## 执行流程

```text
package.json 声明插件入口和 bundle patch
  → cordis.patch.yml 插入插件空配置
  → Harness 调用 apply(ctx, config)
  → config.outputDir / 环境变量 / 用户主目录，按优先级解析绝对目录
  → 创建记录器与运行目录
  → session/event 将事件交给 record(sessionId, event)
  → 立即序列化，接入会话独立的 Promise 队列
  → 异步追加至会话 JSONL 文件

session/flush → 等待指定会话检查点 → 检查错误
dispose       → 拒绝新事件 → 等待所有会话写入
```

## 模块职责

| 文件 | 职责 |
| --- | --- |
| `package.json` | ES Module 入口、包导出、版本兼容元信息及运行命令 |
| `cordis.patch.yml` | 插入插件空配置，不绑定开发机目录 |
| `src/index.js` | 声明 `sessions` 依赖，连接事件、检查点和卸载钩子 |
| `src/config.js` | 路径优先级与选中值校验 |
| `src/metadata.js` | 从 package.json 读取插件版本与会话组件基线 |
| `src/recorder.js` | 运行目录、会话文件名、队列、错误与关闭状态 |
| `scripts/demo.js` | 人工构造 8 条事件，演示日志输出 |
| `scripts/smoke-host.js` | 使用真实 Cordis 与 SessionStore 提交并核对事件 |
| `scripts/lib/host.js` | 自动查找或显式选择宿主，加载前校验组件版本 |
| `scripts/lib/host-smoke.js` | 复用真实组件检查，隔离输出目录及释放资源 |
| `scripts/check-output.js` | 启动真实子进程，分别断言 stdout 与 stderr |
| `scripts/fixtures/output-child.js` | 无摘要输出的真实插件挂载入口，包含磁盘失败场景 |
| `scripts/check-syntax.js` | 遍历源代码、脚本与测试，逐文件执行语法检查 |
| `test/recorder.test.js` | 顺序、内容、会话隔离、异常和关闭行为验证 |
| `test/config.test.js`、`test/host.test.js` | 配置优先级、无效值和宿主版本边界测试 |

## 目录与输出通道

插件入口按显式 `config.outputDir`、`DSH_EVAL_OUTPUT_DIR`、`homedir()/.dsh-eval-lab/runs` 依次选择。`undefined` 表示未配置，空字符串或 null 等无效覆盖直接报错。默认位置不受宿主工作目录影响。独立记录器仍要求调用者传入绝对目录，演示和测试不依赖用户目录。

启动信息及写入错误均使用 `console.error()` 写入 stderr，JSONL 写到文件。入口不输出协议 stdout；子进程检查直接挂载真实组件，在正常与磁盘错误两个场景验证该边界。检查命令自身的成功摘要可使用 stdout。此检查不等于已完成 SDK、ACP 或 headless 整体协议验证。

组件检查固定校验 dsh-session `0.2.0-rc.2` 与 Cordis `4.0.4`。显式路径不匹配时不自动换安装；自动缓存查找跳过不匹配候选。Cordis 的 `FiberState` 是编译后擦除的 const enum，JavaScript 无法导入；检查脚本使用有来源注释的本地 `HOST_FIBER_ACTIVE`，并将其限定在已校验的版本中。插件运行时仍使用可选 peer 声明，不重复加载宿主检查其版本；其他版本尚未验证。

## 语言选择

原生接入层通过 Cordis 的 JavaScript 模块接口导出 `name`、`inject` 和 `apply`。第一版使用纯 JavaScript ES Module，使源码能够直接运行，减少构建配置，先验证插件接入。TypeScript 是后续复杂数据模型的候选，可为事件、用例和断言增加类型检查；尚未迁移。

Python 可以作为离线日志分析或评测程序，通过文件或进程接口连接原生插件。当前没有实现 Python 评测，已有 `main.py` 保持不变。

## 数据组织

```text
runs/<runId>/run.json
runs/<runId>/<sha256(sessionId)>.jsonl
```

`run.json` 包含 `formatVersion`、插件名称与版本、`runId`、UTC 启动时间、`captureScope` 和文件命名规则。`captureScope` 固定为 `live-events-only`，用于限定日志范围。

每条 JSONL 记录包装为：

```json
{
  "formatVersion": 1,
  "runId": "example-run",
  "sessionId": "example-session",
  "event": {
    "seq": 3,
    "time": 1791374400000,
    "type": "tool/call",
    "data": {
      "turn": 1,
      "step": 1,
      "callId": "example-call",
      "name": "read_file",
      "arguments": "{\"path\":\"README.md\"}"
    }
  }
}
```

上例是结构示意，工具名和调用参数是示例。记录器保留原始事件，不解析工具参数，不校验业务事件 schema，也不去重或按序号重排。

## 写入顺序与检查点

每个会话在 `Map` 中保存 `{ pending, error }`。首条事件以 `Promise.resolve()` 为队列起点，后续写入通过 `.then()` 接在旧队尾后。每次 `appendFile()` 完成后，该会话才开始下一次写入。不同会话的队列互相独立。

事件在入队前转成字符串，避免调用方随后修改原对象导致日志变化。JSON 序列化仍然同步消耗 CPU；目录和元信息初始化也是同步操作。运行期文件追加使用异步 I/O，因此不应将整条链路描述为完全无阻塞。

`record()` 返回 `true` 表示已排队。`flush(sessionId)` 等待调用时选中队尾所代表的写入，再检查保存的错误。后续新增写入不包含在该次等待范围内。错误状态是会话级持续状态，不是独立的检查点版本。

## 错误与关闭

首次序列化或写入错误保存在会话状态中并报告。后续该会话的录制停止，其他会话仍可写入。队列捕获异步写入异常，检查点通过 `AggregateError` 报告失败；错误不是写入文件的持久化状态。

`close()` 先设置关闭标志，再等待全部会话的队列。新事件被拒绝，之前已经排队的有效任务可以继续执行。当前没有跨进程恢复、重试或失败日志修复。

独立记录器的 `close()` 会拒绝写入失败；插件 dispose 回调返回该 Promise，但 Cordis 4.0.4 的卸载流程捕获并记录清理错误，`fiber.dispose()` 完成不代表日志有效。真实组件失败检查通过 `ctx.sessions.flush(session)` 的拒绝验证错误传播。M2.2 需要持久化状态使离线检查不依赖宿主退出或卸载结果。

## 技术取舍

| 选择 | 原因 | 代价与边界 |
| --- | --- | --- |
| JSONL | 逐条追加、可逐行读取，减少第一版存储依赖 | 查询和完整性管理需要后续实现，当前没有索引 |
| 会话独立 Promise 队列 | 保持观察顺序，隔离会话写入状态 | 没有容量上限、背压或状态淘汰 |
| 入队前序列化 | 固定接收时的数据内容 | 序列化会同步消耗时间和内存 |
| UUID 运行目录 | 区分插件启动批次，降低覆盖风险 | 一个批次可包含多个任务，尚未建模评测运行 |
| SHA-256 文件名 | 会话 ID 不直接参与路径解释 | 不提供内容加密，原始 ID 仍存于日志中 |
| 失败后停止该会话录制 | 在当前进程中显式暴露不完整记录 | 没有持久化标记，离线消费者仍需额外完整性协议 |
| 可选版本 peer | 标注目标组件版本，独立测试不必安装宿主 | 最终宿主版本仍需实际兼容检查 |

## 验证边界

模拟演示验证记录器输出。单元测试验证记录器和简化上下文。真实组件检查通过 `ctx.plugin()` 挂载服务和插件，人工提交事件并比较文件内容；该检查不等于 Web 或桌面真实模型任务的端到端验证。

当前验证基线和后续计划见 [开发进度](progress.md)。未来事件 schema、错误状态或存储格式变化时，需要同步更新本说明。

M2.1 已统一 stderr，并通过真实组件子进程输出检查。SDK 完整生命周期尚未联调，持久化状态文件与离线检查工具仍属于 [M2 方案](plans/m2-reliable-recording.md) 的后续批次。
