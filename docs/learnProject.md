# DB-GPT 项目学习手册

本文按当前仓库 `0.8.2` 代码组织方式说明 DB-GPT 的模块边界、启动与调用路径、Agent 执行机制、数据语义构建，以及本机 Docker 部署。它面向需要读代码、二次开发和排查运行问题的开发者；描述以仓库中的实现为准，和概念性产品介绍有差异时优先看具体代码。

企业二开规划见 [单企业完全离线内网方案](enterprise/README.md)、[实施计划](enterprise/implementation-plan.md) 和 [完整开发提示词](enterprise/development-prompts.md)。后续企业目标已确认为完全离线；本文第 2 节记录的阿里云配置是此前开发部署状态，不是企业生产方案。

## 1. 项目定位与版本

DB-GPT 是以 Python 为主的 AI 数据应用平台：它把模型服务、数据源连接、知识检索、聊天场景、Agent 编排和应用 API 放到同一运行时中。仓库使用 uv workspace 管理多个 Python 包；前端在 `web/`，文档站点在 `docs/`。

根目录 `pyproject.toml` 将工作区拆分为 `dbgpt-app`、`dbgpt-core`、`dbgpt-serve`、`dbgpt-ext`、`dbgpt-client`、`dbgpt-sandbox` 和 accelerator 包。主要职责如下：

| 层 | 代码位置 | 主要职责 |
|---|---|---|
| 应用入口 | `packages/dbgpt-app` | CLI、Web 服务启动、API、聊天场景、初始化和静态前端 |
| 核心框架 | `packages/dbgpt-core` | `SystemApp` 组件生命周期、Agent 基础类型、模型接口、AWEL、数据源抽象、RAG 抽象 |
| 服务实现 | `packages/dbgpt-serve` | 数据源、Agent 应用、会话、知识库、提示词、模型等管理 API 和持久化服务 |
| 扩展实现 | `packages/dbgpt-ext` | 具体模型/数据库集成、向量存储、文档处理、schema assembler 与 retriever |
| 浏览器界面 | `web` | 管理控制台和聊天 UI；通过后端 API 使用平台能力 |
| 示例与技能 | `examples`、`skills` | 可复用的 Agent 技能、示例数据和应用参考 |

组件不是一个简单的“聊天 API”：`SystemApp` 在启动时装配配置、服务组件、模型 worker、DAO、存储和路由；场景层将一次用户请求变成 prompt/model request；核心模型客户端通过 worker 访问本地或代理模型。

## 2. 本机部署结论

当前电脑环境：Windows 11 64 位，AMD Ryzen 9 8945HX（16 核 / 32 线程），32 GB 内存，NVIDIA GeForce RTX 5060 Laptop GPU（约 8 GB 显存），Docker Desktop Linux 引擎可运行。项目源码部署指南对本地模型给出 24 GB 显存建议，因此本机更适合 Docker 中运行 DB-GPT、通过云端 API 调用模型。

本仓库 Compose 启动两个容器：MySQL 8.0.32 和 DB-GPT Web 服务。Web 服务端口为 `5670`，MySQL 为 `3306`；两者只绑定到本机回环地址。数据分别保存在 Docker 命名卷中，容器重建不会清空卷。

执行部署时 Docker Desktop 已启动，镜像已拉取，Compose 已建立容器。目标配置文件为 `configs/dbgpt-proxy-tongyi-mysql.toml`，模型提供方是阿里云百炼兼容接口。聊天模型和 embedding 模型的 `api_key` 当前是醒目的 `DASHSCOPE_API_KEY_REQUIRED` 占位值，用于让无密钥时 Web 服务保持启动；模型推理与 embedding 请求在密钥配置前不会成功。接入时在该文件的 `[[models.llms]]` 与 `[[models.embeddings]]` 中分别替换为有效阿里云 API key。密钥不要提交到版本库。

启动/查看/停止命令（在仓库根目录执行）：

```powershell
docker compose up -d
docker compose ps
docker compose logs -f webserver
docker compose down
```

访问入口：<http://localhost:5670>。Compose 使用的 MySQL 初始凭据来自仓库示例配置，部署到共享或公网环境前必须更换。该 Compose 是单机开发部署，不包含 TLS、外部身份认证、备份或高可用配置。

> 容器启动成功只说明 Web/数据库服务已启动，不代表阿里云模型鉴权和推理已成功。API key 尚未配置时，模型请求会失败；填入有效密钥后再验证一次对话和 embedding 请求。

## 3. 启动过程与依赖注入

### 3.1 配置到服务

