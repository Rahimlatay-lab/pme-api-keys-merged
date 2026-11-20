-- Department-level permissions for the five employees and manager.
-- Idempotent: safe to run on every deploy (python migrate.py).

CREATE TABLE IF NOT EXISTS departments (
    id   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    code text NOT NULL UNIQUE,
    name text NOT NULL
);

CREATE TABLE IF NOT EXISTS employees (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    employee_code text NOT NULL UNIQUE,
    display_name  text NOT NULL,
    access_role   text NOT NULL CHECK (access_role IN ('employee', 'manager')),
    department_id uuid REFERENCES departments(id),
    CHECK (
        (access_role = 'employee' AND department_id IS NOT NULL)
        OR (access_role = 'manager' AND department_id IS NULL)
    )
);

CREATE TABLE IF NOT EXISTS employee_department_permissions (
    employee_id  uuid NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    department_id uuid NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
    permission   text NOT NULL CHECK (
        permission IN ('deploy_files', 'view_dashboard', 'view_resume')
    ),
    allowed      boolean NOT NULL,
    PRIMARY KEY (employee_id, department_id, permission)
);

INSERT INTO departments (code, name)
VALUES
    ('sales', 'Sales'),
    ('production', 'Production'),
    ('stocks', 'Stocks'),
    ('supply', 'Supply'),
    ('finance', 'Finance')
ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name;

INSERT INTO employees (employee_code, display_name, access_role, department_id)
SELECT seed.employee_code, seed.display_name, seed.access_role, d.id
FROM (VALUES
    ('sales_employee', 'Sales Employee', 'employee', 'sales'),
    ('production_employee', 'Production Employee', 'employee', 'production'),
    ('stocks_employee', 'Stocks Employee', 'employee', 'stocks'),
    ('supply_employee', 'Supply Employee', 'employee', 'supply'),
    ('finance_employee', 'Finance Employee', 'employee', 'finance'),
    ('manager', 'Manager', 'manager', NULL)
) AS seed(employee_code, display_name, access_role, department_code)
LEFT JOIN departments d ON d.code = seed.department_code
ON CONFLICT (employee_code) DO UPDATE SET
    display_name = EXCLUDED.display_name,
    access_role = EXCLUDED.access_role,
    department_id = EXCLUDED.department_id;

-- Each employee gets explicit allow/deny rows for all departments and actions.
-- Employees are allowed all three actions only in their assigned department.
-- The manager may view all dashboards and resumes, but cannot deploy files.
INSERT INTO employee_department_permissions
    (employee_id, department_id, permission, allowed)
SELECT
    e.id,
    d.id,
    p.permission,
    CASE
        WHEN e.access_role = 'manager'
            THEN p.permission IN ('view_dashboard', 'view_resume')
        ELSE e.department_id = d.id
    END
FROM employees e
CROSS JOIN departments d
CROSS JOIN (VALUES
    ('deploy_files'),
    ('view_dashboard'),
    ('view_resume')
) AS p(permission)
ON CONFLICT (employee_id, department_id, permission) DO UPDATE
SET allowed = EXCLUDED.allowed;

CREATE OR REPLACE FUNCTION employee_has_department_permission(
    p_employee_id uuid,
    p_department_code text,
    p_permission text
) RETURNS boolean
LANGUAGE sql
STABLE
AS $$
    SELECT COALESCE((
        SELECT permission.allowed
        FROM employee_department_permissions AS permission
        JOIN departments AS department
            ON department.id = permission.department_id
        WHERE permission.employee_id = p_employee_id
          AND department.code = p_department_code
          AND permission.permission = p_permission
    ), false);
$$;
