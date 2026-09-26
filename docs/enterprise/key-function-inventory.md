# 关键函数与链路清单（P0）

本表标出核心调用链和基线中可见的文档状态。它不是完整符号表；后续按子系统扩展，并在每个改动批次通过 AST 检查 docstring/JSDoc 覆盖，同时人工确认说明准确。`中文说明`指函数本身的中文文档说明，普通行内中文注释不算。

| 子系统 | 函数/入口 | 文件 | 当前职责 | 当前中文说明状态 / 改造要点 |
|---|---|---|---|---|
| 认证 | `get_user_from_headers` | `packages/dbgpt-serve/src/dbgpt_serve/utils/auth.py` | 从 header 生成 `UserRequest` | 无函数 docstring；现状把可伪造身份设为 admin，P2 必须先替换可信身份解析 |
| Flow 鉴权 | `check_api_key` | `packages/dbgpt-serve/src/dbgpt_serve/flow/api/endpoints.py` | Flow API key 检查 | 有英文 docstring；中文解释默认允许和 `/api/v1` 放行分支并统一授权策略 |
| Flow 写入 | `create`、`update_flow`、`create_and_save_dag` | `packages/dbgpt-serve/src/dbgpt_serve/flow/api/endpoints.py`、`.../flow/service/service.py` | 接受前端 Flow 描述，构造/保存 DAG，并按状态注册 | 服务函数中存在英文说明；为请求字段、保存事务、DAG 构造失败、权限范围补中文说明 |
| Flow 加载 | `load_dag_from_db` | `packages/dbgpt-serve/src/dbgpt_serve/flow/service/service.py` | 服务启动时取出持久化的已发布/运行状态 Flow 并注册 DAG | 英文说明；需说明多实例一致性限制 |
| Flow 执行 | `debug_flow`、`safe_chat_flow`、`safe_chat_stream_flow`、`_get_callable_task` | 同上 | 选取 Flow、构造可调用 DAG task、执行或流式返回 | 逐个补充中文输入/错误/权限/取消行为说明 |
| AWEL Runner | `LocalRunner.execute_workflow`、`_execute_node` | `packages/dbgpt-core/src/dbgpt/core/awel/runner/local_runner.py` | 建立 DAG 上下文并递归/按依赖执行 operator | `execute_workflow` 现有说明以英文为主；中文说明当前本地 runner 的执行顺序、状态、变量与失败传播 |
| SQL 工具 | `make_sql_query` 及闭包 `sql_query` | `packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/tools/sql_query.py` | 构造 Agent 可调用的数据库查询工具 | 中文工具说明和英文函数说明；需描述现有拦截边界，并在统一只读执行器落地后更新 |
| 组织同步 | `read_and_validate`、`preview`、`_unique_ids` | `packages/dbgpt-serve/src/dbgpt_serve/organization_sync/service.py` | 校验外部快照、生成只读计数预览 | 已有中文说明；当前不会写数据库或改变账号授权 |
| 应用装配 | `initialize_serve` / 应用初始化入口 | `packages/dbgpt-app/src/dbgpt_app/initialization/serve_initialization.py` | 注册并装配 Serve 子系统 | 准确函数名和初始化阶段由迁移前源码索引复核；重点追踪包扫描与插件加载 |

## 典型 AWEL 保存和运行调用链

```text
web/components/flow/ 画布和节点表单
  -> Flow API 请求 /api/v1/serve/flow
  -> flow/api/endpoints.py create/update/debug/chat endpoint
  -> flow/service/service.py 构建/保存 Flow 实体与 DAG
  -> 部署状态时 FlowFactory 注册；启动时 load_dag_from_db 恢复注册
  -> service 获取可调用 task
  -> dbgpt.core.awel.runner.LocalRunner.execute_workflow
  -> DAG 上游 operator 按执行规则调用
  -> operator 使用模型、数据库、检索、工具等已注入资源
  -> API 将文本/流式结果返回前端
```

UI 画布展示的节点元数据、前后端 Flow 序列化 schema、Python Operator/OperatorType registry 和运行器需要逐个核对；节点在前端可见不表示服务端已注册，也不表示其执行权限或资源访问安全。P0 只固定主调用路径，P5/P7 再落地发布治理及端到端测试。

## AST 覆盖快照

详见 [`python-function-docstring-baseline.csv`](python-function-docstring-baseline.csv)。总量为 10,778 个 Python 函数/方法，4,509 个没有 docstring；其中只有约 120 个 docstring 带中文字符。统计依赖函数定义计数和 Unicode 字符扫描，不判断说明质量，不覆盖 TypeScript/JSDoc。后续应将“关键函数清单 100% 中文说明”和“全仓函数覆盖率目标”分别验收。