`dbgpt start webserver --config <toml>` 是 CLI 启动路径。配置文件决定 Web 监听端口、元数据库、模型列表、向量存储和可选服务。`dbgpt-app` 的 `dbgpt_server.py` 创建并初始化 `SystemApp`，然后注册/启动各服务；服务通过 `SystemApp` 注册组件并在需要时由组件名或 `ComponentType` 获取依赖。

概念上的启动顺序：

```text
CLI 参数与 TOML
  -> Config / 应用配置
  -> SystemApp 与服务组件注册
  -> 元数据库与 DAO 初始化
  -> 模型 worker / embedding factory / 向量存储配置
  -> FastAPI 路由注册
  -> Web 服务开始接收请求
```

容器镜像内提供 `dbgpt` CLI 与 Python 运行环境，故 Windows 主机不需要直接安装该仓库的 Python 依赖。仓库的 `pyproject.toml` 要求 Python >= 3.10；当前主机 Python 3.14.6 并非本次部署使用的运行时。

### 3.2 数据保存位置

| 数据 | 保存位置 |
|---|---|
| DB-GPT 服务表、会话/数据源配置 | MySQL `dbgpt` 数据库 |
| 向量索引及本地文件数据 | Compose `dbgpt-data` 卷（映射至容器 `/app/pilot/data`） |
| 消息数据 | Compose `dbgpt-message` 卷（映射至 `/app/pilot/message`） |
| MySQL 数据文件 | Compose `dbgpt-myql-db` 卷（仓库现有卷名拼写如此） |

Compose 将 `configs/` 映射为容器内 `/app/configs`，因此更新 TOML 后需要重启 Web 容器使其重新加载。Docker 命名卷应通过数据库备份和 `docker volume` 备份策略保护；不要用 `docker compose down -v` 做普通重启。

## 4. 统一聊天 API 与场景分派

### 4.1 普通聊天总链路

核心入口是 `packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/api_v1.py` 的 `POST /api/v1/chat/completions`。请求中的 `chat_mode`、`select_param`、`model_name`、`app_code`、`user_input` 等字段决定后续路径。

普通场景调用路径：

```text
POST /api/v1/chat/completions
  -> 适配请求、解析 chat_mode / domain_type
  -> get_chat_instance(dialogue)
  -> CHAT_FACTORY.get_implementation(chat_mode)
  -> BaseChat 子类初始化（场景 prompt、会话、模型 worker）
  -> BaseChat.stream_call()
  -> prepare_input_values() / generate_input_values()
  -> AppChatComposerOperator 组装历史消息与 prompt
  -> ModelRequest
  -> build_cached_chat_operator(...).call_stream(call_data=...)
  -> DefaultLLMClient -> worker -> provider/model endpoint
  -> 场景 OutputParser 解析增量输出
  -> stream_generator 编码为 SSE/文本流并写回会话
```

`BaseChat` 负责通用的提示词变量、历史消息、温度和 token 参数、模型请求、流式输出解析及会话保存。各个场景覆盖 `generate_input_values()`、`do_action()` 或输出解析器，插入自己的数据准备与动作执行逻辑。LLM 调用抽象成 worker/client/operator，因而场景不需要直接依赖某个厂商 SDK。

### 4.2 典型场景分支

| 场景 | 请求特点 | 主要实现 |
|---|---|---|
| 常规对话 | 普通 prompt + 对话历史 | `scene/chat_normal/` 与 `BaseChat` |
| Chat DB 自动执行 | `select_param` 为数据库名；先选相关 schema，再生成 SQL 并执行 | `scene/chat_db/auto_execute/` |
| Chat DB 专业问答 | 面向 DBA/数据库概念的问答 prompt | `scene/chat_db/professional_qa/` |
| 知识库问答 | 选择知识空间，召回相关文档作为上下文 | `scene/chat_knowledge/`、RAG retriever |
| 文件/表格分析 | 文件读取、问题规划、SQL/Python 或分析工具 | `scene/chat_data/`、`openapi/api_v1/agentic_data_api.py` |
| Agent 应用 | 按 `app_code` 载入 Agent 团队或 AWEL Flow | `dbgpt_serve/agent/agents/controller.py` |
| AWEL Flow | 请求转成 Flow 输入，执行保存的 DAG | `FlowService.chat_stream_flow_str()` 与 AWEL operators |

此外 `/api/v1/chat/react-agent` 是 Agentic Data API 的独立入口，不等同于 chat mode=`chat_agent`。前者是围绕分析工具、skills 和文件/数据操作的 ReAct 工作流；后者通过 Agent 应用控制器运行已定义团队或 AWEL Flow。

### 4.3 Chat DB：自然语言到 SQL

自动执行场景的调用链：

