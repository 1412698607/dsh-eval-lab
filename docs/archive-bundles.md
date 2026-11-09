# 可迁移的只读实验归档包

目录包保存一份明确选择的实验或续跑链，以及选定报告、规则预览、逐样本对照的必要依赖。原文件逐字节复制到 payload，原运行身份、录制摘要、领取记录和历史计划指纹不改写。换目录后可核验清单、重新生成报告和浏览原事件，不需要原目录存在，不调用模型。

本版是目录交付包，包含原始任务与轨迹内容，沿用 runs 忽略规则，不自动上传。它用于离线分析，不是完整宿主 / 会话备份或确定性重放，也不提供搬迁后的续跑规划与执行。

## 导出与搬迁

需要 Python 3.12+；重新评测还需要 PATH 中的 Node.js 22.8+。以下路径替换为已保存的实际实验和报告：

```powershell
python -m dsh_eval.archive_bundle export --entry runs/experiments/<实验ID>/experiment-result.json --source-root runs --output runs/packages/example
# 可以重复 --include，只加入与所选实验或显式祖先链关联的产物：
python -m dsh_eval.archive_bundle export --entry runs/experiments/<实验ID>/experiment-result.json --source-root runs --output runs/packages/with-report --include runs/reports/<报告ID>/report.json
```

--entry 支持普通终态实验及显式选择的实验续跑结果。--source-root 是用户明确授予读取的共同来源目录，所有必要引用都须在其中；不会搜索其他磁盘位置。若还包含保存在其他目录的派生报告、候选用例或规则映射，应选择能够包含这些明确依赖的共同根。不会整树复制这个根。

--include 支持 report.json、assertion-comparison.json、experiment-assertion-preview.json，文件名可按实际保存值指定。报告须来自所选实验或显式祖先；对照须绑定选定样本的原 case / evidence；实验规则预览仍只支持已完成普通实验，不为续跑新增预览能力。依赖缺失、身份或规范关联不符、原路径越界时拒绝。

输出必须是尚不存在的目录，并且位于所选实验、续跑、任务、录制和报告目录之外，避免改变原归档的目录布局。创建失败不覆盖已有内容；导出失败可能保留未完成目录，但最后的 archive-manifest.json 尚未发布。

```text
archive-manifest.json
payload/
  <原来源根下的相对目录与原文件>
```

整个目录可以复制或搬到新位置。本工具不会为读取搬迁后的包而回退访问原目录。

## 核验、重新评测和浏览

```powershell
python -m dsh_eval.archive_bundle verify runs/packages/example
python -m dsh_eval --report runs/packages/example/archive-manifest.json --reports-root runs/rechecked-reports
python -m dsh_eval --browse --runs-root runs/packages/example
```

verify 核对清单、所有成员的大小 / SHA-256、精确依赖闭包，以及原冻结输入、续跑身份与指纹绑定，返回 taskEvaluationPerformed=false。它没有执行 Node inspect 或任务断言，不能把 verified 当作任务通过。

--report 可以选择包目录或 archive-manifest.json。它先核验包，再使用现有评分器执行 fresh inspect 和逐项断言；新的报告、原因摘要和评测写入包外的新 UUID 目录。--reports-root 位于包内时拒绝。新报告保留归档来源信息，已知关联路径使用当前包内位置，历史路径字符串只用于原身份和指纹校验。

浏览时显式选择包根，页面提供“归档包”索引、主入口和选定产物；原报告 / 预览 / 对照及任务原事件均通过清单映射定位。启动时核对清单与成员，打开成员时再次核对清单和该文件摘要；浏览仍只显示保存结论，不重新评分。缺失、额外成员、篡改、未列明原路径和链接 / junction 都拒绝，不修补旧文件。嵌套在普通 runs 根下的包不自动启用映射，应明确把该包设为 --runs-root。

报告生成后可按普通报告方式浏览新报告，配置根须同时覆盖新报告与其包内源文件。新报告位于包外，其自身不是原清单成员；再次搬迁时，原目录包仍可独立核验和重新生成报告。

前台服务输出带令牌的完整 URL，按 Ctrl+C 停止。关闭页面不会停止服务。export / verify 成功退出 0，输入、范围、完整性或输出错误退出 2；--report 的退出语义沿用普通报告，成功生成不等于全部样本通过。

## 清单与只读路径映射

archiveBundleFormatVersion=1 保存 archiveId、createdAt、logicalSourceRoot、entryPath、artifacts、files 和 modelCalled=false。entryPath 及 artifacts[].path 指向 payload 下的相对 POSIX 路径；artifacts 包含主入口和明确选定的派生产物。每个 files 条目保存 path、size 和 sha256。根目录只允许清单与 payload，payload 文件和目录均须与清单派生集合完全一致。

只复制分析需要的冻结清单 / 输入、显式续跑计划 / 领取记录、case / evidence / runtime / evaluation、平面录制清单 / JSONL / 状态，以及选定产物的必要候选与规则文件。home、workspace、node_modules、私人目录、凭据及普通 stdout / stderr 日志不作为依赖复制；必要的 .batch-resume-claim.json 是唯一允许的隐藏领取文件。活动、临时或不受支持的依赖可能被拒绝，应选择停止写入后的稳定归档。

原绝对路径是历史逻辑别名。ArchivePaths 只把这个前缀映射到当前 payload 中的已列明文件及祖先目录；未列明引用即使原文件仍存在也不回退读取。logical_str 在原校验中还原原路径字符串，保持历史摘要载荷不变；physical 用于包内读取。上下文退出后恢复普通行为，续跑规划和执行入口在此上下文内明确拒绝。HTTP 浏览器持有自己的显式映射，避免线程继承问题。

导出先核对源冻结绑定，再记录源摘要、复制及核对原字节，重新验证复制后的语义和闭包，最后发布清单。重评绑定首次验证的清单字节，并在输出前复核文件；这些检查不提供多文件事务、签名、fsync 或断电恢复保证，清单与全部数据共同改写不在摘要保证内。本轮验证限定 Windows 当前 Python / Node 环境，不推广为跨操作系统兼容。
