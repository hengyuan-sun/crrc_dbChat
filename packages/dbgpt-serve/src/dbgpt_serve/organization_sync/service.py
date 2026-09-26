"""企业组织快照校验与差异预览服务。"""

from dataclasses import dataclass
from typing import Iterable, Optional

from dbgpt_serve.organization_sync.contracts import (
    OrganizationDirectoryAdapter,
    OrganizationSnapshot,
)


@dataclass(frozen=True)
class OrganizationSyncPreview:
    """返回同步预览摘要，不执行任何持久化或账号变更。"""

    source_version: Optional[str]
    organization_count: int
    department_count: int
    active_user_count: int
    inactive_user_count: int


class OrganizationSyncService:
    """提供目录快照读取、完整性校验与只读预览。"""

    def __init__(self, directory: OrganizationDirectoryAdapter):
        """初始化组织同步服务并注入企业目录适配器。"""
        self._directory = directory

    def read_and_validate(self) -> OrganizationSnapshot:
        """读取目录快照并校验外部标识唯一性及组织关系引用完整性。

        Returns:
            OrganizationSnapshot: 通过本地完整性检查的原始快照，不会改写字段。

        Raises:
            ValueError: 外部 ID 为空/重复，或父组织、归属部门、用户部门引用未知时抛出。
            Exception: 目录适配器读取失败时由适配器异常向上抛出。

        本方法只检查快照内部引用，不验证组织树环、自引用、跨组织父子关系、版本
        游标或身份权限；不写数据库、不停用账号、不授予角色，也不产生审计记录。
        """
        snapshot = self._directory.read_snapshot()
        organization_ids = self._unique_ids(
            (item.external_id for item in snapshot.organizations), "组织"
        )
        department_ids = self._unique_ids(
            (item.external_id for item in snapshot.departments), "部门"
        )
        self._unique_ids((item.external_id for item in snapshot.users), "用户")

        for organization in snapshot.organizations:
            if (
                organization.parent_external_id
                and organization.parent_external_id not in organization_ids
            ):
                raise ValueError(f"组织 {organization.external_id} 引用了未知上级组织")

        for department in snapshot.departments:
            if department.organization_external_id not in organization_ids:
                raise ValueError(
                    f"部门 {department.external_id} 引用了未知组织"
                )
            if (
                department.parent_external_id
                and department.parent_external_id not in department_ids
            ):
                raise ValueError(f"部门 {department.external_id} 引用了未知上级部门")

        for user in snapshot.users:
            missing = set(user.department_external_ids) - department_ids
            if missing:
                raise ValueError(
                    f"用户 {user.external_id} 引用了未知部门：{', '.join(sorted(missing))}"
                )
        return snapshot

    def preview(self) -> OrganizationSyncPreview:
        """校验当前目录快照并生成组织、部门和账号数量的只读预览。

        Returns:
            OrganizationSyncPreview: 含目录版本和各类记录数量的汇总值。

        Raises:
            ValueError: 快照完整性校验失败。
            Exception: 目录读取失败。

        此预览可重复调用，但没有批次幂等键或快照持久化；它不提交同步、不修改
        成员关系或角色，也不代表预览后数据未发生变化。
        """
        snapshot = self.read_and_validate()
        return OrganizationSyncPreview(
            source_version=snapshot.source_version,
            organization_count=len(snapshot.organizations),
            department_count=len(snapshot.departments),
            active_user_count=sum(user.active for user in snapshot.users),
            inactive_user_count=sum(not user.active for user in snapshot.users),
        )

    @staticmethod
    def _unique_ids(values: Iterable[str], label: str) -> set[str]:
        """拒绝空值或重复的目录外部 ID，并返回唯一标识集合。

        Args:
            values: 同一实体类型的外部标识序列。
            label: 用于构造中文校验错误的实体名称。

        Returns:
            set[str]: 输入中的唯一标识集合。

        Raises:
            ValueError: 任一标识为空白，或输入含重复值。
        """
        collected = list(values)
        if any(not value or not value.strip() for value in collected):
            raise ValueError(f"{label}外部标识不能为空")
        if len(collected) != len(set(collected)):
            raise ValueError(f"{label}外部标识重复")
        return set(collected)
