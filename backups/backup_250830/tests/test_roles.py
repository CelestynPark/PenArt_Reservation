from app.auth.service import ROLES

def test_roles_defined():
    assert "user" in ROLES and "admin" in ROLES