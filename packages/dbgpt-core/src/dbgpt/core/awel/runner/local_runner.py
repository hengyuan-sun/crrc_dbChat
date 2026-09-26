"""Local runner for workflow.

This runner will run the workflow in the current process.
"""

import asyncio
import logging
import traceback
from typing import Any, Dict, List, Optional, Set, cast

from dbgpt.component import SystemApp
from dbgpt.util.tracer import root_tracer

from ..dag.base import DAGContext, DAGVar, DAGVariables
from ..operators.base import CALL_DATA, BaseOperator, WorkflowRunner
from ..operators.common_operator import BranchOperator
from ..task.base import SKIP_DATA, TaskContext, TaskState
from ..task.task_impl import DefaultInputContext, DefaultTaskContext, SimpleTaskOutput
from .job_manager import JobManager

logger = logging.getLogger(__name__)


class DefaultWorkflowRunner(WorkflowRunner):
    """The default workflow runner."""

    def __init__(self):
        """Init the default workflow runner."""
        self._running_dag_ctx: Dict[str, DAGContext] = {}
        self._task_log_index_map: Dict[str, int] = {}
        self._lock = asyncio.Lock()

    async def _log_task(self, task_id: str) -> int:
        async with self._lock:
            if task_id not in self._task_log_index_map:
                self._task_log_index_map[task_id] = 0
            self._task_log_index_map[task_id] += 1
            logger.debug(
                f"Task {task_id} log index {self._task_log_index_map[task_id]}"
            )
            return self._task_log_index_map[task_id]

    async def execute_workflow(
        self,
        node: BaseOperator,
        call_data: Optional[CALL_DATA] = None,
        streaming_call: bool = False,
        exist_dag_ctx: Optional[DAGContext] = None,
        dag_variables: Optional[DAGVariables] = None,
    ) -> DAGContext:
        """以当前进程的本地 runner 从目标算子递归执行其上游 DAG。

        Args:
            node: 本次执行的目标算子，通常是 DAG 的叶子节点。
            call_data: 绑定到目标节点的调用参数。
            streaming_call: 标记本次调用是否采用流式语义。
            exist_dag_ctx: 子图复用的既有上下文；提供时复用节点输出与共享数据。
            dag_variables: 本次执行变量；与既有上下文合并时优先保留本参数值。

        Returns:
            DAGContext: 含节点输出、共享变量和执行状态的本地 DAG 上下文。

        异常与副作用：算子异常沿调用链传播；非流式顶层 DAG 完成后触发 DAG 收尾。
        该 runner 递归执行尚未缓存输出的上游节点，当前按顺序等待上游，不负责持久
        队列、跨进程调度、重试、租约或取消恢复，不能据此推断为分布式执行器。
        """
        # Save node output
        # dag = node.dag
        job_manager = JobManager.build_from_end_node(node, call_data)
        if not exist_dag_ctx:
            # Create DAG context
            node_outputs: Dict[str, TaskContext] = {}
            share_data: Dict[str, Any] = {}
            event_loop_task_id = id(asyncio.current_task())
        else:
            # Share node output with exist dag context
            node_outputs = exist_dag_ctx._node_to_outputs
            share_data = exist_dag_ctx._share_data
            event_loop_task_id = exist_dag_ctx._event_loop_task_id
            if dag_variables and exist_dag_ctx._dag_variables:
                # Merge dag variables, prefer the `dag_variables` in the parameter
                dag_variables = dag_variables.merge(exist_dag_ctx._dag_variables)
        if node.dag and not dag_variables and node.dag._default_dag_variables:
            # Use default dag variables if not set
            dag_variables = node.dag._default_dag_variables
        dag_ctx = DAGContext(
            event_loop_task_id=event_loop_task_id,
            node_to_outputs=node_outputs,
            share_data=share_data,
            streaming_call=streaming_call,
            node_name_to_ids=job_manager._node_name_to_ids,
            dag_variables=dag_variables,
        )
        # if node.dag:
        #     self._running_dag_ctx[node.dag.dag_id] = dag_ctx
        logger.info(
            f"Begin run workflow from end operator, id: {node.node_id}, runner: {self}"
        )
        logger.debug(f"Node id {node.node_id}, call_data: {call_data}")
        skip_node_ids: Set[str] = set()
        system_app: Optional[SystemApp] = DAGVar.get_current_system_app()

        if node.dag:
            # Save dag context
            await node.dag._save_dag_ctx(dag_ctx)
        await job_manager.before_dag_run()

        with root_tracer.start_span(
            "dbgpt.awel.workflow.run_workflow",
            metadata={
                "exist_dag_ctx": exist_dag_ctx is not None,
                "event_loop_task_id": event_loop_task_id,
                "streaming_call": streaming_call,
                "awel_node_id": node.node_id,
                "awel_node_name": node.node_name,
            },
        ):
            await self._execute_node(
                job_manager, node, dag_ctx, node_outputs, skip_node_ids, system_app
            )
        if not streaming_call and node.dag and exist_dag_ctx is None:
            # streaming call not work for dag end
            # if exist_dag_ctx is not None, it means current dag is a sub dag
            await node.dag._after_dag_end(dag_ctx._event_loop_task_id)
        # if node.dag:
        #     del self._running_dag_ctx[node.dag.dag_id]
        return dag_ctx

    async def _execute_node(
        self,
        job_manager: JobManager,
        node: BaseOperator,
        dag_ctx: DAGContext,
        node_outputs: Dict[str, TaskContext],
        skip_node_ids: Set[str],
        system_app: Optional[SystemApp],
    ):
        """递归执行单个算子及其依赖，并记录任务状态和分支跳过结果。

        同一 `node_id` 已有输出时直接复用；否则先按 `upstream` 顺序递归运行依赖，
        再构造输入和 task context，注入 SystemApp 并调用算子的 `_run`。分支算子会
        根据 task metadata 登记需要跳过的下游节点；算子异常会将当前任务置为失败并
        向上传播，后续依赖不会执行。

        Args:
            job_manager: 为节点提供调用数据和本次运行信息的管理器。
            node: 当前待执行算子。
            dag_ctx: 共享 DAG 上下文。
            node_outputs: 节点 ID 到 TaskContext 的执行结果缓存。
            skip_node_ids: 分支决策产生的跳过节点集合。
            system_app: 可选的系统组件容器，缺失于节点时注入。

        副作用：更新共享结果/任务状态，写日志与 tracing span，并运行算子定义的外部操作。
        并行调度与权限判断由其他层负责；此方法不检查 workspace 或节点 allowlist。
        """
        # Skip run node
        if node.node_id in node_outputs:
            return

        # Run all upstream nodes
        # TODO: run in parallel, there are some code to be changed:
        #  dag_ctx.set_current_task_context(task_ctx)
        for upstream_node in node.upstream:
            if isinstance(upstream_node, BaseOperator):
                await self._execute_node(
                    job_manager,
                    upstream_node,
                    dag_ctx,
                    node_outputs,
                    skip_node_ids,
                    system_app,
                )

        inputs = [
            node_outputs[upstream_node.node_id] for upstream_node in node.upstream
        ]
        input_ctx = DefaultInputContext(inputs)
        # Log task, get log index(plus 1 every time)
        log_index = await self._log_task(node.node_id)
        task_ctx: DefaultTaskContext = DefaultTaskContext(
            node.node_id, TaskState.INIT, task_output=None, log_index=log_index
        )
        current_call_data = job_manager.get_call_data_by_id(node.node_id)
        if current_call_data:
            task_ctx.set_call_data(current_call_data)

        task_ctx.set_task_input(input_ctx)
        dag_ctx.set_current_task_context(task_ctx)
        task_ctx.set_current_state(TaskState.RUNNING)

        if node.node_id in skip_node_ids:
            task_ctx.set_current_state(TaskState.SKIP)
            task_ctx.set_task_output(SimpleTaskOutput(SKIP_DATA))
            node_outputs[node.node_id] = task_ctx
            return
        try:
            logger.debug(
                f"Begin run operator, node id: {node.node_id}, node name: "
                f"{node.node_name}, cls: {node}"
            )
            if system_app is not None and node.system_app is None:
                node.set_system_app(system_app)

            run_metadata = {
                "awel_node_id": node.node_id,
                "awel_node_name": node.node_name,
                "awel_node_type": str(node),
                "state": TaskState.RUNNING.value,
                "task_log_id": task_ctx.log_id,
            }
            with root_tracer.start_span(
                "dbgpt.awel.workflow.run_operator", metadata=run_metadata
            ) as span:
                await node._run(dag_ctx, task_ctx.log_id)
                node_outputs[node.node_id] = dag_ctx.current_task_context
                task_ctx.set_current_state(TaskState.SUCCESS)

                run_metadata["skip_node_ids"] = ",".join(skip_node_ids)
                run_metadata["state"] = TaskState.SUCCESS.value
                span.metadata = run_metadata

            if isinstance(node, BranchOperator):
                skip_nodes = task_ctx.metadata.get("skip_node_names", [])
                logger.debug(
                    f"Current is branch operator, skip node names: {skip_nodes}"
                )
                _skip_current_downstream_by_node_name(node, skip_nodes, skip_node_ids)
        except Exception as e:
            msg = traceback.format_exc()
            logger.info(
                f"Run operator {type(node)}({node.node_id}) error, error message: {msg}"
            )
            task_ctx.set_current_state(TaskState.FAILED)
            raise e


