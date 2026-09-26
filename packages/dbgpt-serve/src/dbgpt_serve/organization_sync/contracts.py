"""组织目录同步的数据契约；不绑定具体企业 IdP 或持久化实现。"""

from dataclasses import dataclass, field
from typing import Optional, Protocol, Sequence


@dataclass(frozen=True)
class OrganizationRecord:
    """描述一个来自企业目录的组织单元。"""

    external_id: str
    name: str
    parent_external_id: Optional[str] = None
    attributes: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class DepartmentRecord:
    """描述一个部门，并关联其所属组织单元。"""

    external_id: str
    organization_external_id: str
    name: str
    parent_external_id: Optional[str] = None
    attributes: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class UserRecord:
    """描述一个企业用户及其上游稳定标识。"""

    external_id: str
    username: str
    display_name: str
    department_external_ids: Sequence[str] = ()
    active: bool = True
    attributes: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class OrganizationSnapshot:
    """承载一次完整、可校验的组织目录快照。"""

    organizations: Sequence[OrganizationRecord] = ()
    departments: Sequence[DepartmentRecord] = ()
    users: Sequence[UserRecord] = ()
    source_version: Optional[str] = None


class OrganizationDirectoryAdapter(Protocol):
    """企业目录适配器契约，后续可由内网 LDAP/HR 系统实现。"""

    def read_snapshot(self) -> OrganizationSnapshot:
        """读取一个完整目录快照；凭据应由部署密钥系统提供。"""
        ...


class OrganizationStore(Protocol):
    """平台侧组织存储契约，后续接入受控数据库事务实现。"""

    def read_snapshot(self) -> OrganizationSnapshot:
        """读取平台当前的组织、部门和用户映射。"""
        ...

    def replace_snapshot(self, snapshot: OrganizationSnapshot) -> None:
        """在调用方事务中原子替换组织快照。"""
        ...
