# crrc_dbChat 贡献指南

本文说明如何在团队内安全地修改、验证和交付代码。平台当前处于企业化迁移阶段；修改包名、序列化格式、数据表或运行配置时，必须同时更新兼容映射和迁移说明。

## 开发环境

仓库目录：`D:\Projects\DB-GPT-main\crrc_dbChat`。Windows 用 PowerShell，Linux 用 Bash；容器镜像目标为 Linux。路径大小写、换行符和 shell 脚本差异应在提交前检查。

先安装仓库要求的 Python、Node 和 `uv` 版本。Python workspace 当前仍含待迁移的历史包名，依赖安装命令以根目录 `pyproject.toml` 为准；前端使用 `web/package.json` 声明的 npm 脚本。锁文件方案尚未冻结，新增或升级依赖前先在任务卡中说明管理器、版本和离线制品来源，不要同时改写 npm/yarn 锁文件。

```powershell
Set-Location D:\Projects\DB-GPT-main\crrc_dbChat
python --version
node --version
uv --version
```

内网构建请使用经过批准的依赖镜像或离线 wheelhouse/npm 缓存。开发环境的临时镜像源不得写入生产配置。不要提交 `.env`、访问令牌、真实数据库连接串、模型密钥或业务数据。

## 分支、提交和评审

1. 从最新 `main` 创建短期分支，命名建议为 `feat/<task-id>-<topic>`、`fix/<task-id>-<topic>` 或 `docs/<task-id>-<topic>`。
2. 一个 PR 解决一个可独立验收的任务；跨模块改动先在任务卡/PR 描述中列明依赖和接口契约。
3. 提交标题使用 `type: summary`，例如 `docs: add offline developer guide`、`fix: reject untrusted user headers`。
4. PR 说明实际行为、数据/API 兼容影响、迁移与回退方式、验证命令和未完成项。评审人按代码边界与风险选择，不在仓库中虚构团队账号。
5. 共享 API schema、数据库迁移序号、依赖锁、包名映射和前端节点类型由集成负责人协调，避免并行覆盖。

GitHub 分支保护、必需评审人数和组织团队授权需仓库管理员在 GitHub 配置。当前仓库文件只能提供模板，不能证明这些远端设置已经生效。

## 模块协作边界

模块职责、角色化负责人和契约检查见 [`docs/enterprise/team-development.md`](docs/enterprise/team-development.md)。没有确认成员账号时，按角色分配工作并由项目维护者指定具体评审人；`.github/CODEOWNERS.template` 不是生效的 CODEOWNERS 文件。

## 代码和中文说明

- 新增或修改的关键 Python 函数，在定义处写中文 docstring；TypeScript/React 导出函数和关键状态/请求函数写中文 JSDoc。
- 说明要与实现一致，写清用途、参数/返回、前提、权限范围、异常及可见副作用。算法函数补充关键步骤和选择理由；简单直观代码不堆砌行内注释。
- 修改权限、事务、序列化、节点注册或异步任务时，更新关键函数清单、接口契约和相应用例。
- 不修改依赖、生成代码或第三方源码来凑注释覆盖率。上游许可证、版权、NOTICE 和第三方声明保持准确。

## 提交前验证

按照改动选择可复现的检查，并在 PR 中粘贴实际结果：

```powershell
python scripts/branding_audit.py --format text
python -m pytest <本次相关测试目录> -q
```

前端变更在锁文件与依赖可用后运行 `npm run build` 和适用测试；Python 变更按仓库当前可用环境运行对应 lint、类型检查和测试。若离线依赖暂不可用，记录缺少的制品与阻塞，不要把未运行写成通过。全量检查方式、基线和已知缺口见 [`docs/enterprise/baseline-report.md`](docs/enterprise/baseline-report.md)。

## 任务交接

每个跨阶段任务使用 [`docs/enterprise/task-handoff-template.md`](docs/enterprise/task-handoff-template.md) 记录提交、环境、验证证据、迁移/数据状态、未完成项和下一步。禁止因改 Compose 项目名或持久卷名而未经核验创建空库、删除旧卷或覆盖业务数据。
