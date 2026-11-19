import csv,io,json
import pytest
from app import identity,store
from app.errors import DomainError
from app.pipeline import calculate,execute
from app.modules.m3_grants.rules import GRANTS
from app.modules.m7_seals.rules import evaluate as seal

DIRECTORY=[
    {"employee_no":"1001","name":"张三","cost_center":"CC-EAST","historical_nos":["E001"],"accounts":["zhangsan","zs@corp"]},
    {"employee_no":"1002","name":"张三","cost_center":"CC-WEST","historical_nos":["E002"],"accounts":["zhangsan.west"]},
    {"employee_no":"1003","name":"李四","cost_center":"CC-NORTH","historical_nos":["E003"],"accounts":["lisi"]},
    {"employee_no":"1004","name":"王五","cost_center":"","historical_nos":["E004"],"accounts":["wangwu"]},
    {"employee_no":"1005","name":"赵六","cost_center":"CC-SOUTH","historical_nos":[],"accounts":["shared"]},
    {"employee_no":"1006","name":"钱七","cost_center":"CC-SOUTH","historical_nos":[],"accounts":["shared"]},
]

def make(rows):
    header="event_id,principal,resource,partition,access_time,observed,reported,note\n"
    return (header+"\n".join(",".join(r) for r in rows)+"\n").encode()

def access(event_id,principal,partition="2026-10",observed="allowed",reported="1"):
    return [event_id,principal,"orders",partition,"2026-11-16T00:00:00Z",observed,reported,"演示"]

def run(rows,extra=None):
    params={"identities":DIRECTORY}
    if extra: params.update(extra)
    return calculate(make(rows),params)

def test_historical_no_account_and_email_share_one_principal():
    result=run([access("A1","E001"),access("A2","zs@corp"),access("A3","zhangsan"),access("A4","1001")])
    conclusion=result["identity"]["conclusions"][0]
    assert conclusion["principal"]=="1001"
    assert sorted(conclusion["referenced"])==["1001","E001","zhangsan","zs@corp"]
    assert {row["principal"] for row in result["stages"][1]["rows"]}=={"1001"}
    assert result["identity"]["metrics"]["complete"] is True

def test_same_name_different_cost_center_not_merged():
    result=run([access("A1","zhangsan"),access("A2","zhangsan.west")])
    principals={row["principal"] for row in result["stages"][1]["rows"]}
    assert principals=={"1001","1002"}
    assert not any(item["name"]=="张三" and item["status"]!="resolved" for item in result["identity"]["conclusions"])

def test_name_only_is_not_an_identity():
    result=run([access("A1","张三")])
    assert result["stages"][1]["rows"]==[]
    reasons=[row["reason"] for row in result["stages"][1]["quarantine"]]
    assert reasons==["IDENTITY_AMBIGUOUS"]
    assert result["identity"]["unresolved"][0]["candidates"]==["1001","1002"]

def test_single_name_still_not_accepted():
    result=run([access("A1","李四")])
    assert result["stages"][1]["rows"]==[]
    assert result["stages"][1]["quarantine"][0]["reason"]=="IDENTITY_NAME_ONLY"

def test_shared_account_pointing_to_two_people_conflicts():
    result=run([access("A1","shared")])
    assert result["stages"][1]["rows"]==[]
    assert result["stages"][1]["quarantine"][0]["reason"]=="IDENTITY_CONFLICT"
    assert result["identity"]["conflicts"][0]["candidates"]==["1005","1006"]

def test_incomplete_credentials_never_archive():
    result=run([access("A1","wangwu")])
    assert result["stages"][1]["quarantine"][0]["reason"]=="IDENTITY_INCOMPLETE"
    assert result["identity"]["metrics"]["complete"] is False
    assert result["stages"][6]["metrics"]["ready"] is False
    from app.archive import build_archive
    with pytest.raises(DomainError) as error:build_archive(result)
    assert error.value.code=="IDENTITY_INCOMPLETE"

def test_archive_export_refuses_incomplete_batch():
    from app.archive import build_archive
    result=run([access("A1","wangwu")])
    result["run_id"]="x"
    with pytest.raises(DomainError) as error:build_archive(result)
    assert error.value.code=="IDENTITY_INCOMPLETE"

