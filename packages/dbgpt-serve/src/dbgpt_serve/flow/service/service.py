import json
import logging
import os
from typing import AsyncIterator, Dict, List, Optional, Tuple, cast

import schedule
from fastapi import HTTPException

from dbgpt._private.config import Config
from dbgpt._private.pydantic import model_to_json
from dbgpt.agent import AgentDummyTrigger
from dbgpt.component import SystemApp
from dbgpt.core.awel import DAG, BaseOperator, CommonLLMHttpRequestBody
from dbgpt.core.awel.flow.flow_factory import (
    FlowCategory,
    FlowFactory,
    State,
    fill_flow_panel,
)
from dbgpt.core.awel.trigger.http_trigger import CommonLLMHttpTrigger
from dbgpt.core.awel.util.chat_util import (
    _v1_create_completion_response,
    is_chat_flow_type,
    safe_chat_stream_with_dag_task,
    safe_chat_with_dag_task,
)
from dbgpt.core.interface.llm import ModelOutput
from dbgpt.core.schema.api import (
    ChatCompletionResponseStreamChoice,
    ChatCompletionStreamResponse,
    DeltaMessage,
)
from dbgpt.storage.metadata import BaseDao
from dbgpt.storage.metadata._base_dao import QUERY_SPEC
from dbgpt.util.dbgpts.loader import DBGPTsLoader
from dbgpt.util.pagination_utils import PaginationResult
from dbgpt_serve.core import BaseService, blocking_func_to_async

from ..api.schemas import FlowDebugRequest, FlowInfo, ServeRequest, ServerResponse
from ..config import SERVE_SERVICE_COMPONENT_NAME, ServeConfig
from ..models.models import ServeDao, ServeEntity
from .compat_service import register_compat_flow

logger = logging.getLogger(__name__)

CFG = Config()


