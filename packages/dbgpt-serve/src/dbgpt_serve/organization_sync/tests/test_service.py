"""企业组织同步预留模块的契约测试。"""

import pytest

from dbgpt_serve.organization_sync.contracts import (
    DepartmentRecord,
    OrganizationRecord,
    OrganizationSnapshot,
    UserRecord,
)
from dbgpt_serve.organization_sync.service import OrganizationSyncService


class InMemoryDirectory:
    """为组织同步测试提供固定的内存目录。"""

    def __init__(self, snapshot: OrganizationSnapshot):
        """保存测试要返回的组织快照。"""
        self.snapshot = snapshot

    def read_snapshot(self) -> OrganizationSnapshot:
        """返回预置的目录快照。"""
        return self.snapshot


def test_preview_counts_valid_snapshot_without_mutating_source():
    """验证预览能统计有效数据，并保持目录内容不变。"""
    snapshot = OrganizationSnapshot(
        organizations=[OrganizationRecord("org-1", "长客股份")],
        departments=[DepartmentRecord("dep-1", "org-1", "研发部")],
        users=[
            UserRecord("u-1", "alice", "Alice", ["dep-1"]),
            UserRecord("u-2", "bob", "Bob", ["dep-1"], active=False),
        ],
        source_version="v1",
    )
    preview = OrganizationSyncService(InMemoryDirectory(snapshot)).preview()

    assert preview.source_version == "v1"
    assert preview.organization_count == 1
    assert preview.department_count == 1
    assert preview.active_user_count == 1
    assert preview.inactive_user_count == 1
    assert len(snapshot.users) == 2


@pytest.mark.parametrize(
    "snapshot, expected_error",
    [
        (
            OrganizationSnapshot(
                organizations=[
                    OrganizationRecord("org-1", "一部"),
                    OrganizationRecord("org-1", "重复"),
                ]
            ),
            "组织外部标识重复",
        ),
        (
            OrganizationSnapshot(
                organizations=[OrganizationRecord("org-1", "一部")],
                departments=[DepartmentRecord("dep-1", "missing", "研发部")],
            ),
            "引用了未知组织",
        ),
        (
            OrganizationSnapshot(
                organizations=[OrganizationRecord("org-1", "一部")],
                departments=[DepartmentRecord("dep-1", "org-1", "研发部")],
                users=[UserRecord("u-1", "alice", "Alice", ["missing"])],
            ),
            "引用了未知部门",
        ),
    ],
)
def test_preview_rejects_inconsistent_snapshot(snapshot, expected_error):
    """验证组织关系不完整或外部标识重复时拒绝预览。"""
    with pytest.raises(ValueError, match=expected_error):
        OrganizationSyncService(InMemoryDirectory(snapshot)).preview()
