# 本地结果浏览与持续集成

更新：2026 年 10 月 21 日，Asia/Shanghai。M5 已实现本地只读浏览和无模型 CI 配置，插件保持 `0.1.2`，沿用现有用例、批次、实验、报告和证据格式。

## 打开与停止

在项目根目录运行，需要 Python 3.12 或更高版本，无需安装前端依赖：

```powershell
python -m dsh_eval --browse
```

终端输出一行 JSON，其中 `url` 是带本次访问令牌的本机地址。完整打开该地址；默认自动选择空闲端口。页面不自动打开浏览器，终端按 Ctrl+C 停止服务。关闭页面不会停止服务。

默认用例库是 `fixtures/evaluation`，结果目录是 `runs`。可以指定其他目录或端口：

```powershell
python -m dsh_eval --browse --cases-root fixtures/evaluation --runs-root runs --port 8765
```

`--runs-root` 在浏览模式中仅表示读取位置，不会创建目录。独立放置的报告、实验及录制目录，需要在指定结果根目录内才能互相打开；不存在或超出范围的关联显示“缺失或超出浏览目录”，不搜索其他磁盘位置。旧报告中的绝对路径迁移后可能失效，浏览器不会修补历史文件。

浏览不能与 `--run`、`--evidence`、`--output`、`--reports-root` 或宿主控制选项混用。启动成功时服务持续运行，Ctrl+C 正常返回 0；非法端口或绑定失败输出错误 JSON 并返回 2。

## 从列表到证据

页面分为实验、配置报告、批次、逐次结果和用例库。用例库收录 `*.case.json`；结果列表收录 `experiment-result.json`、`report.json`、`batch-result.json`、`evaluation.json`，冻结输入及报告中的复验结果通过关联文件打开，避免把每份快照都当成一个新用例。支持名称 / 标识 / 路径搜索、任务结论筛选及来源声明筛选；“刷新文件”重新读取目录。

来源筛选保留样本中的缺失声明，因此同一实验 / 报告可同时出现在真实运行、合成和缺失筛选中。缺失来源仅在浏览响应中标为 `unknown`，不修改原 `source`；失败样本的结构化异常显示类型与消息。

- 实验与报告显示原计划样本、全尝试通过比例、可评测通过比例及可评测覆盖，比例同时显示分子 / 分母，零分母仍为缺失。
- 样本行显示请求配置、实际 provider / model、配置匹配、来源声明，以及执行 / 录制 / 断言三维结果。点击样本打开保存的逐项评测，再进入用例快照、证据清单、执行事实、录制状态及事件轨迹。
- 配置报告显示保存的 `verification`、`saved.outcome` 与 `changedFields`，并展示同来源共同配对数量、排除、逐指标观测 / 缺失配对、右减左差值及范围。`verified` 显示为“复验已处理”，不等于任务通过。完整保存值可在折叠 JSON 中核对。
- 指标保留缺失，不用零替代。页面数值保留六位有效数字，原 JSON 不变；时间按 Asia/Shanghai 显示。
- JSONL 每页默认 50 行，可前后翻页，保留原行号和原事件。无法解析的行显示错误及预览；超过 64 KiB 的行只显示最多 2048 字节预览，不将预览当作完整记录或断言证据。

浏览只显示保存时的内容，不调用 `evaluate`、Node inspect、runner 或模型，不改变历史结果。`complete`、`passed` 和配置匹配均是文件中保存的结论，可能已过时；`live` / `synthetic` 是来源声明，不是签名。需要重新检查日志和断言时，使用现有离线入口：

```powershell
python -m dsh_eval --report 'runs/experiments/<experimentId>/experiment-result.json'
```

这个命令会单独生成新报告；页面刷新后可以查看。单用例复验仍使用 [评测格式](evaluation-format.md) 的 `--case ... --evidence ...` 入口。

## 读取边界与限制

Python 标准库服务仅绑定 `127.0.0.1`，仅提供静态页面和读取 API。API 要求本次启动生成的随机令牌，令牌在 URL fragment 中传给页面，随后用请求头访问 API；拒绝不匹配的 Host / Origin，不开放跨域读取，不缓存响应。浏览器在当前标签页会话中保存令牌以支持刷新，重新启动服务须使用新地址。这不是面向远程或多用户的登录系统。

文件必须落在显式的两个根目录内；关联路径先规范化文本并检查范围和禁用目录，再解析真实路径并复核。根外绝对路径、相对越界路径和未配置的 UNC 位置不会先被解析。每次读取仍拒绝目录穿越、隐藏路径、NTFS 备用流及 home / workspace / private-notes / secrets 等目录。扫描不跟随符号目录或 Windows junction，避免绕入私人目录或循环。任意脚本、普通文本输出和凭据文件没有下载入口，原始 JSON / 事件内容通过文本节点显示，不执行其中的 HTML。

目录最多列出 2000 项，超过后明确提示截断；单份 JSON / Markdown 最大 8 MiB，JSON 对象 / 数组容器最多 128 层；轨迹 API 每页最多 200 行、offset 最大 1000000。超深 JSON 文档在列表中单独报错，直接打开返回错误；超深轨迹行显示原行号、错误及预览，后续正常行继续显示，不将浏览限制当作证据无效结论。页面不是实时一致快照，不提供编辑、运行按钮、自动复验、目录监控、完整大文件下载、流式全文搜索或跨实验合并。应浏览停止写入后的稳定文件。访问令牌不能代替本机文件权限或保护已被同一用户修改的证据。审查修复与回归见 [记录 021](changes/2026-10-21-021-m5-review-fixes.md)。

## 无模型持续集成

[确定性工作流](../.github/workflows/deterministic.yml) 在 push、pull_request 和手动触发时，使用 Windows runner、Node.js 24 和 Python 3.12，依次运行：

```powershell
npm.cmd run check
npm.cmd test
npm.cmd run test:python
python -m compileall -q dsh_eval test
npm.cmd run demo:eval
```

不安装 Harness 或项目依赖，不配置模型密钥，不执行 `--run`，不上传原始运行目录。测试中的确定性适配器会启动真实 Node / Python 子进程，使用原录制器、inspect 与状态化工具，但不调用模型。`smoke:host`、`check:output` 和真实工具注册 smoke 需要本机的固定 Harness 安装，不属于这个干净环境工作流。

真实模型验收继续使用明确的 `--case / --batch / --experiment ... --run` 命令，预算来自用例 `timeoutSeconds`，调用前需单独选择任务与配置；本批没有新增模型自动工作流，也没有 token / 费用硬限额。工作流权限仅 `contents: read`，checkout 不保留凭据，整项检查上限 15 分钟。

Action 用法核对自官方 [checkout](https://github.com/actions/checkout)、[setup-node](https://github.com/actions/setup-node)、[setup-python](https://github.com/actions/setup-python) 说明。本地检查通过不代表 GitHub 托管运行已通过；本批没有提交、推送或触发云端工作流，首次云端结果需在代码提交后核对。实现与本地验证见 [修改记录 020](changes/2026-10-21-020-m5-results-browser-ci.md)。
