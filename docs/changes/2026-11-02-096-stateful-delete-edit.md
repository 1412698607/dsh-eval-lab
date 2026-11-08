# 修改记录 096 受控删除与精确文本编辑

日期：2026 年 11 月 2 日，Asia/Shanghai。类型：功能 / 测试 / 文档。插件版本：0.1.2。相关 Git 提交：本批尚未提交；基线 115c670 已存在并核实，包含已提交推送的 094–095。该提交远端 CI 尚未核实。

## 问题与目标

094 已提供虚拟文件整体写入与工具期限，095 另完成单个真实写入任务。受控工具仍不能删除文件或只修改指定片段，无法区分完整覆盖与精确编辑，也没有覆盖删除不存在文件、歧义编辑或这些操作的超时恢复。

本批在相同 Python 环境与 JavaScript 桥接中增加显式 eval_delete / eval_edit，沿用最终状态、工具期限和续跑核验。正常修改、预期错误及双工具超时分别成为三份新用例，不修改旧 core 固定集或历史模型证据。

## 文件修改

| 文件 | 修改前 | 修改后 / 原因 |
| --- | --- | --- |
| [environment.py](../../dsh_eval/environment.py) | read / list / write | 新增单文件删除、提交时唯一精确匹配编辑，普通错误不修改状态 |
| [formats.py](../../dsh_eval/formats.py) | 三种可选受控工具 | 增加两种显式工具名，复用对应工具的延迟 / 期限校验 |
| [tool-bridge.js](../../scripts/lib/tool-bridge.js) | 注册读取、列举与写入 | 增加删除 / 编辑的描述和各自参数 schema，默认仍只注册 read / list |
| [edit-delete.case.json](../../fixtures/evaluation/edit-delete.case.json)、[edit-delete-errors.case.json](../../fixtures/evaluation/edit-delete-errors.case.json)、[edit-delete-timeout.case.json](../../fixtures/evaluation/edit-delete-timeout.case.json) | 无对应操作用例 | 正常修改、缺失 / 歧义拒绝、两种工具分别超时重试，均声明完整最终状态 |
| [mutation-adapter.js](../../scripts/fixtures/mutation-adapter.js)、[test_stateful_mutations.py](../../test/test_stateful_mutations.py) | 无对应合成执行链路 | 固定操作脚本经真实管道 / 录制器进入评测、续跑和报告，答案不从断言读取 |
| [tool-bridge.test.js](../../test/tool-bridge.test.js) | 原写入与响应回归 | 增加启用 / 参数形状和普通工具错误后桥接仍可使用的回归 |
| [smoke_bridge.py](../../scripts/smoke_bridge.py)、[smoke-bridge.js](../../scripts/smoke-bridge.js) | 读取 / 写入组件模式 | 增加互斥 --mutations 模式，真实 Cordis 注册 / IPC 验证状态、超时和取消 |

## 实现与技术取舍

- delete 只接受 path，删除一个已有虚拟文件，返回 `DELETED: <path>`。缺失文件或目录（含 `.`）返回 NOT_FOUND，不递归，也不提供 force。新 requestId 重复删除已消失文件会失败；相同 requestId 返回原缓存响应，即使原路径已被重新创建，也不会再次删除。
- edit 接受 path / oldText / newText 字符串。文件缺失为 NOT_FOUND；空 oldText 为 EMPTY_EDIT_TARGET；原文无匹配为 TEXT_NOT_FOUND；多起点匹配为 AMBIGUOUS_MATCH，包含 `aaa` 中 `aa` 的重叠匹配。只有唯一匹配才拼接替换文本；允许空 newText 删除片段或相同新旧文本的无变化操作。保持 Unicode、换行、其他内容及其他文件，不引入正则 / 模糊匹配。
- 原文匹配发生于提交时，延迟期间文件变化会影响匹配结果，不复用过期位置。删除 / 编辑不消耗读取故障计数；删除后重建仍保留该路径剩余故障次数，每次用例才重置环境。
- 不新建调度器：沿用 submit / poll 在到期检查后提交内存修改，工具超时、已处理的单请求取消和任务收尾移除未提交操作。已提交操作不回滚；没有事务或外部系统恰好一次保证。
- 版本 2 stateful.tools 显式启用新工具，旧工具默认集合、case / evidence / bridge / snapshot 版本均不变。最终文件集合中的缺失与剩余内容由原 environment_files 比较；报告与续跑仍按原冻结输入、身份和摘要核验。
- Python 测试用例的工具延迟缩短为 200 / 0 ms、期限 100 ms，以缩短无模型回归；公开 timeout 用例和真实组件检查仍使用两工具各 1500 / 0 ms、期限 1000 ms。合成脚本固定发出调用，不证明模型自行选择工具的能力。

## 验证

Windows，沿用当前 Node.js v24.14.0 / Python 3.12.0；真实组件为当前固定 CLI / SessionStore 0.2.0-rc.2、Cordis 4.0.4。所有本批检查均无模型调用。

| 命令或操作 | 实际结果 | 范围 |
| --- | --- | --- |
| `python -m unittest discover -s test -p test_stateful_mutations.py -v` | 13 项通过，2.861 秒 | 精确匹配、空替换、重叠歧义、缺失 / 非法路径、非递归删除、重复请求不二次修改重建文件、环境重置、超时 / 取消、提交时状态、三份用例录制与续跑报告 |
| `node --test --test-isolation=none test/tool-bridge.test.js` | 8 项通过 | 显式注册、参数 schema 和普通错误后桥接可用 |
| `npm.cmd run test:python` | 完整 476 项通过，293.742 秒 | 最终代码的全部 Python 回归，真实子进程环境，无模型调用 |
| `npm.cmd test` | 完整 121 项通过，7.065 秒 | 新增两项回归及既有 Node 测试，包含真实子进程生命周期 |
| `python -m scripts.smoke_bridge --mutations` | passed，15 请求 | 实际 Cordis / Tools 注册、fork IPC；编辑 / 删除超时前后读回、重试成功、单独取消后状态不变、歧义 / 缺失错误后仍可读 |
| `python -m scripts.smoke_bridge --writes` | passed，六请求 | 原写入、超时恢复和取消组件链路仍通过 |
| `npm.cmd run check`；`python -m compileall -q dsh_eval scripts test` | 45 个 JavaScript 文件及 Python 编译通过 | 语法检查 |

完整 `npm.cmd run test:python` 通过 476 项，293.742 秒，零失败 / 错误；覆盖本批最终实现，没有全量运行后的生产代码调整。最终 9 份文档 / 549 个相对文件链接目标检查通过，三份公开用例 validate_case 通过（分别 8 / 7 / 10 条断言），`git diff --check` 通过。实际过程未出现定向或全量失败；094–095 的历史失败、验证与模型样本不改写，不继承远端 CI。

## 风险与后续

只支持内存虚拟文件，不对宿主文件做删除或编辑；不提供目录删除、重命名、批量替换、外部异步工具、事务回滚或跨进程持久化幂等。空目标 / 歧义是可恢复工具错误，协议类型或字段错误继续按原桥接规则处理。

三份新用例尚未执行真实模型任务，095 的真实写入不能作为删除 / 编辑的模型验收。后续可在独立新运行中验收这些用例，再决定其他状态操作或外部工具范围。本批未提交 / 推送或新增 CI。

## 文档同步

同步 README、CHANGELOG、progress、architecture、evaluation-format、stateful-tools、M6 方案和用例目录说明。当前基线更新为实际 115c670，保留 094–095 当时的未提交状态与验证范围；公开文档不依赖原始 runs 日志。