```text
POST /api/v1/chat/completions (chat_mode=chat_with_db_execute)
  -> get_chat_instance -> CHAT_FACTORY -> ChatWithDbAutoExecute
  -> ConnectorManager.get_connector(db_name)
  -> generate_input_values()
      -> DBSummaryClient.get_db_summary(query, top_k)
      -> DBSchemaRetriever 查找相关表/字段文档
      -> 失败时退回 connector.table_simple_info()
  -> prompt 带上方言、schema、问题、结果展示类型
  -> LLM 返回 thoughts / direct_response / sql / display_type JSON
  -> DbChatOutputParser 分析 SQL 与最终展示约定
  -> do_action -> connector.run_to_df 执行查询
  -> 输出表格/图表数据和文本流
```

代码路径集中在 `scene/chat_db/auto_execute/chat.py` 和 `prompt.py`。仅仅把 schema 发给模型不能保证 SQL 正确；数据库用户权限、生成 SQL 的限制、执行错误恢复和结果解释都影响安全与准确性。连接生产数据时建议为 DB-GPT 使用只读数据库账号，并在目标数据库启用资源/查询限制。

## 5. Agent 的搭建与运行

### 5.1 Agent 组成

Agent 能力分布于 `packages/dbgpt-core/src/dbgpt/agent/`，由核心抽象与服务端控制器配合：

- **Agent / ConversableAgent**：定义消息收发、状态和执行循环的基础类型。
- **AgentContext**：本次任务的用户、会话、模型、资源和运行配置上下文。
- **AgentMemory**：短期消息/窗口记忆、计划记忆以及可选向量长期记忆的组合。
- **Resource / Tool**：数据库、知识库、MCP、执行器等可调用能力；Agent 决策调用动作，再得到 observation。
- **Plan / Manager**：把用户意图变为子任务，选择 Agent、资源或 workflow 并协调执行。
- **LLMConfig / LLMClient**：向 Agent 屏蔽不同模型提供方与模型调用实现。
- **TeamContext**：描述 Agent 团队成员、关系、启动角色和模式；可以序列化保存。

常见搭建步骤是：明确 Agent 目标与输入/输出；选择对话 Agent、可复用工具或 AWEL operator；声明要使用的资源并限制权限；准备 prompt、上下文和 memory；把成员及协作方式保存为 Agent 应用；从 chat API 发起执行；检查 event、工具 observation、最终输出及会话记录。

### 5.2 原生多 Agent 应用执行

`POST /api/v1/chat/completions` 的 `chat_mode=chat_agent` 分支会调到 `multi_agents.app_agent_chat()`，根据 `app_code` 读取 `GptsApp` 记录：

```text
chat_completions
  -> multi_agents.app_agent_chat(conv_uid, gpts_name, user_query, ...)
  -> 若应用是 Flow：app_agent_flow_chat -> FlowService -> DAG operators
  -> 否则保存/读取 StorageConversation
  -> multi_agents.agent_chat_v2(...)
  -> 读取 GptsApp.team_mode 与 team_context
  -> 选择对应 team manager（如 AutoPlanChatManager 或 AWEL manager）
  -> manager 驱动成员 Agent / action / resource
  -> task 与 chunk 被逐步 yield 回 SSE
  -> 保存 Agent 会话、消息和计划数据
```

`controller.py` 中的 `MultiAgents` 负责应用查询、conversation/memory 构造、流式协调和模式选择；`app_agent_manage.py` 则负责按应用模式建立运行管理器。团队元数据与会话数据由 `dbgpt_serve.agent.db` 下的 DAO/实体保存。

代码同时支持原生多 Agent 协作和 AWEL Flow 型 Agent：原生团队由 manager 驱动 Agent 彼此交接；AWEL Flow 将 operator 连接成有向无环图，由 trigger 触发并沿输入输出边传递数据。两者都能作为一个 DB-GPT 应用暴露，但配置结构与运行语义不同。

### 5.3 Agentic Data / ReAct 分析链

`packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/agentic_data_api.py` 注册 `/api/v1/chat/react-agent`。这条链偏向文件和业务分析，通常包括：

1. 建立会话上下文，读取上传文件、用户选择和可用模型信息。
2. 按用户显式选择或技能描述匹配 Skill，并把 Skill 指令注入 Agent 上下文。
3. 准备工具集合，例如读文件、SQL 查询、知识检索、代码/Python 执行、浏览器或子 Agent 调度。
4. ReAct 循环让模型在“提出下一步—调用工具—观察结果”之间迭代，并以 SSE 发送计划、工具状态和回答。
5. 维护待办步骤、上下文 token 预算及过期 observation 压缩；满足完成条件后输出报告/图表或请求用户补充输入。

