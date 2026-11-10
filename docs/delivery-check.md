# 固定合成交付检查

当前候选源码提供 `check:delivery`，需要Python3.12+、Node.js22.8+，不安装Harness、不配置模型密钥、不调用模型。

```powershell
npm.cmd run check:delivery
# 可指定尚不存在的目录：
npm.cmd run check:delivery -- --output-dir runs/delivery-review
# 同一入口的Python形式：
python -m dsh_eval.delivery_check
```

默认在 `runs/delivery-check/<uuid>/` 新建输出，已有叶路径（包括悬空链接）不覆盖。检查只移动本次新生成输出目录内的workflow-source和目录包，每次移动前核对解析后的源 / 目标仍在本次目录内，不移动用户已有归档。

流程依次生成工作流和基线比较示例，核对预设0 / 1 / 2；导出普通四样本工作流实验及其报告 / 规则预览，将原源目录和包实际搬迁，再在原源不可用时核验目录包、在包外重评四个样本。退休源、独立基线比较源及包内文件字节保持。原源不再可用是本次测试的设计，退休源路径保留用于字节核对；后续浏览分别选择regression-source或relocated/package作为结果根。

浏览检查通过ArtifactBrowser读取关联，再对比较根和包根分别执行catalog / 指定文档的两次真实HTTP请求；更深评测 / 证据 / 轨迹关联通过API读取。这不是实际前端点击验收。所有连接、服务线程和套接字在finally收尾；检查自建服务使用非守护请求线程，由server_close实际等待请求线程结束，另行回收serve_forever线程。关闭后的连接探针超时不当作关闭证明；正常与错误请求收尾回归见[139](changes/2026-11-11-139-baseline-delivery-review.md)。

结果保存在 `delivery-result.json`，文件摘要在 `delivery-sha256.json`。成功退出0只表示这些预设检查完成，不表示所有演示任务通过或模型表现可靠；正常反例仍保留失败 / 不可评。归档verify仅文件与依赖核验，包外新报告才执行fresh inspect及断言。输入 / 执行错误退出2，中断退出130，失败可能保留本次未完成输出。

命令本身不执行git clone / checkout，也不认证源码版本。在干净已提交版本运行、在当前候选文件复制导出中运行，属于不同证据。[138](changes/2026-11-11-138-synthetic-delivery-check.md)分别验证HEAD `1717cc9`的338文件Git导出与包含未提交B/C的344文件公开候选；前者只运行其已有CLI，不包含新检查器或B。138的候选在原仓库之外运行新npm入口，模块ROOT、源码清单、原门禁及搬迁后四样本核对通过，当时完整672项Python / 164项Node回归通过。这些结果属于139修复前快照，修复后的当前回归及交付另见[139](changes/2026-11-11-139-baseline-delivery-review.md)，不沿用旧清单声称新代码字节匹配。

在新检出源码中复现时，先确认需要验证的Git提交及工作区状态，再运行上述命令。若有未提交修改，结果只能描述对应候选快照，不能自动升级为已提交版本验收。文件清单核对源码字节，运行生成的Python缓存不算源码；文档随后补记结果时，运行代码 / 测试 / 配置仍需与已验快照匹配。

B/C尚未提交，新云端交付步骤及摘要网页渲染均未验证。输出包含原始合成内容，保留在忽略目录，不自动上传；CI仍只上传原先五份基线比较文件。
