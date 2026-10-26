# 修改记录 053 外部路由与批次续跑交付状态核对

日期：2026 年 10 月 27 日，Asia/Shanghai。类型：文档。插件版本：`0.1.2`。相关 Git 提交：已核实 `e3dc29a0f7bd3502e070a23ac8ae9d6a4a9883a4`，本验收文档尚未提交。

## 问题与目标

049 至 052 的实现、测试和文档已提交，进度仍保留当时的未提交状态。核对对应提交的 CI，并将实际交付状态与原本地验证、真实模型样本区分。

## 文件修改

| 文件 | 修改前 | 修改后 | 原因 |
| --- | --- | --- | --- |
| 本记录、docs/progress.md、CHANGELOG.md | 缺少对应提交的验收记录 | 保存精确 SHA、run / job / attempt、步骤状态及日志访问限制 | 不把旧提交或本地结果代作当前提交的云端证据 |

## 实现与技术取舍

只读核对 Git HEAD 与 GitHub Actions REST API。没有触发或重跑工作流，也没有运行模型。GitHub CLI 在当前环境不可用，采用相同仓库的公开 API；原始日志与本机检查产物只保存在忽略目录，公开记录使用运行链接和可核对标识。

## 验证

核对时工作区干净，HEAD 为 e3dc29a。实际 API 查询：

```text
GET /repos/1412698607/dsh-eval-lab/actions/runs?head_sha=e3dc29a0f7bd3502e070a23ac8ae9d6a4a9883a4&per_page=10
GET /repos/1412698607/dsh-eval-lab/actions/runs/40357525952/attempts/1/jobs
GET /repos/1412698607/dsh-eval-lab/actions/jobs/121693864714/logs
```

| 对象 | 实际结果 |
| --- | --- |
| [CI run 40357525952](https://github.com/1412698607/dsh-eval-lab/actions/runs/40357525952) | head_sha 精确匹配；attempt=1、completed / success |
| [job 121693864714](https://github.com/1412698607/dsh-eval-lab/actions/runs/40357525952/job/121693864714) | deterministic、相同 head_sha、completed / success |
| JS 语法、Node 回归、Python 回归、Python 编译、合成示例步骤 | API 返回的步骤状态均为 completed / success |
| 原始 job 日志接口 | HTTP 403，未读取云端测试输出和具体数量 |

因此本记录确认提交级 CI 状态与各步骤通过，不将 052 本地的 271 Python / 87 Node / 43 JS 数量升级为已读取的云端日志事实。既有 050 四个实际模型任务和失败停止结果保留，没有新模型任务。

## 风险与后续

日志访问限制使云端具体测试数量仍未核对。当前新增 [054 实验续跑预检](2026-10-27-054-experiment-resume-preflight.md) 在上述提交之后实施，其本地结果和未来提交的 CI 必须独立记录。

## 文档同步

更新进度当前基线与 CHANGELOG；049–052 的历史验证与当时状态不覆盖。
