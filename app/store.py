import sqlite3,json,base64
from datetime import datetime,timezone
from app.config import DATA_DIR
from app.errors import DomainError
def connect():
    DATA_DIR.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(DATA_DIR/"records.db",timeout=20)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY,payload TEXT NOT NULL,version INTEGER NOT NULL DEFAULT 1,decision TEXT NOT NULL DEFAULT '待复核')")
    db.execute("CREATE TABLE IF NOT EXISTS run_versions (id TEXT NOT NULL,version INTEGER NOT NULL,payload TEXT NOT NULL,decision TEXT NOT NULL,superseded_at TEXT NOT NULL,PRIMARY KEY(id,version))")
    columns={row[1] for row in db.execute("PRAGMA table_info(runs)")}
    if "raw_input" not in columns:
        db.execute("ALTER TABLE runs ADD COLUMN raw_input BLOB")
    return db
def save(run_id,payload,raw=None):
    """同一输入、规则版本、参数与主体目录只产生一个批次，重跑不新增结论。"""
    stored=base64.b64encode(raw).decode() if raw is not None else None
    with connect() as db:
        db.execute("INSERT OR IGNORE INTO runs(id,payload,raw_input) VALUES (?,?,?)",(run_id,json.dumps(payload,ensure_ascii=False),stored))
        if stored is not None:
            db.execute("UPDATE runs SET raw_input=? WHERE id=? AND raw_input IS NULL",(stored,run_id))
    return get(run_id)
def get(run_id):
    with connect() as db: row=db.execute("SELECT payload,version,decision FROM runs WHERE id=?",(run_id,)).fetchone()
    if not row: raise DomainError("NOT_FOUND","批次不存在",404)
    return {**json.loads(row[0]),"version":row[1],"decision":row[2]}
def versions(run_id):
    with connect() as db:
        exists=db.execute("SELECT 1 FROM runs WHERE id=?",(run_id,)).fetchone()
        if not exists: raise DomainError("NOT_FOUND","批次不存在",404)
        rows=list(db.execute("SELECT version,payload,decision,superseded_at FROM run_versions WHERE id=? ORDER BY version",(run_id,)))
    return [{"version":v,"decision":d,"superseded_at":t,"identity":json.loads(p).get("identity",{})} for v,p,d,t in rows]
def latest():
    with connect() as db: row=db.execute("SELECT id FROM runs ORDER BY rowid DESC LIMIT 1").fetchone()
    return get(row[0]) if row else None
def history():
    with connect() as db: rows=list(db.execute("SELECT id,version,decision,payload FROM runs ORDER BY rowid DESC"))
    result=[]
    for run_id,version,decision,payload in rows:
        identity=json.loads(payload).get("identity",{})
        result.append({"run_id":run_id,"version":version,"decision":decision,"identity_policy":identity.get("policy",""),"identity_complete":identity.get("metrics",{}).get("complete")})
    return result
def review(run_id,version,decision):
    if decision not in {"已复核","退回复核"}: raise DomainError("BAD_DECISION","复核状态无效")
    with connect() as db:
        cursor=db.execute("UPDATE runs SET version=version+1,decision=? WHERE id=? AND version=?",(decision,run_id,version))
        if cursor.rowcount!=1:
            if not db.execute("SELECT 1 FROM runs WHERE id=?",(run_id,)).fetchone(): raise DomainError("NOT_FOUND","批次不存在",404)
            raise DomainError("STALE_VERSION","版本已更新，请刷新",409)
    return get(run_id)
def switch_identity(run_id,version,policy):
    """在同一批次内切换主体归属策略：旧版归档后版本+1，失败则整体回滚。

    失败时批次版本、旧结论与全部原始标识原样保留；重复切换同一策略不改动批次。
    """
    from app import identity
    from app.pipeline import calculate
    if policy not in identity.POLICIES: raise DomainError("BAD_IDENTITY_POLICY","未知的主体归属策略")
    db=connect()
    try:
        row=db.execute("SELECT payload,version,decision,raw_input FROM runs WHERE id=?",(run_id,)).fetchone()
        if not row: raise DomainError("NOT_FOUND","批次不存在",404)
        current_payload,current_version,current_decision,stored_raw=row
        if current_version!=version: raise DomainError("STALE_VERSION","版本已更新，请刷新",409)
        payload=json.loads(current_payload)
        if payload.get("identity",{}).get("policy")==policy:
            return {"run":get(run_id),"policy":policy,"previous_version":current_version,"changed":False}
        if not stored_raw: raise DomainError("MISSING_RAW","旧批次没有原始输入，无法切换策略",409)
        raw=base64.b64decode(stored_raw)
        params={**payload.get("parameters",{}),"identity_policy":policy}
        calculated=calculate(raw,params)
        new_identity=calculated.get("identity",{})
        if not new_identity.get("active"):
            raise DomainError("IDENTITY_SWITCH_REJECTED","切换后主体归属未生效，已保留旧版与原始标识",409)
        covered={identifier for item in new_identity.get("conclusions",[]) for identifier in item.get("referenced",[])}
        covered.update(item.get("identifier") for item in new_identity.get("unresolved",[]))
        if covered!=set(new_identity.get("original_identifiers",[])):
            # 归属结论必须覆盖全部原始标识，否则新策略有漏项，拒绝切换。
            raise DomainError("IDENTITY_SWITCH_REJECTED","切换会遗漏原始标识，已保留旧版与原始标识",409)
        calculated["run_id"]=run_id
        calculated["identity_switched_from"]=current_version
        now=datetime.now(timezone.utc).isoformat()
        db.execute("INSERT OR REPLACE INTO run_versions(id,version,payload,decision,superseded_at) VALUES (?,?,?,?,?)",(run_id,current_version,current_payload,current_decision,now))
        cursor=db.execute("UPDATE runs SET payload=?,version=version+1,decision=? WHERE id=? AND version=?",(json.dumps(calculated,ensure_ascii=False),"待复核",run_id,current_version))
        if cursor.rowcount!=1: raise DomainError("STALE_VERSION","版本已更新，请刷新",409)
        db.commit()
    except Exception:
        db.rollback();raise
    finally:
        db.close()
    return {"run":get(run_id),"policy":policy,"previous_version":current_version,"changed":True}
