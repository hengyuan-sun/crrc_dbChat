# ADR-0002：前端目录的包管理器与锁文件归属

- 状态：已接受
- 日期：2026-09-26
- 责任角色：前端负责人、平台与发布负责人
- 关联任务/PR：P1.1 离线工程底座

## 背景

Web 与文档站各自同时存在 npm 和 Yarn 锁文件。现有 Web CI、静态资源脚本使用 Yarn；文档站 Docker 构建执行 `npm ci`。多把锁允许本地和 CI 解析出不同依赖图，且会发出包管理器混用警告。

## 决定

- `web/` 使用 Yarn Classic 1.22.22，唯一锁文件为 `web/yarn.lock`；Corepack 按 `web/package.json` 的 `packageManager` 字段选择版本。CI 与 Linux 静态打包使用冻结锁安装。
- `docs/` 使用 npm `ci`，唯一锁文件为 `docs/package-lock.json`；Dockerfile 与本地说明一致使用 npm。
- 移除两目录各自未选用的锁文件，并在对应 package manifest 中保持文档站包名为企业产品名。
- Yarn 锁定图中原有 `d3-array@2` 全局 resolution 覆盖了图表引擎要求的 `^3.2.4`，出现 `medianIndex` 缺少导出的 Webpack 告警。移除这条全局覆盖，让依赖声明选择兼容的主版本；旧版本消费者仍可由锁文件保留对应版本。

## 兼容与离线状态

两套重复锁已移除：Web 保留 Yarn 锁，文档站保留 npm 锁。移除 Web 对 `d3-array` 的全局版本覆盖后，G2 所需的 3.2.4 与旧依赖所需的 2.12.1 可按依赖范围并存，构建时的 `medianIndex` 导出错误消失。

Web 初次离线安装因临时缓存缺少 `d3-color` 失败；联网导入锁文件对应包后，同一机器上的离线冻结锁安装成功。这证明当前临时缓存齐备，不证明全新内网机器已有依赖制品。完整 Yarn/NPM 离线镜像、Node 基础镜像 digest 与 SBOM 尚未交付，因此无公网环境安装仍未验收。

## 验收证据

- Web Yarn 1.22.22 离线冻结锁安装成功（临时缓存已完整导入）；前端单元测试 20 项通过；Next 生产构建和 58 路由静态导出成功。
- 导出产物首页、Flow 画布深链、Prompt 新建页以及两个 CRRC SVG 本地 HTTP smoke 均返回 200；目前未做图表组件的人工浏览器验收。
- 已启动文档站 `npm ci`，但联网十多分钟后仍在等待 npm registry 元数据请求（单次 Docusaurus 元数据请求约 165 秒）；本轮主动结束该进程，未取得成功退出码，因此文档依赖安装、站点构建和容器构建均未验收。
- 构建仍报告旧 Browserslist 数据、React Hook 依赖 lint 提示、缺 Next ESLint plugin；Next 配置仍跳过类型检查。它们没有阻断当前构建，但应作为质量债逐项修复/确认。
- 静态导出提示 Next rewrites 不会应用；生产 API 路由需由部署入口配置。本机离线缓存测试也不等价于干净机器/无公网验收。
