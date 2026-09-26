# crrc_dbChat 文档站

文档站使用 Docusaurus，锁定依赖由 `package-lock.json` 管理，安装时使用 npm `ci` 模式。

## 本地预览

```powershell
Set-Location docs
npm ci
npm run start
```

默认访问 `http://localhost:3000`。构建静态站点运行 `npm run build`，生成目录为 `docs/build/`。

## 容器

单版本文档可从仓库根目录构建：

```powershell
docker build -f docs/Dockerfile -t crrc-dbchat-docs:local .
```

`Dockerfile-deploy` 会根据 Git 标签生成多版本文档，并会访问版本历史/远程源；它目前不属于已验证的完全离线部署路径。容器基础镜像、npm 依赖缓存和 Git 历史制品需要进入内网发布清单后再进行断网验收。
