import os,sys,tempfile
sys.path.insert(0,os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"]=tempfile.mktemp(suffix=".db")
os.environ["DATA_DIR"]=tempfile.mkdtemp()
os.environ["JOB_SECRETS_KEY"]="runner-registry-test-key"
os.environ.setdefault("RUNNER_SERVICE_SECRET","embedded-test-secret")

import database
database.init_db()
from routes.deps import hash_password,now_utc_str
from fastapi.testclient import TestClient
from app import app
from services import runner_client

client=TestClient(app)
URL="https://runner-two.example"
SECRET="runner-secret-longer-than-twenty-four-characters"

class Resp:
    def __init__(self,status=200,data=None):self.status_code=status;self._data=data or {};self.headers={}
    def json(self):return self._data


def setup_module():
    c=database.get_db_connection();n=now_utc_str();c.execute("INSERT INTO users(username,email,password,is_verified,is_admin,created_at,updated_at) VALUES(?,?,?,1,1,?,?)",("runner-admin","runner@gmail.com",hash_password("Passw0rd!x"),n,n));c.commit();c.close()


def headers():
    r=client.post("/login",json={"username":"runner@gmail.com","email":"runner@gmail.com","password":"Passw0rd!x"})
    return {"Authorization":"Bearer "+r.json()["token"]}


def test_admin_can_verify_add_drain_and_keep_secret_private(monkeypatch):
    monkeypatch.setattr("routes.admin.socket.getaddrinfo",lambda *a,**k:[(2,1,6,"",("8.8.8.8",443))])
    def get(url,headers=None,timeout=None):
        if url==URL+"/health":return Resp(200,{"jobs":1,"capacity":5,"free":4,"load":.2,"mem_mb":80,"safe_mb":400})
        if url==URL+"/internal/jobs" and headers=={"Authorization":"Bearer "+SECRET}:return Resp(200,{"jobs":[]})
        return Resp(403,{})
    monkeypatch.setattr("routes.admin.requests.get",get)
    assert client.get("/admin/runners").status_code==404
    c=database.get_db_connection();uid=c.execute("SELECT id FROM users WHERE username='runner-admin'").fetchone()["id"];n=now_utc_str();c.execute("INSERT INTO jobs(user_id,name,language,code,runner_job_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",(uid,"embedded-old","python","print(1)","old-rid",n,n));c.commit();c.close()
    made=client.post("/admin/runners",headers=headers(),json={"label":"Runner Two","url":URL,"secret":SECRET})
    assert made.status_code==200,made.text
    data=client.get("/admin/runners",headers=headers()).json()
    assert data["runners"][0]["url"]==URL and SECRET not in repr(data) and "secret" not in data["runners"][0]
    c=database.get_db_connection();raw=c.execute("SELECT encrypted_secret FROM runner_nodes").fetchone()["encrypted_secret"];old_worker=c.execute("SELECT worker_url FROM jobs WHERE name='embedded-old'").fetchone()["worker_url"];c.close()
    assert raw.startswith("enc:v1:") and SECRET not in raw and old_worker=="embedded"
    runner_client.invalidate_runner_registry()
    assert URL in runner_client.runner_pool()

    sent={}
    def request(method,url,json=None,headers=None,timeout=None):
        sent.update(method=method,url=url,headers=headers);return Resp(200,{"jobs":[]})
    monkeypatch.setattr(runner_client.requests,"request",request)
    runner_client._runner_http("GET","/internal/jobs",worker=URL)
    assert sent["headers"]["Authorization"]=="Bearer "+SECRET

    node_id=data["runners"][0]["id"]
    off=client.post(f"/admin/runners/{node_id}/toggle",headers=headers(),json={"enabled":False})
    assert off.status_code==200
    assert URL not in runner_client.runner_pool()
    # Draining stops placement but preserves credentials for jobs already there.
    runner_client._runner_http("GET","/internal/jobs",worker=URL)
    assert sent["headers"]["Authorization"]=="Bearer "+SECRET
    deleted=client.delete(f"/admin/runners/{node_id}",headers=headers())
    assert deleted.status_code==200


def test_add_runner_retries_render_wakeup_and_reports_missing_secret(monkeypatch):
    url="https://runner-waking.example"
    monkeypatch.setattr("routes.admin.socket.getaddrinfo",lambda *a,**k:[(2,1,6,"",("8.8.4.4",443))])
    monkeypatch.setattr("routes.admin.time.sleep",lambda _seconds:None)
    calls={"health":0}
    def get(target,headers=None,timeout=None):
        if target==url+"/health":
            calls["health"]+=1
            return Resp(502,{}) if calls["health"]<3 else Resp(200,{"status":"ok"})
        if target==url+"/internal/jobs":
            return Resp(503,{"detail":"Runner secret not configured."})
        return Resp(404,{})
    monkeypatch.setattr("routes.admin.requests.get",get)
    response=client.post("/admin/runners",headers=headers(),json={"label":"Waking","url":url,"secret":SECRET})
    assert calls["health"]==3
    assert response.status_code==400
    assert "RUNNER_SERVICE_SECRET is missing" in response.json()["detail"]