def test_grant_on_historical_no_matches_employee():
    grants=[{"id":"G-1","principal":"E001","resource":"orders","start":"2026-11-01T00:00:00Z","end":"2026-12-01T00:00:00Z","from_partition":"2026-01","to_partition":"2026-12","effect":"allow"},
            {"id":"G-2","principal":"shared","resource":"orders","start":"2026-11-01T00:00:00Z","end":"2026-12-01T00:00:00Z","from_partition":"2026-01","to_partition":"2026-12","effect":"allow"}]
    result=run([access("A1","zhangsan")],{"grants":grants})
    assert result["stages"][2]["grant_identity_issues"][0]["grant_id"]=="G-2"
    stage4={row["event_id"]:row for row in result["stages"][3]["rows"]}
    assert stage4["A1"]["principal"]=="1001" and stage4["A1"]["rule_evidence"]=="G-1"

def test_reconciliation_follows_identity():
    result=run([access("A1","E001"),access("A2","zs@corp")])
    audit=result["stages"][5]
    assert [row["principal"] for row in audit["rows"]]==["1001","1001"]
    assert audit["metrics"]["balanced"] is True and audit["metrics"]["accepted_inputs"]==2

def test_rerun_adds_no_new_conclusion():
    first=execute(make([access("A1","E001"),access("A2","zhangsan.west")]),{"identities":DIRECTORY})
    second=execute(make([access("A1","E001"),access("A2","zhangsan.west")]),{"identities":DIRECTORY})
    assert first["run_id"]==second["run_id"]
    assert len(store.history())==1
    assert first["identity"]["conclusions"]==second["identity"]["conclusions"]

def test_export_contains_identity_conclusions():
    from app.archive import build_archive
    grants=[{"id":"G-1","principal":"E001","resource":"orders","start":"2026-11-01T00:00:00Z","end":"2026-12-01T00:00:00Z","from_partition":"2026-01","to_partition":"2026-12","effect":"allow"}]
    result=execute(make([access("A1","E001")]),{"identities":DIRECTORY,"grants":grants})
    rows=list(csv.reader(io.StringIO(build_archive(result).lstrip("﻿"))))
    kinds={row[3] for row in rows[1:]}
    assert "accepted" in kinds and "identity" in kinds
    identity_row=next(row for row in rows[1:] if row[3]=="identity")
    assert json.loads(identity_row[4])==["E001"] and identity_row[5]=="resolved"
    manifest_row=next(row for row in rows[1:] if row[3]=="identity_manifest")
    manifest=json.loads(manifest_row[6])
    assert manifest["policy"]==identity.STRICT and manifest["complete"] is True
    assert result["manifest"]["identity"]["fingerprint"]

def test_unattributable_grant_blocks_archive():
    from app.archive import build_archive
    grants=[{"id":"G-1","principal":"shared","resource":"orders","start":"2026-11-01T00:00:00Z","end":"2026-12-01T00:00:00Z","from_partition":"2026-01","to_partition":"2026-12","effect":"allow"}]
    result=execute(make([access("A1","zhangsan")]),{"identities":DIRECTORY,"grants":grants})
    assert result["identity"]["metrics"]["complete"] is True
    assert result["stages"][6]["metrics"]["ready"] is False
    assert result["stages"][6]["blockers"][0]["code"]=="IDENTITY_GRANT_INCOMPLETE"
    with pytest.raises(DomainError) as error:build_archive(result)
    assert error.value.code=="IDENTITY_GRANT_INCOMPLETE"

def test_policy_conflict_resolution_differs():
    directory=[
        {"employee_no":"2001","name":"甲","cost_center":"X","accounts":["acct"]},
        {"employee_no":"2002","name":"乙","cost_center":"Y","historical_nos":["acct"]},
    ]
    strict=identity.build(directory)
    assert strict["identifiers"]["acct"]=={"2001","2002"}
    assert strict["conflicts"]
    historical=identity.build(directory,policy=identity.HISTORICAL_FIRST)
    assert historical["identifiers"]["acct"]=={"2002"}

def test_strict_merges_only_when_shared_credentials_match():
    directory=[
        {"employee_no":"3001","name":"丙","cost_center":"Z","accounts":["legacy"]},
        {"employee_no":"3002","name":"丙","cost_center":"Z","accounts":["legacy"]},
    ]
    built=identity.build(directory)
    assert built["merges"][0]["basis"]=="共同凭据完全一致"
    assert built["identifiers"]["legacy"]=={"3001"}

