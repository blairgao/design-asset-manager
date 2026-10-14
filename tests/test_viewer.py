import uuid

import pytest
from sqlalchemy import select

from dam.models import Asset, FirmRole, ProjectRole
from dam.viewer import Forbidden, Viewer


def _viewer(role: FirmRole, **project_roles) -> Viewer:
    return Viewer(
        user_id=uuid.uuid4(),
        firm_id=uuid.uuid4(),
        role=role,
        project_roles={uuid.UUID(k): v for k, v in project_roles.items()},
    )


def test_staff_sees_every_project():
    v = _viewer(FirmRole.staff)
    assert v.can_read_project(uuid.uuid4())
    assert v.can_edit_project(uuid.uuid4())
    v.require_staff()


def test_client_scoped_to_granted_projects():
    p_view, p_edit = uuid.uuid4(), uuid.uuid4()
    v = Viewer(
        user_id=uuid.uuid4(),
        firm_id=uuid.uuid4(),
        role=FirmRole.client,
        project_roles={p_view: ProjectRole.viewer, p_edit: ProjectRole.editor},
    )
    assert v.can_read_project(p_view) and v.can_read_project(p_edit)
    assert not v.can_read_project(uuid.uuid4())
    assert v.can_edit_project(p_edit) and not v.can_edit_project(p_view)
    with pytest.raises(Forbidden):
        v.require_edit(p_view)
    with pytest.raises(Forbidden):
        v.require_staff()
    with pytest.raises(Forbidden):
        v.require_admin()


def test_scope_assets_adds_tenant_and_client_filters():
    staff = _viewer(FirmRole.staff)
    sql = str(staff.scope_assets(select(Asset))).split("WHERE", 1)[1]
    assert "asset.firm_id" in sql and "asset.deleted_at IS NULL" in sql
    assert "internal_only" not in sql

    client = Viewer(
        user_id=uuid.uuid4(),
        firm_id=uuid.uuid4(),
        role=FirmRole.client,
        project_roles={uuid.uuid4(): ProjectRole.viewer},
    )
    sql = str(client.scope_assets(select(Asset))).split("WHERE", 1)[1]
    assert "asset.project_id IN" in sql and "asset.internal_only IS" in sql
