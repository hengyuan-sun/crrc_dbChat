# crrc_dbChat Web

本目录包含企业平台的浏览器界面，基于 Next.js。开发环境需要 Node.js 18 或更高版本，并使用 Corepack 管理的 Yarn 1.22.22。依赖安装只使用 `yarn.lock`。

## 安装与开发

```powershell
corepack enable
corepack yarn install --frozen-lockfile --non-interactive
Copy-Item .env.template .env
corepack yarn dev
```

在 `.env` 中按本机 API 地址配置前端环境。真实地址和凭据不要写入版本库；离线环境需先将锁文件对应的包导入批准的内网缓存。

## 构建与测试

```powershell
corepack yarn test
corepack yarn build
corepack yarn export
```

构建由 `scripts/run-next.js` 启动 Next.js，以兼容 Windows 与 Linux，并禁用框架遥测。静态导出写入 `out/`；项目部署脚本 `scripts/build_web_static.sh` 会将静态文件复制到 API 服务资源目录。静态导出不包含 Next.js rewrites，部署环境必须由内网入口或 API_BASE_URL 提供正确 API 路径。

构建的并发可通过 `NEXT_BUILD_CPUS` 设置，默认 4；静态页面收集超时为 180 秒。若修改图表依赖，先检查 d3 版本解析和实际页面渲染，不能仅凭构建成功判定所有可视化运行正常。
