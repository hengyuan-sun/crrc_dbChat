"""sql_query tool — read-only SQL query against the selected database."""

import json
from typing import Any, Dict, Optional

from dbgpt.agent.resource.tool.base import tool


def make_sql_query(react_state: Dict[str, Any], database_connector: Optional[Any]):
    """为当前 Agent 注册数据库查询工具，并捕获所选连接器。

    Args:
        react_state: Agent 工具构建上下文；当前实现未读取该参数。
        database_connector: 已选择的数据源连接器；为空时工具返回提示信息。

    Returns:
        Callable: 接收 SQL 字符串并返回 JSON 编码工具结果的闭包。

    安全边界：真正的执行发生在返回的 `sql_query` 闭包中。当前关键字前缀检查
    不是 SQL parser，不能阻止注释、CTE、方言函数、多语句或其他绕过方式；结果行数
    与文本裁剪发生在连接器取回结果之后。生产只读保障必须由共享 SQL 策略、执行
    超时/行数限制和数据库只读账号共同实现。
    """

    @tool(
        description=(
            "对用户选择的数据库执行 SQL 查询（仅支持 SELECT）。"
            '参数: {"sql": "SELECT 语句"}'
        )
    )
    def sql_query(sql: str) -> str:
        """执行一次受当前前缀规则检查的查询，并将结果格式化为工具 JSON。

        Args:
            sql: Agent 生成的 SQL 文本。

        Returns:
            str: 含文本或 Markdown 表格的 JSON `chunks` 字符串；连接器异常会被
                转成错误文本返回，而不是继续向 Agent 调用栈抛出。

        当前限制：只按去除首尾空白后的语句起始词拦截部分写操作；查询执行后最多
        展示 50 行，并将文本限制为 20,000 字符，但不会阻止数据库先返回更大结果。
        不将此闭包视为完整只读授权或结果脱敏边界。
        """
        if database_connector is None:
            return json.dumps(
                {
                    "chunks": [
                        {
                            "output_type": "text",
                            "content": "未选择数据库，请先在左侧面板选择一个数据源。",
                        }
                    ]
                },
                ensure_ascii=False,
            )

        sql_stripped = sql.strip().rstrip(";")
        sql_upper = sql_stripped.upper().lstrip()
        forbidden = [
            "INSERT",
            "UPDATE",
            "DELETE",
            "DROP",
            "ALTER",
            "TRUNCATE",
            "CREATE",
            "GRANT",
            "REVOKE",
        ]
        for kw in forbidden:
            if sql_upper.startswith(kw):
                return json.dumps(
                    {
                        "chunks": [
                            {
                                "output_type": "text",
                                "content": f"安全限制: 不允许执行 {kw} 语句，"
                                "仅支持 SELECT 查询。",
                            }
                        ]
                    },
                    ensure_ascii=False,
                )

        try:
            result = database_connector.run(sql_stripped)
            if not result:
                return json.dumps(
                    {
                        "chunks": [
                            {"output_type": "text", "content": "查询返回空结果。"}
                        ]
                    },
                    ensure_ascii=False,
                )

            columns = result[0]
            col_names = [str(c[0]) if isinstance(c, tuple) else str(c) for c in columns]
            rows = result[1:]

            header = "| " + " | ".join(col_names) + " |"
            separator = "| " + " | ".join(["---"] * len(col_names)) + " |"
            md_rows = []
            for row in rows[:50]:
                md_rows.append("| " + " | ".join(str(v) for v in row) + " |")
            table = "\n".join([header, separator] + md_rows)
            if len(rows) > 50:
                table += f"\n\n（仅显示前 50 行，共 {len(rows)} 行）"

            # Cap total output size so a single wide query can't blow out the
            # LLM context window. The full result remains available via the
            # ToolResultStorage persistence layer if it exceeds the threshold.
            MAX_SQL_OUTPUT_CHARS = 20_000
            if len(table) > MAX_SQL_OUTPUT_CHARS:
                table = (
                    table[:MAX_SQL_OUTPUT_CHARS]
                    + f"\n\n... [Output truncated at {MAX_SQL_OUTPUT_CHARS} chars. "
                    f"Total rows: {len(rows)}]"
                )

            return json.dumps(
                {"chunks": [{"output_type": "markdown", "content": table}]},
                ensure_ascii=False,
            )
        except Exception as e:
            return json.dumps(
                {
                    "chunks": [
                        {
                            "output_type": "text",
                            "content": f"SQL 执行失败: {str(e)}",
                        }
                    ]
                },
                ensure_ascii=False,
            )

    return sql_query