工具实现位于 `openapi/api_v1/tools/`，Agent API 对话编排集中在 `agentic_data_api.py`。Skill 是带元数据、说明文档和可选脚本/资源的可复用知识包：它提供领域步骤与工具约束，不等于新的模型，也不会自动获得安全权限。工具应按最小权限配置；外部副作用或高风险动作需要额外的人工确认机制。

### 5.4 AWEL：代码式与可视化工作流

AWEL（Agentic Workflow Expression Language）在 `dbgpt-core` 实现 DAG、trigger、operator、task 与资源节点；应用侧和 serve 层提供可视化 Flow 的元数据、存取与执行接口。典型 Flow 是 HTTP Trigger 接收输入，Prompt/Knowledge Operator 准备上下文，LLM Operator 调模型，Output Operator 负责协议响应。执行期数据依赖 DAG 边而传递，运营期定义会落库并通过 FlowService 加载。

选择 AWEL 的情况：流程步骤固定、节点有明确输入输出、希望可视化维护和复用；选择原生 Agent 的情况：运行步骤需由 Agent 按工具观察结果动态决定。混合使用也可由 Agent 选择一个 Flow/Tool 作为动作。

## 6. 数据语义与 schema 检索

这里的“数据语义”分为三个层次，不能混为单一的业务语义层：

1. **结构语义**：数据源 connector 反射数据库，获得表、字段、类型、主键、索引及数据库方言。
2. **文档语义**：表/字段名称和数据库注释，加上 DB-GPT 生成的数据库画像/表摘要，以文本块索引供自然语言检索。
3. **业务定义语义**：团队维护的指标口径、维度定义、同义词、权限和业务规则。平台能通过描述、知识库、prompt 或应用资源承载这些信息，但当前代码并不自动保证所有企业指标均有统一、可审计的语义模型。

### 6.1 结构读取和持久化

数据源创建的 Web API 会进入 `dbgpt_serve.datasource.api.endpoints`，再调用 `Service.create()`。服务将数据库连接参数存入 DAO；随后提交后台索引任务 `DBSummaryClient.db_summary_embedding(db_name, db_type)`。`ConnectorManager` 按 DB 类型构造具体 connector；抽象约定见 `dbgpt-core/src/dbgpt/datasource/base.py`，SQL 数据库实现见 `dbgpt/datasource/rdbms/base.py`。RDBMS connector 使用 SQLAlchemy metadata 反射，并可读取表注释、列注释、字段类型、默认值和主键信息。

### 6.2 Schema 向量画像

索引时 `DBSummaryClient` 创建 RDBMS/图数据库 summary client，连接目标数据库，使用 `DBSchemaAssembler.load_from_connection()` 生成 schema chunks；`RDBTextSplitter` 把表结构和字段结构拆分；embedding factory 生成向量；storage manager 把表文档写入 `<db>_profile` collection，把字段文档写入 `<db>_profile_field` collection。

查询时 `ChatWithDbAutoExecute.generate_input_values()` 调 `DBSummaryClient.get_db_summary()`，由 `DBSchemaRetriever` 对表和字段向量集合召回与用户问题相关的 schema 文档。检索到的 schema 被放进 Text-to-SQL prompt，帮助模型只关注少量相关表；检索失败时会退回到 connector 的简明 schema 列表。

新建连接触发异步建索引；刷新连接会重建画像；删除连接时删除相应表/字段向量 collection。向量索引是 schema 的检索副本，不替代源数据库元数据，数据库结构变更后要刷新画像以保持一致。

### 6.3 如何补齐业务口径

要让问数结果符合企业口径，需要显式维护“销售额是含税还是未税”“有效用户如何定义”“订单状态哪些纳入 GMV”等规则。可行做法包括：在数据库表/列 comment 中补上稳定定义；在知识库中维护指标字典和业务规则并在问数场景检索；在 Agent Skill 中写入有边界的指标分析流程；为固定流程构建带校验节点的 AWEL Flow。最终仍应把 SQL、指标定义、源字段与时间过滤条件一起呈现，便于业务人员复核。

## 7. RAG 与知识库流程

文档知识库与数据库 schema 检索都使用 embedding/vector-store/retriever 这些 RAG 组件，但索引对象和业务入口不同。文档知识库通常是文件解析、切片、embedding、向量存储、query 检索与上下文拼接；Chat Knowledge 场景将召回片段送入 prompt，并根据检索内容组织答案。数据库 schema 检索对象是表/字段描述，因此用 `DBSchemaAssembler`/`DBSchemaRetriever`。

主要扩展点：

