# 本机源码启动

当前启动方式会使用本机已有的 DB-GPT 运行时镜像作为依赖层，并从本仓库的 `packages/` 构建 `crrc-dbchat:local` 镜像。API 服务运行的是当前工作区源码；MySQL 数据卷沿用 `db-gpt-main` Compose 项目中已有的数据。

## 启动

在仓库根目录执行：

```powershell
docker compose -p db-gpt-main -f docker-compose.yml -f docker-compose.crrc.yml up -d --build
```

访问地址：

- 前端/API：<http://127.0.0.1:5670>
- API 文档：<http://127.0.0.1:5670/docs>

停止服务但保留数据库数据：

```powershell
docker compose -p db-gpt-main -f docker-compose.yml -f docker-compose.crrc.yml down
```

## 本地模型

配置文件 `configs/crrc-offline-start.toml` 将 LLM 和 embedding 请求指向 `host.docker.internal:11434`。本机需要另行启动兼容 OpenAI API 的离线推理服务；可以通过容器环境变量 `LOCAL_MODEL_API_BASE`、`LOCAL_EMBEDDING_API_URL`、`LLM_MODEL_NAME`、`EMBEDDING_MODEL_NAME` 指定地址和模型名。没有模型服务时，平台页面和 API 仍可启动，但对话、embedding 与知识库处理不能完成。

## 当前限制

- 前端静态资源仍来自已有运行时镜像的打包内容；仓库 `web/` 中新改的品牌文案/Logo 尚未通过前端构建替换进服务静态目录。
- 本地模型未在启动时实测，本机缺少监听于 11434 的模型服务时，启动日志会记录 embedding 连接失败。
- 此启动 profile 用于本机开发验证；MySQL 示例密码和 `encrypt_key` 必须在共享或生产部署前替换。
