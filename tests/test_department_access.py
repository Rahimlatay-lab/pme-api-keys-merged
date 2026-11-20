from sqlalchemy import text

from db import SessionLocal


async def _has_permission(employee_code, department, permission):
    async with SessionLocal() as session:
        result = await session.execute(
            text(
                "SELECT employee_has_department_permission("
                "(SELECT id FROM employees WHERE employee_code = :employee_code), "
                ":department, :permission)"
            ),
            {
                "employee_code": employee_code,
                "department": department,
                "permission": permission,
            },
        )
        return result.scalar_one()


async def test_employee_permissions_are_limited_to_assigned_department():
    assert await _has_permission("sales_employee", "sales", "deploy_files")
    assert await _has_permission("sales_employee", "sales", "view_dashboard")
    assert await _has_permission("sales_employee", "sales", "view_resume")
    assert not await _has_permission("sales_employee", "finance", "deploy_files")
    assert not await _has_permission("sales_employee", "finance", "view_dashboard")
    assert not await _has_permission("sales_employee", "finance", "view_resume")


async def test_manager_can_view_all_departments_but_cannot_deploy_files():
    for department in ("sales", "production", "stocks", "supply", "finance"):
        assert await _has_permission("manager", department, "view_dashboard")
        assert await _has_permission("manager", department, "view_resume")
        assert not await _has_permission("manager", department, "deploy_files")