- 文档解析和切分：`dbgpt-ext` 的 RAG loader/text splitter。
- Embedding 创建：`dbgpt-core` RAG embedding factory，并由 app 初始化注册 provider。
- 向量存储：`dbgpt-serve/rag/storage_manager.py` 根据 TOML 创建 Chroma 等向量存储。
- Retriever / Knowledge Space：`dbgpt-serve/rag/retriever/` 与知识空间服务。
- 场景注入：`scene/chat_knowledge/`、Agent Resource 和 AWEL Knowledge Operator。

Embedding 模型应与索引时一致；更换模型通常意味着重建向量索引。向量召回结果是候选证据，不代表最终答案正确，需评估召回覆盖、重排和答案引用。

## 8. 关键代码导航

| 目的 | 建议起点 |
|---|---|
| 统一聊天入口 | `packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/api_v1.py` |
| 通用聊天生命周期 | `packages/dbgpt-app/src/dbgpt_app/scene/base_chat.py` |
| 场景注册与选择 | `packages/dbgpt-app/src/dbgpt_app/scene/chat_factory.py`、`scene/base.py` |
| Chat DB Text-to-SQL | `packages/dbgpt-app/src/dbgpt_app/scene/chat_db/auto_execute/` |
| ReAct Agentic Data | `packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/agentic_data_api.py` |
| Agent 工具实现 | `packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/tools/` |
| Agent 核心抽象 | `packages/dbgpt-core/src/dbgpt/agent/` |
| 多 Agent 控制器 | `packages/dbgpt-serve/src/dbgpt_serve/agent/agents/controller.py` |
| Agent 应用与团队管理 | `packages/dbgpt-serve/src/dbgpt_serve/agent/agents/app_agent_manage.py` |
| 数据源 API 与生命周期 | `packages/dbgpt-serve/src/dbgpt_serve/datasource/` |
| 数据库 connector 抽象 | `packages/dbgpt-core/src/dbgpt/datasource/` |
| Schema 汇总、向量索引、检索 | `packages/dbgpt-serve/src/dbgpt_serve/datasource/service/db_summary_client.py`、`packages/dbgpt-ext/src/dbgpt_ext/rag/assembler/db_schema.py`、`retriever/db_schema.py` |
| AWEL API 与应用文档 | `packages/dbgpt-core/src/dbgpt/core/awel/`、`docs/docs/application/awel.md` |
| 部署配置 | `docker-compose.yml`、`configs/dbgpt-proxy-tongyi-mysql.toml` |

## 9. 部署验证与后续操作

部署状态可用以下命令检查：

```powershell
docker compose ps
docker compose logs --tail 100 webserver
docker compose logs --tail 100 db
Invoke-WebRequest http://localhost:5670/api/health
```

服务健康后，浏览器打开 Web UI，添加实际可访问的业务数据源，在 Chat DB 选择该数据源进行问答。数据库 schema summary 是异步任务；首次添加数据源后等待索引完成，再测试相关表的召回质量。阿里云 API key 生效后，除聊天模型外也要验证 embedding 模型，因为向量知识库和 DB schema 画像都依赖 embedding。

排查顺序：

1. `docker compose ps` 检查容器是否持续运行/重启。
2. 看 `webserver` 日志中的实际 Profile 和配置路径，确认读取的是 `dbgpt-proxy-tongyi-mysql.toml`。
3. `db` 状态应为 healthy；检查初始化 SQL 与 MySQL 账号连接。
4. 将 `configs/dbgpt-proxy-tongyi-mysql.toml` 两处 `api_key` 占位值替换为有效凭据，再重启 Web 容器。
5. 分别检查 LLM 和 embedding 端点、模型名、账号权限与网络连通性。
6. Schema 无召回时先检查连接器能否读取表，再查看后台 summary 日志和 Chroma collection。

## 10. 重要实现边界

- 向量 schema 检索减少 prompt 里的 schema 规模，但不是 SQL 语法或权限验证器。
- 生成 SQL 和工具调用均受模型输出影响；应在数据库侧设置只读账号、表级授权、超时和行数限制。
- Agent memory 可能包含历史问题和数据摘要；使用长期向量记忆前要评估数据保留、删除和隔离策略。
- Compose 使用固定示例数据库密码且服务 API keys 默认为空，适合本机开发验证。不要直接暴露至公网。
- 8 GB 显存不适合按上游本地模型推荐规格部署 30B 级模型；云端推理能降低本地 GPU 和内存压力，但需要配置 API 凭证并处理数据外发合规要求。

## 11. AWEL 源码：节点如何从画布变成可运行 DAG

AWEL 画布不是远程 Python IDE。前端存的是**图的声明**：哪些已知节点实例在图上、每个节点有哪些参数值、输入输出端如何连接。后端持有真正的 Python 算法类；保存时按声明反查类、实例化算子、连接 DAG、持久化定义并（部署状态时）注册 trigger。