class Service(BaseService[ServeEntity, ServeRequest, ServerResponse]):
    """The service class for Flow"""

    name = SERVE_SERVICE_COMPONENT_NAME

    def __init__(
        self, system_app: SystemApp, config: ServeConfig, dao: Optional[ServeDao] = None
    ):
        self._system_app = None
        self._serve_config: ServeConfig = config
        self._dao: ServeDao = dao
        self._flow_factory: FlowFactory = FlowFactory()
        self._dbgpts_loader: Optional[DBGPTsLoader] = None

        super().__init__(system_app)

    def init_app(self, system_app: SystemApp) -> None:
        """Initialize the service

        Args:
            system_app (SystemApp): The system app
        """
        super().init_app(system_app)

        self._dao = self._dao or ServeDao(self._serve_config)
        self._system_app = system_app
        self._dbgpts_loader = system_app.get_component(
            DBGPTsLoader.name,
            DBGPTsLoader,
            or_register_component=DBGPTsLoader,
            load_dbgpts_interval=self._serve_config.load_dbgpts_interval,
        )

    def before_start(self):
        """Execute before the application starts"""
        super().before_start()
        # Register the compat flow at the beginning
        register_compat_flow()
        self._pre_load_dag_from_db()
        self._pre_load_dag_from_dbgpts()

    def after_start(self):
        """Execute after the application starts"""
        self.load_dag_from_db()
        self.load_dag_from_dbgpts(is_first_load=True)
        schedule.every(self._serve_config.load_dbgpts_interval).seconds.do(
            self.load_dag_from_dbgpts
        )

    @property
    def dao(self) -> BaseDao[ServeEntity, ServeRequest, ServerResponse]:
        """Returns the internal DAO."""
        return self._dao

    @property
    def dbgpts_loader(self) -> DBGPTsLoader:
        """Returns the internal DBGPTsLoader."""
        if self._dbgpts_loader is None:
            raise ValueError("DBGPTsLoader is not initialized")
        return self._dbgpts_loader

    @property
    def config(self) -> ServeConfig:
        """Returns the internal ServeConfig."""
        return self._serve_config

    def create(self, request: ServeRequest) -> ServerResponse:
        """仅按通用服务语义把 Flow 请求写入 DAO，不构建或注册 AWEL DAG。

        Args:
            request: 已完成基本 schema 校验、准备持久化的 Flow 定义。

        Returns:
            ServerResponse: DAO 保存后转换得到的 Flow 响应对象。

        注意：这是 `BaseService.create` 的等价委托，不适用于需要立即构建
        或部署 DAG 的入口；前端创建流程应调用 `create_and_save_dag`。
        本方法和 DAO 当前不执行 workspace 资源授权，调用方须先完成可信鉴权。
        """
        return super().create(request)

    def create_and_save_dag(
        self, request: ServeRequest, save_failed_flow: bool = False
    ) -> ServerResponse:
        """从画布请求构建 DAG、写入 Flow 记录，并按状态注册运行图。

        Args:
            request: 包含 JSON Flow 描述或已构造 DAG 的请求。
            save_failed_flow: 为真时将构建/注册失败记录为 `LOAD_FAILED`；
                为假时构建失败直接抛错，注册失败会删除刚创建的 Flow 记录。

        Returns:
            ServerResponse: DAO 查询得到的持久化 Flow 响应。

        Raises:
            ValueError: Flow 图构建失败且未启用失败记录时抛出。
            Exception: DAG 注册失败时按上述回滚分支处理后重新抛出。

        副作用：写入 DAO、更新状态及进程内 DAG registry。DAO 写入与 registry
        注册并非跨系统原子事务；多实例一致性、workspace 授权和发布审批均未由本方法保证。
        """
        try:
            # Build DAG from request
            if request.define_type == "json":
                dag = self._flow_factory.build(request)
            else:
                dag = request.flow_dag
            request.dag_id = dag.dag_id
            # Save DAG to storage
            request.flow_category = self._parse_flow_category(dag)
        except Exception as e:
            if save_failed_flow:
                request.state = State.LOAD_FAILED
                request.error_message = str(e)
                request.dag_id = ""
                return self.dao.create(request)
            else:
                raise ValueError(
                    f"Create DAG {request.name} error, define_type: "
                    f"{request.define_type}, error: {str(e)}"
                ) from e
        self.dao.create(request)
        # Query from database
        res = self.get({"uid": request.uid})

        state = request.state
        try:
            if state == State.DEPLOYED:
                # Register the DAG
                self.dag_manager.register_dag(dag, request.uid)
                # Update state to RUNNING
                request.state = State.RUNNING
                request.error_message = ""
                self.dao.update({"uid": request.uid}, request)
            else:
                logger.info(f"Flow state is {state}, skip register DAG")
        except Exception as e:
            logger.warning(f"Register DAG({dag.dag_id}) error: {str(e)}")
            if save_failed_flow:
                request.state = State.LOAD_FAILED
                request.error_message = f"Register DAG error: {str(e)}"
                request.dag_id = ""
                self.dao.update({"uid": request.uid}, request)
            else:
                # Rollback
                self.delete(request.uid)
            raise e
        return res

    def _pre_load_dag_from_db(self):
        """Pre load DAG from db"""
        entities = self.dao.get_list({})
        for entity in entities:
            try:
                self._flow_factory.pre_load_requirements(entity)
            except Exception as e:
                logger.warning(
                    f"Pre load requirements for DAG({entity.name}, {entity.dag_id}) "
                    f"from db error: {str(e)}"
                )

    def load_dag_from_db(self):
        """启动恢复数据库中的 JSON Flow，并把运行态 DAG 注册到本进程。

        遍历 DAO 返回的实体，逐条重建图；`DEPLOYED`、`RUNNING` 以及特定旧版本
        的 `INITIALIZING` 流程会进入当前进程的 DAG registry，随后数据库状态更新为
        `RUNNING`。单条加载失败只记日志并继续处理其他流程。

        注意：当前扫描未在这里附加 workspace 过滤或全局发布版本锁；registry
        是进程内状态，多副本注册和失败重试不具备分布式一致性保证。
        """
        entities = self.dao.get_list({})
        for entity in entities:
            try:
                if entity.define_type != "json":
                    continue
                dag = self._flow_factory.build(entity)
                if entity.state in [State.DEPLOYED, State.RUNNING] or (
                    entity.version == "0.1.0" and entity.state == State.INITIALIZING
                ):
                    # Register the DAG
                    self.dag_manager.register_dag(dag, entity.uid)
                    # Update state to RUNNING
                    entity.state = State.RUNNING
                    entity.error_message = ""
                    self.dao.update({"uid": entity.uid}, entity)
            except Exception as e:
                logger.warning(
                    f"Load DAG({entity.name}, {entity.dag_id}) from db error: {str(e)}"
                )

    def _pre_load_dag_from_dbgpts(self):
        """Pre load DAG from dbgpts"""
        flows = self.dbgpts_loader.get_flows()
        for flow in flows:
            try:
                if flow.define_type == "json":
                    self._flow_factory.pre_load_requirements(flow)
            except Exception as e:
                logger.warning(
                    f"Pre load requirements for DAG({flow.name}) from "
                    f"dbgpts error: {str(e)}"
                )

    def load_dag_from_dbgpts(self, is_first_load: bool = False):
        """Load DAG from dbgpts"""
        flows = self.dbgpts_loader.get_flows()
        for flow in flows:
            try:
                if flow.define_type == "python" and flow.flow_dag is None:
                    continue
                # Set state to DEPLOYED
                flow.state = State.DEPLOYED
                exist_inst = self.dao.get_one({"name": flow.name})
                if not exist_inst:
                    self.create_and_save_dag(flow, save_failed_flow=True)
                elif is_first_load or exist_inst.state != State.RUNNING:
                    # TODO check version, must be greater than the exist one
                    flow.uid = exist_inst.uid
                    self.update_flow(flow, check_editable=False, save_failed_flow=True)
            except Exception as e:
                import traceback

                message = traceback.format_exc()
                logger.warning(
                    f"Load DAG {flow.name} from dbgpts error: {str(e)}, detail: "
                    f"{message}"
                )

    def update_flow(
        self,
        request: ServeRequest,
        check_editable: bool = True,
        save_failed_flow: bool = False,
    ) -> ServerResponse:
        """重建并替换指定 Flow 的持久化定义及其已注册 DAG。

        Args:
            request: 包含 Flow 标识和新图定义的请求。
            check_editable: 为真时拒绝更新不可编辑记录。
            save_failed_flow: 为真时把图加载失败记录为 `LOAD_FAILED`。

        Returns:
            ServerResponse: 替换后从 DAO 返回的 Flow 响应。

        Raises:
            HTTPException: 流程不存在、不可编辑或状态变更非法时抛出。
            Exception: 图构建、DAO 更新或重新注册失败时传播。

        副作用：先更新 DAO、移除旧 registry 项，再调用创建/注册路径；异常时仅当
        旧记录原状态为 `RUNNING` 才尝试重新创建它。其他状态没有等价恢复保证。
        此流程不提供数据库与进程内 registry 的原子提交，也不执行 workspace
        授权或版本审批，不能视作企业发布流程。
        """
        new_state = State.DEPLOYED
        try:
            # Try to build the dag from the request
            if request.define_type == "json":
                dag = self._flow_factory.build(request)
            else:
                dag = request.flow_dag
            request.flow_category = self._parse_flow_category(dag)
        except Exception as e:
            if save_failed_flow:
                request.state = State.LOAD_FAILED
                request.error_message = str(e)
                request.dag_id = ""
                return self.dao.update({"uid": request.uid}, request)
            else:
                raise e
        # Build the query request from the request
        query_request = {"uid": request.uid}
        inst = self.get(query_request)
        if not inst:
            raise HTTPException(status_code=404, detail=f"Flow {request.uid} not found")
        if check_editable and not inst.editable:
            raise HTTPException(
                status_code=403, detail=f"Flow {request.uid} is not editable"
            )
        old_state = inst.state
        if not State.can_change_state(old_state, new_state):
            raise HTTPException(
                status_code=400,
                detail=f"Flow {request.uid} state can't change from {old_state} to "
                f"{new_state}",
            )
        old_data: Optional[ServerResponse] = None
        try:
            update_obj = self.dao.update(query_request, update_request=request)
            old_data = self.delete(request.uid)
            old_data.state = old_state
            if not old_data:
                raise HTTPException(
                    status_code=404, detail=f"Flow detail {request.uid} not found"
                )
            update_obj.flow_dag = request.flow_dag
            return self.create_and_save_dag(update_obj)
        except Exception as e:
            if old_data and old_data.state == State.RUNNING:
                # Old flow is running, try to recover it
                # first set the state to DEPLOYED
                old_data.state = State.DEPLOYED
                self.create_and_save_dag(old_data)
            raise e

    def get(self, request: QUERY_SPEC) -> Optional[ServerResponse]:
        """Get a Flow entity

        Args:
            request (ServeRequest): The request

        Returns:
            ServerResponse: The response
        """
        # TODO: implement your own logic here
        # Build the query request from the request
        query_request = request
        flow = self.dao.get_one(query_request)
        if flow:
            fill_flow_panel(flow)
            metadata = self.dag_manager.get_dag_metadata(
                flow.dag_id, alias_name=flow.uid
            )
            if metadata:
                flow.metadata = metadata.to_dict()
        return flow

    def delete(self, uid: str) -> Optional[ServerResponse]:
        """Delete a Flow entity

        Args:
            uid (str): The uid

        Returns:
            ServerResponse: The data after deletion
        """

        # TODO: implement your own logic here
        # Build the query request from the request
        query_request = {"uid": uid}
        inst = self.get(query_request)
        if inst is None:
            raise HTTPException(status_code=404, detail=f"Flow {uid} not found")
        if inst.state == State.RUNNING and not inst.dag_id:
            raise HTTPException(
                status_code=404, detail=f"Running flow {uid}'s dag id not found"
            )
        try:
            if inst.dag_id:
                self.dag_manager.unregister_dag(inst.dag_id)
        except Exception as e:
            logger.warning(f"Unregister DAG({inst.dag_id}) error: {str(e)}")
        self.dao.delete(query_request)
        return inst

    def get_list(self, request: ServeRequest) -> List[ServerResponse]:
        """Get a list of Flow entities

        Args:
            request (ServeRequest): The request

        Returns:
            List[ServerResponse]: The response
        """
        # TODO: implement your own logic here
        # Build the query request from the request
        query_request = request
        return self.dao.get_list(query_request)

    def get_list_by_page(
        self, request: QUERY_SPEC, page: int, page_size: int
    ) -> PaginationResult[ServerResponse]:
        """Get a list of Flow entities by page

        Args:
            request (ServeRequest): The request
            page (int): The page number
            page_size (int): The page size

        Returns:
            List[ServerResponse]: The response
        """
        page_result = self.dao.get_list_page(
            request, page, page_size, desc_order_column=ServeEntity.gmt_modified.name
        )
        for item in page_result.items:
            metadata = self.dag_manager.get_dag_metadata(
                item.dag_id, alias_name=item.uid
            )
            if metadata:
                item.metadata = metadata.to_dict()
        return page_result

    def get_flow_templates(
        self,
        user_name: Optional[str] = None,
        sys_code: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> PaginationResult[Dict]:
        """Get a list of Flow templates

        Args:
            user_name (Optional[str]): The user name
            sys_code (Optional[str]): The system code
            page (int): The page number
            page_size (int): The page size
        Returns:
            List[ServerResponse]: The response
        """
        user_lang = self._system_app.config.get_current_lang(default="en")
        local_file_templates = _get_flow_templates_from_files(user_lang)
        templates = []
        for _, t in local_file_templates:
            fill_flow_panel(t)
            templates.append(t.to_dict())
        return PaginationResult.build_from_all(templates, page, page_size)

    async def chat_stream_flow_str(
        self, flow_uid: str, request: CommonLLMHttpRequestBody
    ) -> AsyncIterator[str]:
        """Stream chat with the AWEL flow.

        Args:
            flow_uid (str): The flow uid
            request (CommonLLMHttpRequestBody): The request
        """
        # Must be non-incremental
        request.incremental = False
        async for output in self.safe_chat_stream_flow(flow_uid, request):
            text = output.gen_text_with_thinking()
            if text:
                text = text.replace("\n", "\\n")
            if output.error_code != 0:
                yield _v1_create_completion_response(
                    f"[SERVER_ERROR]{text}",
                    None,
                    model_name=request.model,
                    stream_id=request.conv_uid,
                )
                break
            else:
                yield _v1_create_completion_response(
                    text, None, model_name=request.model, stream_id=request.conv_uid
                )

    async def chat_stream_openai(
        self, flow_uid: str, request: CommonLLMHttpRequestBody
    ) -> AsyncIterator[str]:
        conv_uid = request.conv_uid
        choice_data = ChatCompletionResponseStreamChoice(
            index=0,
            delta=DeltaMessage(role="assistant"),
            finish_reason=None,
        )
        chunk = ChatCompletionStreamResponse(
            id=conv_uid, choices=[choice_data], model=request.model
        )
        json_data = model_to_json(chunk, exclude_unset=True, ensure_ascii=False)

        yield f"data: {json_data}\n\n"

        request.incremental = True
        async for output in self.safe_chat_stream_flow(flow_uid, request):
            if not output.success:
                yield f"data: {json.dumps(output.to_dict(), ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"
                return
            text = output.text if output.has_text else ""
            choice_data = ChatCompletionResponseStreamChoice(
                index=0,
                delta=DeltaMessage(
                    role="assistant",
                    content=text,
                    reasoning_content=output.thinking_text,
                ),
            )
            chunk = ChatCompletionStreamResponse(
                id=conv_uid,
                choices=[choice_data],
                model=request.model,
            )
            json_data = model_to_json(chunk, exclude_unset=True, ensure_ascii=False)
            yield f"data: {json_data}\n\n"
        yield "data: [DONE]\n\n"

    async def safe_chat_flow(
        self, flow_uid: str, request: CommonLLMHttpRequestBody
    ) -> ModelOutput:
        """调用已注册 Flow 的唯一叶子算子，并把异常转换为模型错误结果。

        Args:
            flow_uid: 持久化 Flow 的 UID。
            request: 对话输入、模型参数及增量输出选项。

        Returns:
            ModelOutput: AWEL 输出，或带错误码和异常文本的失败结果。

        注意：异常不会由该包装方法重新抛出；Flow 查询只按 UID，当前实现没有
        在此处校验调用者、workspace、发布版本或其节点资源权限。
        """
        incremental = request.incremental
        try:
            task = await self._get_callable_task(flow_uid)
            return await safe_chat_with_dag_task(task, request)
        except HTTPException as e:
            return ModelOutput(error_code=1, text=e.detail, incremental=incremental)
        except Exception as e:
            return ModelOutput(error_code=1, text=str(e), incremental=incremental)

    async def safe_chat_stream_flow(
        self, flow_uid: str, request: CommonLLMHttpRequestBody
    ) -> AsyncIterator[ModelOutput]:
        """以异步迭代器逐条转发已注册 Flow 的对话结果。

        Args:
            flow_uid: 持久化 Flow 的 UID。
            request: 对话输入、模型参数及增量输出选项。

        Returns:
            AsyncIterator[ModelOutput]: 逐条输出模型片段；失败时产出错误对象。

        注意：下游迭代器消费时才会继续执行。当前包装会把异常转换为一个错误
        `ModelOutput`；身份、workspace、已发布版本校验须由后续企业授权层补齐。
        """
        incremental = request.incremental
        try:
            task = await self._get_callable_task(flow_uid)
            async for output in safe_chat_stream_with_dag_task(
                task, request, incremental
            ):
                yield output
        except HTTPException as e:
            yield ModelOutput(error_code=1, text=e.detail, incremental=incremental)
        except Exception as e:
            yield ModelOutput(error_code=1, text=str(e), incremental=incremental)

    async def _get_callable_task(
        self,
        flow_uid: str,
    ) -> BaseOperator:
        """从当前进程注册表中解析可供聊天执行的 Flow 叶子算子。

        Returns:
            BaseOperator: 唯一叶子节点，作为 Agent/聊天执行入口。

        Raises:
            HTTPException: Flow UID 不存在，或 DAG 尚未在当前进程注册。
            ValueError: DAG 叶子节点数量不是一个。

        注意：此处仅以 UID 和进程内 dag_id 查找，没有资源所有权、workspace
        或发布版本检查；调用链必须在进入本方法前完成可信认证和授权。
        """
        flow = self.get({"uid": flow_uid})
        if not flow:
            raise HTTPException(status_code=404, detail=f"Flow {flow_uid} not found")
        dag_id = flow.dag_id
        if not dag_id or dag_id not in self.dag_manager.dag_map:
            raise HTTPException(
                status_code=404, detail=f"Flow {flow_uid}'s dag id not found"
            )
        dag = self.dag_manager.dag_map[dag_id]
        # if (
        #     flow.flow_category != FlowCategory.CHAT_FLOW
        #     and self._parse_flow_category(dag) != FlowCategory.CHAT_FLOW
        # ):
        #     raise ValueError(f"Flow {flow_uid} is not a chat flow")
        leaf_nodes = dag.leaf_nodes
        if len(leaf_nodes) != 1:
            raise ValueError("Chat Flow just support one leaf node in dag")
        return cast(BaseOperator, leaf_nodes[0])

    def _parse_flow_category(self, dag: DAG) -> FlowCategory:
        """Parse the flow category

        Args:
            flow_category (str): The flow category

        Returns:
            FlowCategory: The flow category
        """
        from dbgpt.core.awel.flow.base import _get_type_cls

        triggers = dag.trigger_nodes
        leaf_nodes = dag.leaf_nodes
        if (
            not triggers
            or not leaf_nodes
            or len(leaf_nodes) > 1
            or not isinstance(leaf_nodes[0], BaseOperator)
        ):
            return FlowCategory.COMMON

        leaf_node = cast(BaseOperator, leaf_nodes[0])
        if not leaf_node.metadata or not leaf_node.metadata.outputs:
            return FlowCategory.COMMON

        common_http_trigger = False
        agent_trigger = False
        for trigger in triggers:
            if isinstance(trigger, CommonLLMHttpTrigger):
                common_http_trigger = True
                break

            if isinstance(trigger, AgentDummyTrigger):
                agent_trigger = True
                break

        output = leaf_node.metadata.outputs[0]
        try:
            real_class = _get_type_cls(output.type_cls)
            if agent_trigger:
                return FlowCategory.CHAT_AGENT
            elif common_http_trigger and is_chat_flow_type(real_class, is_class=True):
                return FlowCategory.CHAT_FLOW
        except Exception:
            return FlowCategory.COMMON

    async def debug_flow(
        self, request: FlowDebugRequest, default_incremental: Optional[bool] = None
    ) -> AsyncIterator[ModelOutput]:
        """从请求体构建临时 DAG 并以异步结果流执行调试对话。

        Args:
            request: 含临时图定义、聊天请求和可选 Flow 变量的调试载荷。
            default_incremental: 若非空则覆盖请求中的增量输出配置。

        Returns:
            AsyncIterator[ModelOutput]: 依次产出调试结果或错误对象。

        Raises:
            ValueError: 叶子节点不是唯一节点，或请求体类型无效。

        安全边界：临时 DAG 来自调用请求并直接交给 FlowFactory 构造，之后调用
        节点工具；本方法未执行节点白名单、workspace 变量 ACL 或副作用审批，
        不应在未授权的外部入口直接开放。
        """
        from dbgpt.core.awel.dag.dag_manager import _parse_metadata

        dag = await blocking_func_to_async(
            self._system_app,
            self._flow_factory.build,
            request.flow,
        )
        leaf_nodes = dag.leaf_nodes
        if len(leaf_nodes) != 1:
            raise ValueError("Chat Flow just support one leaf node in dag")
        task = cast(BaseOperator, leaf_nodes[0])
        dag_metadata = _parse_metadata(dag)
        # TODO: Run task with variables
        variables = request.variables
        dag_request = request.request

        if isinstance(request.request, CommonLLMHttpRequestBody):
            incremental = request.request.incremental
        elif isinstance(request.request, dict):
            incremental = request.request.get("incremental", False)
        else:
            raise ValueError("Invalid request type")

        if default_incremental is not None:
            incremental = default_incremental

        try:
            async for output in safe_chat_stream_with_dag_task(
                task, dag_request, incremental
            ):
                yield output
        except HTTPException as e:
            yield ModelOutput(error_code=1, text=e.detail, incremental=incremental)
        except Exception as e:
            yield ModelOutput(error_code=1, text=str(e), incremental=incremental)

    async def _wrapper_chat_stream_flow_str(
        self, stream_iter: AsyncIterator[ModelOutput]
    ) -> AsyncIterator[str]:
        async for output in stream_iter:
            text = output.text
            if text:
                text = text.replace("\n", "\\n")
            if output.error_code != 0:
                yield f"data:[SERVER_ERROR]{text}\n\n"
                break
            else:
                yield f"data:{text}\n\n"

    async def get_flow_files(self, flow_uid: str):
        logger.info(f"get_flow_files:{flow_uid}")

        flow = self.get({"uid": flow_uid})
        if not flow:
            logger.warning(f"cant't find flow info!{flow_uid}")
            return None
        package = self.dbgpts_loader.get_flow_package(flow.name)
        if package:
            pkg_path = (
                f"{package.root.replace(CFG.NOTE_BOOK_ROOT + '/', '')}/{package.name}"
            )
            return FlowInfo(
                name=package.name,
                definition_type=package.definition_type,
                description=package.description,
                label=package.label,
                package=package.package,
                package_type=package.package_type,
                root=package.root,
                path=pkg_path,
                version=package.version,
            )
        return None


def _parse_flow_template_from_json(json_dict: dict) -> ServerResponse:
    """Parse the flow from json

    Args:
        json_dict (dict): The json dict

    Returns:
        ServerResponse: The flow
    """
    flow_json = json_dict["flow"]
    flow_json["editable"] = False
    del flow_json["uid"]
    flow_json["state"] = State.INITIALIZING
    flow_json["dag_id"] = None
    return ServerResponse(**flow_json)


def _get_flow_templates_from_files(
    user_lang: str = "en",
) -> List[Tuple[str, ServerResponse]]:
    """Get a list of Flow templates from files"""
    # List files in current directory
    parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    template_dir = os.path.join(parent_dir, "templates", user_lang)
    default_template_dir = os.path.join(parent_dir, "templates", "en")
    if not os.path.exists(template_dir):
        template_dir = default_template_dir
    templates = []
    for root, _, files in os.walk(template_dir):
        for file in files:
            if file.endswith(".json"):
                try:
                    full_path = os.path.join(root, file)
                    with open(full_path, "r") as f:
                        data = json.load(f)
                        templates.append(
                            (full_path, _parse_flow_template_from_json(data))
                        )
                except Exception as e:
                    logger.warning(f"Load template {file} error: {str(e)}")
    return templates
