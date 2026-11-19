import hashlib,json
from app.errors import DomainError
from app.reasons import sources
def blockers(context,rows):
    """归档门禁：结构不平衡直接失败；主体或授权凭据问题记录为阻塞项，保留批次供复核。"""
    reasons=[]
    identity=context.get("identity_document") or {}
    metrics=identity.get("metrics",{})
    if metrics and metrics.get("complete") is False:
        reasons.append({"code":"IDENTITY_INCOMPLETE","detail":"存在未归属、同名待裁或凭据不完整的主体，不能归档"})
    if any(row.get("identity_status")=="incomplete" for row in rows):
        reasons.append({"code":"IDENTITY_INCOMPLETE","detail":"存在凭据不完整的主体行，不能归档"})
    if identity.get("active") is False:
        reasons.append({"code":"IDENTITY_DISABLED","detail":"未启用主体归属，批次不能归档"})
    grant_issues=(context.get("grants") or {}).get("grant_identity_issues") or []
    if grant_issues:
        reasons.append({"code":"IDENTITY_GRANT_INCOMPLETE","detail":f"{len(grant_issues)} 条授权的主体无法唯一归属，不能归档"})
    return reasons
def evaluate(rows,context):
    stages=[v for v in context.values() if isinstance(v,dict) and "metrics" in v]
    balances=[s["metrics"]["balanced"] for s in stages if "balanced" in s["metrics"]]
    if balances and not all(balances): raise DomainError("UNBALANCED","来源行未对平，不能归档")
    gate=blockers(context,rows)
    ids=[str(r.get("event_id",r.get("_line",""))) for r in rows]
    if len(ids)!=len(set(ids)): raise DomainError("ARCHIVE_DUPLICATE","归档业务键重复")
    encoded=json.dumps(rows,ensure_ascii=False,sort_keys=True,default=str).encode()
    return {"rows":rows,"quarantine":[],"metrics":{"records":len(rows),"source_lines":len(set(x for row in rows for x in sources(row))),"sha256":hashlib.sha256(encoded).hexdigest(),"ready":not gate,"differences":sum(r.get("status")=="差异" for r in rows),"principals":len({r.get("principal") for r in rows})},"blockers":gate}
