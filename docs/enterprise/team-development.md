# 团队协作与代码边界

本文描述当前迁移阶段适用的协作方式。模块负责人是职责角色，不代表已经分配了具体人员；账号和 GitHub 团队名必须由项目维护者确认后配置。

## 模块负责人角色

| 代码边界 | 负责人角色 | 主要输入/输出契约 | 评审重点 |
|---|---|---|---|
| `packages/dbgpt-serve/src/dbgpt_serve/utils/auth.py` 与拟新增企业身份/授权模块 | 身份与组织负责人 | 身份断言、RequestContext、成员/角色与授权决策 | 可信身份来源、默认拒绝、workspace 约束、撤权传播 |
| `packages/dbgpt-serve/src/dbgpt_serve/organization_sync/` | 组织目录负责人 | 稳定外部 ID、完整/增量快照、校验结果、同步批次回执 | 幂等、事务、树关系校验、预览/提交/审计分界 |
| `packages/dbgpt-serve/src/dbgpt_serve/agent/`、`packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/tools/` 及工具注册边界 | Agent 与工具负责人 | Agent 请求、工具 schema、执行结果及错误契约 | 工具 allowlist、主体/workspace 传递、超时、副作用和脱敏 |
| `packages/dbgpt-core/src/dbgpt/core/awel/`、`packages/dbgpt-serve/src/dbgpt_serve/flow/`、`web/components/flow/` | 工作流负责人 | Flow JSON/schema、operator registry、revision/release/run | 前后端 schema 一致、节点白名单、执行版本固定、并发与取消 |
| `packages/dbgpt-serve/src/dbgpt_serve/rag/`、`packages/dbgpt-ext/src/dbgpt_ext/rag/` 和语义目录 | RAG 与语义负责人 | 文档/切片 ACL、embedding 维度、指标版本、SQL 策略输入 | 召回前授权、删除传播、指标可追溯、SQL 执行边界 |
| `packages/dbgpt-ext/src/dbgpt_ext/llms/`、`packages/dbgpt-serve/src/dbgpt_serve/model/` 与模型代理配置 | 模型负责人 | 内网模型端点、任务能力、版本/维度与健康状态 | 无公网 fallback、工件校验、流式中断和并发评测 |
| `web/` | 前端负责人 | API 类型、页面状态、品牌配置和静态资源 | 授权失败展示、敏感缓存清理、离线静态资源与浏览器验证 |
| `docker/`、`configs/`、`scripts/`、`.github/workflows/` | 平台与发布负责人 | 镜像/依赖 manifest、安装升级配置、健康检查和回退步骤 | digest 固定、离线可复现、不覆盖持久卷、凭据不入库 |
| `docs/enterprise/`、黄金集和验收报告 | QA/业务数据负责人 | 业务期望值、风险场景、验收证据 | 输入可复现、结果由业务确认、失败项有负责人 |

上表路径是当前仓库路径映射。Python 内部命名空间仍处于分阶段迁移；重命名前先修改本表和 ADR，不允许并行批量替换 import 与插件字符串。

## 跨模块接口约定

接口和事件契约需要进入可版本控制的 schema/模型及其契约测试，至少包含字段、可空性、身份/workspace 上下文、错误语义、幂等键、兼容窗口和版本。数据库 schema 变化同时提供迁移前置检查、正向迁移、回滚/恢复策略与数据校验。节点类型、反射类路径和持久化枚举属于兼容契约，必须维护集中映射及历史数据迁移，不以数据库中的旧字符串临时 `import` 旧模块。

跨服务异步任务携带可信的 actor/workspace/授权版本及 trace ID；worker 在执行时重新校验资源和授权状态。缓存 key 包含授权范围和内容版本。Agent、AWEL、RAG 和 SQL 使用相同的身份上下文传递约定，避免各自创建不一致的用户身份。

## 并行与集成顺序

1. 集成人先确认任务卡、文件所有权、API/schema/数据迁移契约及验收用例。
2. 可并行工作限于接口已冻结且目录不重叠的模块。更新共享锁文件、迁移序号、前后端 Flow schema 或节点注册表的改动串行集成。
3. 每个 PR 完成模块内验证后合入集成分支；身份/授权服务先于页面权限 UI，模型接口先于模型选择 UI，Flow 版本/发布服务先于发布界面。
4. 集成者运行跨模块检查，修复冲突并记录失败；不把“可合并”当作“功能验收通过”。阶段性发布需保留可回滚镜像、配置和数据库恢复步骤。

## PR 审查清单

- 行为和依赖是否只在描述的边界内改变？对外 API、数据库、JSON、缓存键和命令兼容性如何？
- 权限是否在服务/DAO/worker 执行点检查，且作用到 workspace/resource？隐藏按钮不算授权。
- 事务、重试、幂等、副作用、取消、超时和失败恢复是否有明确语义？
- 新增函数是否有准确中文 docstring/JSDoc，关键函数清单是否更新？
- 用户输入是否经过校验，日志和错误是否脱敏，任意代码/模块/URL 是否被约束？
- 是否新增公网依赖、自动下载、CDN 或云端 fallback？其离线制品和校验方式是什么？
- 测试是否覆盖成功、拒绝、跨 workspace、失败/恢复路径？实际运行的命令和结果是否提供？
- 迁移是否先备份、可重跑、能中止，是否验证旧持久数据和恢复流程？

## 任务卡与交接

```text
任务 ID / 负责人角色：
业务目标与不做事项：
负责目录与禁止并行修改的文件：
输入/输出 API、事件和数据契约：
依赖任务及集成顺序：
关键函数中文说明与文档更新：
验收用例（成功/权限拒绝/异常/恢复）：
数据迁移、备份及回退方案：
实际验证命令和结果：
PR/提交与待办：
```

GitHub 账号、审批团队、分支保护规则尚未由用户提供或由远端管理员确认。因此 CODEOWNERS 只能使用 `.github/CODEOWNERS.template` 作为配置模板，不能填入虚构账号或把模板当作有效审查规则。