def _skip_current_downstream_by_node_name(
    branch_node: BranchOperator, skip_nodes: List[str], skip_node_ids: Set[str]
):
    """根据分支节点的输出标记递归登记应跳过的下游节点。

    先收集名称命中或已登记的直接子节点，再批量写入跳过集合，确保 Join 等共享
    下游节点能看到完整的已跳过父节点集合；随后继续向这些节点的下游传播。

    Args:
        branch_node: 已执行完成并产出分支选择 metadata 的分支算子。
        skip_nodes: 分支算子 metadata 中声明跳过的节点名称。
        skip_node_ids: 本次 DAG 运行共享的跳过节点 ID 集合，会被原地更新。

    副作用：递归更新 `skip_node_ids` 并记录跳过日志；不执行节点，也不控制并发。
    """
    if not skip_nodes:
        return
    nodes_to_skip = []
    for child in branch_node.downstream:
        child = cast(BaseOperator, child)
        if child.node_name in skip_nodes or child.node_id in skip_node_ids:
            logger.info(f"Skip node name {child.node_name}, node id {child.node_id}")
            nodes_to_skip.append(child)

    # Pre-register all direct skip candidates so that shared downstream nodes
    # (e.g. JoinOperator) can see the full set of skipped parents before deciding
    # whether they themselves should be skipped.
    for node in nodes_to_skip:
        if node.can_skip_in_branch():
            skip_node_ids.add(node.node_id)

    # Now recurse into each candidate's downstream.
    for node in nodes_to_skip:
        for child in node.downstream:
            child = cast(BaseOperator, child)
            _skip_downstream_by_id(child, skip_node_ids)


def _skip_downstream_by_id(node: BaseOperator, skip_node_ids: Set[str]):
    if not node.can_skip_in_branch():
        # Current node cannot be skipped, so leave it and its downstream intact.
        return
    if node.node_id in skip_node_ids:
        # Already marked for skipping; avoid redundant traversal.
        return
    # A node with multiple upstream parents (e.g. JoinOperator) should only be
    # skipped when ALL of its parents are being skipped.  If any parent is still
    # active, this node must remain active to consume that parent's output.
    for parent in node.upstream:
        if isinstance(parent, BaseOperator) and parent.node_id not in skip_node_ids:
            return
    skip_node_ids.add(node.node_id)
    for child in node.downstream:
        child = cast(BaseOperator, child)
        _skip_downstream_by_id(child, skip_node_ids)