### 11.1 三种节点对象：Operator、Resource、Trigger

- **Operator** 是图里的计算步骤，运行时继承 `BaseOperator`；常用父类 `MapOperator[IN, OUT]`、`JoinOperator`、`ReduceStreamOperator`、`BranchOperator` 定义处理形态。
- **Resource** 是算子的依赖对象，例如 LLM client、prompt、database connector、vector store 或某个可配置资源。Resource 节点在 DAG 构建时实例化，然后注入 Operator 参数；它本身不作为普通计算 task 链路执行。
- **Trigger** 是启动入口，可以是 HTTP、迭代器等。Trigger 注册到 `TriggerManager` 后接收外部请求，再触发 DAG。

核心执行节点关系在 `dbgpt-core/src/dbgpt/core/awel/dag/base.py`：`DAGNode` 同时包含依赖图和 `ViewMixin`，`BaseOperator` 增加运行器、`call()`/`call_stream()` 和 `_do_run()` 执行合同。`MapOperator._do_run()` 读取父节点结果或根节点 call data，再调用子类 `map(input)`；因此一个典型算法算子只需要处理明确的输入类型并返回输出类型。

### 11.2 节点元数据既是前端 schema，也是后端反序列化协议

`dbgpt-core/src/dbgpt/core/awel/flow/base.py` 中的几类元数据决定节点怎样显示、怎样连线、怎样实例化：

| 元数据 | 定义内容 | 前端/后端作用 |
|---|---|---|
| `ViewMetadata` | 算子名、分类、描述、版本、参数、输入、输出 | 在节点列表中展示；构建器据此校验并建立 Operator |
| `Parameter` | 字段名/类型/默认值/必填/选项/UI 类型/是否动态 | 生成节点参数编辑控件；存储实例的参数值 |
| `IOField` | 输入/输出字段名、Python 类型路径、是否 list、动态端口、mapper | 决定画布 handle 和类型兼容性；运行时定义边的端口次序 |
| `ResourceMetadata` | Resource 类型、可注入父类型、构造参数 | 让资源在画布上展示，并匹配能接收该资源的节点参数 |

Operator 子类被 Python import 时，`DAGNode` 的 `ViewMixin`/`BaseOperatorMeta` 会触发 `after_define()`，进而 `_register_operator()`，把类和 `ViewMetadata` 放到 `_OPERATOR_REGISTRY`。App 启动配置中的 `_initialize_operators()` 会扫描 `dbgpt_app.operators` 与 `dbgpt_serve.agent.resource`，确保节点类导入并注册。后台 `/api/v2/serve/awel/nodes` 读取 registry，把 metadata 序列化后返回前端；前端本身不凭文件名猜节点。

节点标识含稳定的逻辑键：`operator_<name>___$$___<category>___$$___<version>`；Flow JSON 同时保存 Python `type_cls`（完整导入路径）与 `type_name`。构图时通过逻辑键从 registry 拿到已注册类，并以类上的 metadata 为准；Flow JSON 里前端传回的 metadata 不能覆盖服务端实际算子定义。这能避免用户仅靠改请求 JSON 伪造一个后端任意类，但仍应把 Flow API 当成部署接口保护。

### 11.3 前端：发现节点、连线、填参数和保存

主要源码：`web/components/flow/add-nodes-sider.tsx`、`add-nodes.tsx`、`canvas-node.tsx`、`node-handler.tsx`、`pages/construct/flow/canvas/index.tsx`、`components/flow/canvas-modal/save-flow-modal.tsx` 和 `client/api/flow/index.ts`。

1. 左侧栏通过 `getFlowNodes()` 请求 `GET /api/v2/serve/awel/nodes`，把 `flow_type` 为 `operator` 与 `resource` 的 metadata 分开，按 category 分组显示。
2. 拖拽节点时，以 metadata 为节点 `data`，创建一个带 UI `id`、画布位置和 `customNode` 类型的 ReactFlow node。参数表单由 `Parameter.ui` 元数据渲染；参数有依赖的动态 options 时，前端调用 `POST /nodes/refresh` 让服务端按新依赖刷新字段可选值。
3. 节点端口是 `inputs`、`outputs` 或资源/算子的资源型 `parameters`。前端 handle 标识包含 node id、handle 类型和端口索引。连 Operator→Operator 时比对 `type_cls` 与 list 标志；资源→Operator/Resource 时用 `ResourceMetadata.parent_cls` 判断目标参数是否能接受该资源。
4. 保存前 `checkFlowDataRequied()` 做画布侧必填参数、必连端口和动态端口数量等检查。它是用户体验校验，后端 `FlowFactory.build()` 仍会重新做权威校验。
5. `reactFlow.toObject()` 产生 `{nodes, edges, viewport}`。`mapHumpToUnderline()` 把 `positionAbsolute`、`sourceHandle`、`targetHandle` 改成后端 schema 使用的 snake_case。
6. `SaveFlowModal.onSaveFlow()` 创建时 `POST /api/v2/serve/awel/flows`，更新时 `PUT /api/v2/serve/awel/flows/{uid}`。请求包括 `flow_data`、变量、名称和状态。默认保存状态为 `deployed`，因此成功保存通常意味着请求后端构建并注册工作流，而不只是写草稿。

