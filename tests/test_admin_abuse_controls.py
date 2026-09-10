import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = tempfile.mktemp(suffix=".db")
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp())

import database
from routes.deps import hash_password, now_utc_str

database.init_db()
from app import app
from fastapi.testclient import TestClient
from services import abuse_control

client = TestClient(app)


def setup_module():
    c = database.get_db_connection(); now = now_utc_str()
    c.execute("INSERT INTO users (username,email,password,is_verified,is_admin,created_at,updated_at) VALUES (?,?,?,1,1,?,?)",
              ("security-admin", "security@gmail.com", hash_password("Passw0rd!x"), now, now))
    c.execute("INSERT INTO users (username,email,password,is_verified,created_at,updated_at) VALUES (?,?,?,1,?,?)",
              ("target-user", "target@gmail.com", hash_password("Passw0rd!x"), now, now))
    c.commit(); c.close()


def admin_headers():
    r = client.post("/login", json={"username":"security@gmail.com", "email":"security@gmail.com", "password":"Passw0rd!x"})
    return {"Authorization":"Bearer " + r.json()["token"]}


def test_block_needs_admin_but_not_2fa_and_is_reversible():
    h = admin_headers()
    made = client.post("/admin/blocks", headers=h, json={"scope":"ip","value":"203.0.113.8","duration_hours":24,"reason":"account farm"})
    assert made.status_code == 200, made.text
    block_id = made.json()["id"]
    try:
        abuse_control.enforce(ip="203.0.113.8", action="signup")
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 403
    else:
        raise AssertionError("active block was not enforced")
    listed = client.get("/admin/blocks", headers=h).json()
    assert listed["active"] == 1 and listed["blocks"][0]["reason"] == "account farm"
    removed = client.post(f"/admin/blocks/{block_id}/remove", headers=h, json={})
    assert removed.status_code == 200, removed.text
    assert abuse_control.active_block("ip", "203.0.113.8") is None


def test_suspend_needs_no_admin_2fa():
    c = database.get_db_connection(); uid=c.execute("SELECT id FROM users WHERE username='target-user'").fetchone()["id"]; c.close()
    r=client.post("/admin/users/set-suspended",headers=admin_headers(),json={"user_id":uid,"suspended":True})
    assert r.status_code==200,r.text
    root=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    assert 'id="adminTfaCode"' not in open(os.path.join(root,"index.html"),encoding="utf-8").read()


def test_block_routes_are_stealth_and_validate_device_hash():
    assert client.get("/admin/blocks").status_code == 404
    r = client.post("/admin/blocks", headers=admin_headers(), json={"scope":"fingerprint","value":"short","reason":"bad"})
    assert r.status_code == 400
