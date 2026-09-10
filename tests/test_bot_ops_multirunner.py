from services import bot_ops, runner_client, snapshots


class Resp:
    def __init__(self,status,data,worker=None):
        self.status_code=status;self._data=data;self.placed_on=worker;self.headers={}
    def json(self):return self._data


def row():
    return {"id":11,"user_id":3,"name":"my-bot","language":"python","code":"print('x')",
            "env":None,"runner_job_id":"dead-a","worker_url":"https://runner-a.example",
            "desired_state":"running","telegram_bot_detected":0}


def test_telegram_restart_reassigns_vanished_internal_job(monkeypatch):
    app=row();monkeypatch.setattr(bot_ops,"find_app",lambda uid,ref:dict(app))
    calls=[];monkeypatch.setattr(runner_client,"fleet_jobs",lambda refresh=True:{})
    def request(method,path,body=None,worker=None):
        calls.append((method,path,worker))
        if path.endswith("/restart"):return Resp(404,{})
        assert path=="/internal/jobs"
        return Resp(201,{"id":"fresh-b","logs":"started"},"https://runner-b.example")
    monkeypatch.setattr(runner_client,"_runner_http",request)
    saved={};monkeypatch.setattr(bot_ops,"_set_assignment",lambda r,rid,worker,desired="running":saved.update(rid=rid,worker=worker,desired=desired))
    monkeypatch.setattr(snapshots,"restore_snapshot",lambda *a,**k:{"restored":0})
    result=bot_ops.restart(3,"my-bot")
    assert result["ok"] is True
    assert calls[0]==("POST","/internal/jobs/dead-a/restart","https://runner-a.example")
    assert saved=={"rid":"fresh-b","worker":"https://runner-b.example","desired":"running"}


def test_status_recovers_missing_job_then_reads_new_assignment(monkeypatch):
    app=row();monkeypatch.setattr(bot_ops,"find_app",lambda uid,ref:app)
    calls=[];monkeypatch.setattr(runner_client,"fleet_jobs",lambda refresh=True:{})
    def request(method,path,body=None,worker=None):
        calls.append((method,path,worker))
        if path=="/internal/jobs/dead-a":return Resp(404,{})
        if path=="/internal/jobs":return Resp(201,{"id":"fresh-b","logs":"online"},"https://runner-b.example")
        raise AssertionError(path)
    monkeypatch.setattr(runner_client,"_runner_http",request)
    monkeypatch.setattr(bot_ops,"_set_assignment",lambda r,rid,worker,desired="running":r.update(runner_job_id=rid,worker_url=worker,desired_state=desired))
    monkeypatch.setattr(snapshots,"restore_snapshot",lambda *a,**k:{"restored":0})
    result=bot_ops.logs(3,"my-bot")
    assert result["ok"] is True and result["logs"]=="online"
    assert app["runner_job_id"]=="fresh-b" and app["worker_url"]=="https://runner-b.example"


def test_old_unassigned_row_adopts_existing_process_instead_of_duplicating(monkeypatch):
    app=row();app["worker_url"]=None
    monkeypatch.setattr(bot_ops,"find_app",lambda uid,ref:app)
    live={"real-b":{"id":"real-b","name":"u3-my-bot","status":"running","worker":"https://runner-b.example","logs":"still here"}}
    monkeypatch.setattr(runner_client,"fleet_jobs",lambda refresh=True:live)
    calls=[]
    def request(method,path,body=None,worker=None):
        calls.append((method,path,worker))
        if path=="/internal/jobs/dead-a/restart":return Resp(404,{})
        if path=="/internal/jobs/real-b/restart":return Resp(200,live["real-b"])
        if path=="/internal/jobs/dead-a":return Resp(404,{})
        raise AssertionError(path)
    monkeypatch.setattr(runner_client,"_runner_http",request)
    saved={};monkeypatch.setattr(bot_ops,"_set_assignment",lambda r,rid,worker,desired="running":saved.update(rid=rid,worker=worker))
    result=bot_ops.restart(3,"my-bot")
    assert result["ok"] is True
    assert saved=={"rid":"real-b","worker":"https://runner-b.example"}
    assert not any(path=="/internal/jobs" for _,path,_ in calls)
