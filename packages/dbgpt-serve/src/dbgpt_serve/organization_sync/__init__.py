"""企业组织信息同步扩展模块。"""

from dbgpt_serve.organization_sync.contracts import (
    DepartmentRecord,
    OrganizationRecord,
    OrganizationSnapshot,
    UserRecord,
)
from dbgpt_serve.organization_sync.service import OrganizationSyncService

__all__ = [
    "DepartmentRecord",
    "OrganizationRecord",
    "OrganizationSnapshot",
    "OrganizationSyncService",
    "UserRecord",
]
