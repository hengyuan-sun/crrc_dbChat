# 关键函数与链路清单

本表记录已检查的代表性核心链路，不是全仓完整符号表。`中文说明`指函数定义处的中文 docstring/JSDoc；普通行内中文注释不算。补充说明后还要人工核对与实现一致，并用执行用例验证行为。

| 子系统 | 函数/入口 | 文件 | 当前职责 | 当前中文说明状态 / 未完成项 |
|---|---|---|---|---|
| 身份 | `get_user_from_headers` | `packages/dbgpt-serve/src/dbgpt_serve/utils/auth.py` | 从 header 生成 `UserRequest` | 已说明现状和安全边界：请求方可伪造 user ID 并得到 admin；缺 header 返回固定 `001/admin`。待 P2 替换可信身份解析行为 |
| Flow API Key | `check_api_key` | `packages/dbgpt-serve/src/dbgpt_serve/flow/api/endpoints.py` | 检查 Flow 服务 API Key | 已说明 `/api/v1` 路径放行、未配置密钥时全放行；待统一认证/默认拒绝与资源授权 |
| Flow API | `create`、`debug_flow` | `packages/dbgpt-serve/src/dbgpt_serve/flow/api/endpoints.py` | 接收画布 Flow 或临时 DAG 并调用服务 | 已说明输入、SSE 返回及当前未绑定可信主体、未限制调试节点的安全边界 |
| Flow 写入 | `Service.create`、`update_flow`、`create_and_save_dag` | `packages/dbgpt-serve/src/dbgpt_serve/flow/service/service.py` | DAO 写入、DAG 构造/替换、注册和错误处理 | 已加中文说明；`Service.create` 曾只含 docstring、未委托 DAO，现已改为调用基类实现；对应回归用例因缺少 `sqlalchemy` 未运行 |
| Flow 恢复 | `load_dag_from_db` | 同上 | 启动时重建满足状态条件的 JSON Flow 并注册本地 DAG | 已说明逐条加载/更新及异常处理；尚无 workspace filter、跨进程一致性和不可变 release |
| Flow 调用 | `safe_chat_flow`、`safe_chat_stream_flow`、`_get_callable_task`、`Service.debug_flow` | 同上 | 解析已注册叶子节点，执行对话或临时 DAG 调试 | 已加中文输入/输出/异常和授权边界说明；workspace ACL、发布审批、节点 allowlist 与取消治理未实现 |
| AWEL Runner | `DefaultWorkflowRunner.execute_workflow`、`_execute_node`、`_skip_current_downstream_by_node_name` | `packages/dbgpt-core/src/dbgpt/core/awel/runner/local_runner.py` | 建立 DAGContext，顺序递归执行依赖、缓存任务输出并传播分支跳过 | 已说明执行顺序、状态、变量、失败和日志副作用；不提供持久队列/跨进程调度/重试/取消恢复 |
| SQL Tool | `make_sql_query` 与闭包 `sql_query` | `packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/tools/sql_query.py` | 创建并执行 Agent 数据库查询工具 | 已说明关键字前缀检查与执行后裁剪的局限；共享 SQL 策略、执行侧行数/超时和 DB 只读权限尚未落地 |
| 组织同步 | `read_and_validate`、`preview`、`_unique_ids` | `packages/dbgpt-serve/src/dbgpt_serve/organization_sync/service.py` | 校验外部快照并生成只读数量预览 | 已补中文参数/返回/异常/副作用边界；树环/跨组织校验、持久化提交、审批、审计和撤权传播未实现 |
| 应用装配 | `initialize_serve` / Serve 初始化入口 | `packages/dbgpt-app/src/dbgpt_app/initialization/serve_initialization.py` | 注册并装配 Serve 子系统 | 具体导出函数与插件扫描调用关系待源码索引复核；中文说明审查尚未开始 |

## AWEL 画布保存和运行链

```text
web/components/flow/ 画布、节点面板和表单
  -> Flow API /api/v1/serve/flow（新建、更新、调试、聊天等路由）
  -> flow/api/endpoints.py 校验请求并分发到 Service
  -> flow/service/service.py 从 JSON 构图、DAO 持久化、按状态注册 DAG
  -> 启动时 load_dag_from_db 从 DAO 重建当前进程中的已运行 DAG
  -> chat/debug 路径解析 DAG 叶子节点
  -> DefaultWorkflowRunner.execute_workflow 创建/复用 DAGContext
  -> _execute_node 顺序运行上游 operator，再运行目标节点
  -> operator 调用已注入的模型、数据库、检索或工具资源
  -> API 把文本/流式输出包装为 JSON 或 SSE 返回前端
```

UI 画布可见一个节点不代表后端已注册、可安全加载或有执行权限。当前 runner 在本进程递归执行；当前服务部署状态与进程内 registry 耦合。服务/DAO 权限、operator allowlist、不可变版本与 worker 持久任务需要单独实施。

## AST 覆盖快照

详见 [`python-function-docstring-baseline.csv`](python-function-docstring-baseline.csv)，这是本批关键中文说明补充之前的快照：10,778 个 Python 函数/方法中，4,509 个无 docstring，约 120 个 docstring 含中文。字符统计不判断说明质量，也不覆盖 TypeScript/JSDoc。关键函数逐项覆盖与全仓函数覆盖率须分别验收。
