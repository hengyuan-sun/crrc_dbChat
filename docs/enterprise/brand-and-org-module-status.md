# crrc_dbChat 品牌与组织同步模块阶段记录

## 本阶段范围

- 用户可见的中英文首页标题、常用对话文案、侧栏 Logo、HTML/社交分享元信息更新为 `crrc_dbChat` / `CRRC 长客股份`。
- 前端 Logo 使用本地 SVG，不依赖外网图片服务。
- 新增组织/部门/用户快照数据契约、目录适配器协议、完整性校验和只读预览。
- 保留上游 Python 包名、模块路径、命令、存储键和 HTTP 接口路径，以避免破坏既有导入和客户端兼容。

## 组织同步模块当前行为

代码位于 `packages/dbgpt-serve/src/dbgpt_serve/organization_sync/`。目前可注入内网目录读取适配器，并验证外部 ID 唯一性以及组织/部门/用户引用完整性。预览只汇总数量，不落库、不更改账号状态、不分配角色。真实 IdP、权威 HR 字段、平台侧存储、审批、审计和定时任务尚待企业接口确认。

## 品牌替换范围与兼容边界

项目核心包、CLI 和大量历史文档仍包含 `dbgpt` / `DB-GPT` 标识。这些词有一部分是 import 路径、API、配置环境变量、存储键、上游版权和论文引用，不宜通过全局字符串替换破坏兼容性或抹去来源。本阶段替换产品入口及 UI 文案；其余待分类后按模块迁移，并为外部兼容项保留说明。

## 中文函数说明覆盖

本阶段新增组织同步模块的类和函数均写有中文文档字符串；本次修改的前端组件保持原有组件注释风格。现有上游代码尚未逐函数补齐中文说明，这是跨数千文件的后续分阶段工作，不能标记为已完成。

## 验证

- `PYTHONPATH=packages/dbgpt-serve/src;packages/dbgpt-core/src;packages/dbgpt-ext/src python -m pytest packages/dbgpt-serve/src/dbgpt_serve/organization_sync/tests/test_service.py -q`：4 项通过。
- 前端完整构建/测试需在安装锁文件依赖的 Node 环境中执行；目标副本未包含 `node_modules`，本阶段尚未验证构建。
- 源码源目录不含 Git 历史，目标仓库以本地源码建立首次提交；原始 commit 来源无法核验。
