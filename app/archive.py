import csv,io,json
from app.errors import DomainError
def build_archive(run):
    seal=(run.get("stages") or [{}])[-1]
    blockers=seal.get("blockers") or []
    if blockers:
        raise DomainError(blockers[0]["code"],blockers[0]["detail"],409)
    identity=run.get("identity") or {}
    if identity.get("metrics",{}).get("complete") is False:
        raise DomainError("IDENTITY_INCOMPLETE","主体凭据不完整或存在冲突，不能归档",409)
    stream=io.StringIO(newline="");writer=csv.writer(stream)
    writer.writerow(["run_id","input_sha256","rule_version","kind","source_lines","reason","evidence"])
    meta=run["manifest"]
    for row in run["stages"][-1]["rows"]:
        writer.writerow([run["run_id"],meta["input_sha256"],meta["rule_version"],"accepted",json.dumps(row.get("_sources",[])),row.get("status",""),json.dumps(row,ensure_ascii=False)])
    for row in run["stages"][-1].get("cumulative_quarantine",[]):
        writer.writerow([run["run_id"],meta["input_sha256"],meta["rule_version"],"quarantine",json.dumps(row.get("_sources",[])),row.get("reason",""),json.dumps(row,ensure_ascii=False)])
    for item in identity.get("conclusions",[]):
        writer.writerow([run["run_id"],meta["input_sha256"],meta["rule_version"],"identity",json.dumps(item.get("referenced",[])),item.get("status",""),json.dumps(item,ensure_ascii=False)])
    for item in identity.get("unresolved",[]):
        writer.writerow([run["run_id"],meta["input_sha256"],meta["rule_version"],"identity_unresolved",json.dumps([item.get("identifier")]),item.get("status",""),json.dumps(item,ensure_ascii=False)])
    meta_identity=meta.get("identity") or {}
    writer.writerow([run["run_id"],meta["input_sha256"],meta["rule_version"],"identity_manifest",json.dumps(identity.get("original_identifiers",[])),meta_identity.get("policy",""),json.dumps(meta_identity,ensure_ascii=False,sort_keys=True)])
    return "﻿"+stream.getvalue()
