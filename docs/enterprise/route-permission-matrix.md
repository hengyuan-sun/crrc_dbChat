# 路由权限基线与核验规则

机器可读的 OpenAPI 盘点位于 [`route-permission-matrix.csv`](route-permission-matrix.csv)，基于当前运行服务的 `/openapi.json` 生成，共 364 个 operations、326 个 paths。表中 `openapi_security` 只代表 OpenAPI 文档是否声明 security scheme，不是认证或资源授权通过证明。

## 当前结论

- OpenAPI 中 124 个 operation 声明了 `security`，其余 240 个没有声明。
- 当前 schema 没有为任何 operation 明确暴露 `user_id` header 参数。运行时可能通过依赖注入、全局中间件或业务代码处理身份；因此不能仅凭此列断言没有身份检查。
- 已直接核查 `dbgpt_serve.utils.auth.get_user_from_headers()`：客户端可控 `user_id` 会被当作身份并给 `admin` 角色；缺省身份也是固定 `001/admin`。
- 已直接核查 Flow 路由依赖：`check_api_key()` 对 `/api/v1` 路径跳过，未配置 API keys 时允许访问。还需逐路由检查端点是否依赖该函数及是否有其他保护。
- 目前没有完成全部 API 的身份认证、workspace 过滤、对象级 CRUD/运行权限审查。矩阵的 assessment 字段是待核实项，不是漏洞最终判定或验收状态。

## 逐路由审查表要求

对每条 method/path 建立如下证据后，才可改为 `已核验`：

1. 精确到 endpoint 函数与挂载 router 的源码位置。
2. 认证来源：cookie/JWT/可信代理身份/service account/匿名白名单；签名、issuer、audience、过期、禁用账号如何检查。
3. 权限动作：list/read/create/update/delete/run/debug/export/share/admin 等实际策略。
4. 资源 ID 是否先限制组织/workspace/owner 再读取；列表、下载、导入导出、异步任务、节点动态参数和错误回显是否一致。
5. 未授权/匿名/伪造 user/workspace/resource ID 的用例及状态码；平台管理员是否默认有业务数据读取权。

最终权限策略采用默认拒绝。前端隐藏按钮、OpenAPI 声明、API key 存在与否，均不能替代后端逐次资源授权。
