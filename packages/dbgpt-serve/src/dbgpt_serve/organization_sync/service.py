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
        """读取上游快照并校验标识唯一性及组织关系完整性。"""
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
        """生成只读预览，供未来管理页面展示同步规模。"""
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
        """校验外部标识非空且唯一，并返回标识集合。"""
        collected = list(values)
        if any(not value or not value.strip() for value in collected):
            raise ValueError(f"{label}外部标识不能为空")
        if len(collected) != len(set(collected)):
            raise ValueError(f"{label}外部标识重复")
        return set(collected)