画布 JSON 的关键形状可简化为：

```json
{
  "flow_data": {
    "nodes": [
      { "id": "...", "position": { "x": 0, "y": 0 }, "data": { "flow_type": "operator", "type_cls": "pkg.MyOperator", "parameters": [] } }
    ],
    "edges": [
      { "source": "node_a", "target": "node_b", "source_handle": "node_a|outputs|0", "target_handle": "node_b|inputs|0" }
    ],
    "viewport": { "x": 0, "y": 0, "zoom": 1 }
  }
}
```

这里的 node id 是**一次流程里节点实例的 key**；`type_cls` / metadata key 才是实现类身份。复制同一种算子产生新的 node id，但它仍会解析到同一个 Python 算子类。

### 11.4 后端：Flow JSON 如何转成 Python DAG

HTTP 层在 `dbgpt-serve/src/dbgpt_serve/flow/api/endpoints.py`，数据服务在 `service/service.py`，声明到 DAG 的转换在 `dbgpt-core/src/dbgpt/core/awel/flow/flow_factory.py`。`ServeRequest` 直接别名为 `FlowPanel`，其中 Pydantic 结构 `FlowData` / `FlowNodeData` / `FlowEdgeData` 验证节点类型与边；边的 `source_order` / `target_order` 可由 handle 中的索引补出。

`FlowService.create_and_save_dag()` 主要步骤：

1. 若 `define_type == "json"`，调用 `FlowFactory.build(request)`；其他类型使用传入的 `flow_dag`。
2. `FlowFactory.build()` 将节点按 `flow_type` 分为 operator 与 resource，检查 node id 唯一、边两端存在、operator/resource 连接方向合法。
3. 从边恢复相邻关系与端口序号；执行拓扑排序。算子输出若声明 mapper，会插入 mapper operator 转换输出类型。
4. 按拓扑顺序实例化资源，确保资源依赖先建好；把资源 node id 写入下游算子的 resource 参数。
5. 从 registry 取算子真实 class 和 class metadata，结合 Flow JSON 中保存的参数值构造 runnable 参数，实例化每一个算子。
6. 构造真正的 `DAG`，只对 operator-to-operator 数据依赖执行 `upstream >> downstream`。Resource edge 是构造期依赖注入，不是运行期 data edge。
7. DAO 将 `flow_data` 序列化成 JSON 写入 Flow 表。如果状态为 `DEPLOYED`，服务调用 `DAGManager.register_dag()` 注册 DAG 与触发器，再把状态更新为 `RUNNING`。如建图失败，接口返回错误；更新失败时 service 会尝试恢复之前正在运行的版本。

Flow JSON 是持久化源定义；`DAGManager.dag_map` 是当前进程中可执行 DAG 实例。进程启动时 Flow service 再从数据库加载 `DEPLOYED`/`RUNNING` Flow，重建 DAG 并重新注册。因此“保存到数据库”与“当前进程已有可调用 DAG”是两个步骤；状态不是 RUNNING 时可能仅保存定义、不注册执行入口。

### 11.5 工作流何时、如何运行

**HTTP Trigger Flow**：当 DAG 中有 HTTP trigger，`DAGManager.register_dag()` 会为 trigger 向 `TriggerManager` 注册 URL 路由；请求到该 URL 后，trigger 把 body 映射为 DAG 输入并启动 DAG。Trigger 的动态路由注册逻辑见 `core/awel/trigger/http_trigger.py` 和 `trigger/trigger_manager.py`。

**Chat Flow**：前端统一聊天 API 选择 `chat_mode=chat_flow`，走 `api_v1.py` 中的 Chat Flow 分支；它构造 `CommonLLMHttpRequestBody` 并调用 `FlowService.chat_stream_flow_str(flow_uid, request)`。服务用 uid 找当前 DAG，取唯一 leaf Operator 做执行入口，逐步 yield stream 输出。Chat Flow 要有兼容的 `CommonLLMHttpTrigger` 和一个输出 leaf；`FlowService._parse_flow_category()` 根据 trigger 和 leaf output 类型识别应用类别。