def test_switch_to_historical_policy_keeps_old_version(client):
    directory=[
        {"employee_no":"4001","name":"周九","cost_center":"CC-A","accounts":["acct"]},
        {"employee_no":"4002","name":"吴十","cost_center":"CC-B","historical_nos":["acct"]},
    ]
    payload=client.post("/api/runs",json={"csv":make([access("A1","acct")]).decode(),"parameters":{"identities":directory}}).get_json()
    run_id=payload["run_id"]
    before=client.get("/api/runs/"+run_id).get_json()
    assert before["identity"]["policy"]==identity.STRICT
    assert before["identity"]["unresolved"][0]["status"]=="conflict"
    assert before["identity"]["metrics"]["complete"] is False
    switched=client.post("/api/runs/"+run_id+"/identity",json={"version":1,"policy":identity.HISTORICAL_FIRST})
    assert switched.status_code==200
    body=switched.get_json()
    new_run=body["run"]
    assert body["changed"] is True and body["previous_version"]==1
    assert new_run["run_id"]==run_id and new_run["version"]==2
    assert new_run["identity"]["policy"]==identity.HISTORICAL_FIRST
    assert new_run["identity"]["conclusions"][0]["principal"]=="4002"
    assert new_run["identity"]["metrics"]["complete"] is True
    assert new_run["identity"]["original_identifiers"]==["acct"]
    old=client.get("/api/runs/"+run_id+"/identities").get_json()["versions"]
    assert len(old)==1 and old[0]["version"]==1
    assert old[0]["identity"]==before["identity"]
    assert old[0]["identity"]["unresolved"][0]["status"]=="conflict"

def test_switch_failure_keeps_old_version_and_identifiers(client):
    payload=client.post("/api/runs",json={"csv":make([access("A1","E001")]).decode(),"parameters":{"identities":DIRECTORY}}).get_json()
    run_id=payload["run_id"]
    before=client.get("/api/runs/"+run_id).get_json()
    bad=client.post("/api/runs/"+run_id+"/identity",json={"version":1,"policy":"nope"})
    assert bad.status_code==422
    stale=client.post("/api/runs/"+run_id+"/identity",json={"version":99,"policy":identity.HISTORICAL_FIRST})
    assert stale.status_code==409
    after=client.get("/api/runs/"+run_id).get_json()
    assert after["identity"]==before["identity"] and after["version"]==before["version"]
    assert after["identity"]["original_identifiers"]==["E001"]
    assert client.get("/api/runs/"+run_id+"/identities").get_json()["versions"]==[]

def test_switch_is_idempotent_for_same_policy(client):
    payload=client.post("/api/runs",json={"csv":make([access("A1","E001")]).decode(),"parameters":{"identities":DIRECTORY}}).get_json()
    run_id=payload["run_id"]
    first=client.post("/api/runs/"+run_id+"/identity",json={"version":1,"policy":identity.HISTORICAL_FIRST})
    assert first.status_code==200
    second=client.post("/api/runs/"+run_id+"/identity",json={"version":2,"policy":identity.HISTORICAL_FIRST})
    assert second.status_code==200 and second.get_json()["changed"] is False
    assert client.get("/api/runs/"+run_id).get_json()["version"]==2

def test_switch_rejects_identifier_change(client):
    directory=[{"employee_no":"5001","name":"郑一","cost_center":"CC-A","accounts":["acct"]}]
    payload=client.post("/api/runs",json={"csv":make([access("A1","acct")]).decode(),"parameters":{"identities":directory}}).get_json()
    run_id=payload["run_id"]
    before=client.get("/api/runs/"+run_id).get_json()
    # 用未登记标识的批次无法切换出任何新结论；原始标识集合必须保持一致。
    response=client.post("/api/runs/"+run_id+"/identity",json={"version":1,"policy":identity.HISTORICAL_FIRST})
    assert response.status_code==200
    after=client.get("/api/runs/"+run_id).get_json()
    assert after["identity"]["original_identifiers"]==before["identity"]["original_identifiers"]==["acct"]