运行器见 `core/awel/runner/local_runner.py`：从被调用的末端算子反向找 upstream，递归确保上游先运行，再创建 TaskContext、把输入设为父节点输出、设置 DAGContext，最后调用 `node._run()`。`_run()` 先解析 DAG variables，再进 `_do_run()`；Map 算子调用 `map()`。当前 LocalRunner 中 upstream 是 `for` 循环依次运行，代码也留有“并行运行 upstream”的 TODO，所以不能假设普通分叉会自动并行。

`POST /api/v2/serve/awel/flow/debug` 会对请求里的 Flow 临时 build 并执行 stream，适合画布调试；它与保存/部署后的 `dag_manager.dag_map` 注册路径不同。动态参数刷新 `/nodes/refresh` 只刷新 metadata/options，也不是执行 DAG。

### 11.6 开发一个算法算子

建议把算法逻辑包装成纯输入输出转换，第三方 I/O 放到明确的 Resource 或组件依赖中。最小 `MapOperator` 示例：

```python
from dbgpt.core.awel import MapOperator
from dbgpt.core.awel.flow import IOField, OperatorCategory, ViewMetadata


class NormalizeTextOperator(MapOperator[str, str]):
    metadata = ViewMetadata(
        label="Normalize text",
        name="normalize_text",
        category=OperatorCategory.CONVERSION,
        description="Trim whitespace and normalize line endings.",
        parameters=[],
        inputs=[IOField.build_from("Text", "input", str)],
        outputs=[IOField.build_from("Normalized text", "output", str)],
    )

    async def map(self, input_value: str) -> str:
        return input_value.replace("\r\n", "\n").strip()
```

开发准则：

- `MapOperator[IN, OUT]` 的泛型、`IOField.build_from()` 输入输出类型必须一致；类型会序列化成模块路径供前端判断连线兼容。
- `metadata.parameters` 的每个 `Parameter.name` 必须对应 `__init__` 参数名；`Parameter.type`、默认值、optional 和 UI schema 决定表单与后端运行值。
- 如要注入 LLM、Datasource 或自定义连接器，声明 resource category 参数并用 `ResourceMetadata.parent_cls` 表明资源可连到哪个类型；不要把连接凭证硬编码进 Python 类或普通 Flow JSON。
- 返回类型若和下游不一致，要提供显式转换算子/mapper，不要只改 `type_cls` 让前端“看起来能连”。
- 在运行时调用阻塞 I/O 时用 `self.blocking_func_to_async(fn, ...)`，避免阻塞事件循环；长耗时和失败要可观测，错误应抛成能定位到节点的异常。
- 需要流式语义时使用相应 stream Operator/Input/Output 类型，显式定义 chunk 类型和完成行为，不要把普通 `MapOperator` 当作生成器随意返回。
- 自定义模块必须随 Web 后端部署，并在应用扫描范围内（或由 Flow import 预加载）；前端画布只负责展示 registry 已暴露的定义。新增/改节点类后重启应用，使模块导入和注册发生。

真实仓库参考实现：`packages/dbgpt-app/src/dbgpt_app/operators/rag.py` 的 `HOKnowledgeOperator`。它声明知识空间、top_k、score threshold 等参数；输入是用户问题 `str`，输出为 `HOContextBody` 和 `Chunk` 列表；初始化检索器，`map()` 调 retriever 并将 chunks 写入 `DAGContext` share data。复杂下游需要原始 chunks 时，通过专门的 `ChunkMapper` 子 operator 读取共享数据。这展示了“一个主要 output + 显式 mapper 端口”如何表达一对多数据。

修改 Operator 的输入输出 schema 是对画布连线协议的更改：已有 Flow 持久化旧 `type_cls`、port 顺序、参数名和 `type_cls`；变更时要检查老 Flow JSON 和版本兼容，并在类的 `version` 上明确兼容策略。

### 11.7 从开发到上线的验证顺序

1. 确认模块被 `_initialize_operators()` 扫描，启动日志/`GET /api/v2/serve/awel/nodes` 能看到节点元数据。
2. 在 metadata 检查参数必填、类型路径、UI 控件、输入/输出和版本信息。
3. 在画布检查连线候选、资源参数、动态端口、保存校验；使用 debug endpoint 输入最小请求验证输出。
4. 正式保存为 deployed，确认 Flow 状态进入 RUNNING；查询详情中的 `dag_id` 和 Flow metadata。
5. 调用对应 HTTP trigger 或 chat flow URL，检查每个 operator 的 task 状态、日志、trace、stream 输出和错误路径。
6. 重启应用后再调用一次，验证 Flow 从持久化 JSON 重新 load/注册，而不是只依赖开发进程里的内存状态。

