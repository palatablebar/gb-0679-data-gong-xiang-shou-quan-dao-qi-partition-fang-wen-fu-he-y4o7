import time
from app.config import ROOT,MODULES
from app.errors import DomainError
from app.values import scalar
from app.manifest import digest,manifest
from app import identity,store
from app.modules.m1_accesses.rules import evaluate as stage1
from app.modules.m2_resources.rules import evaluate as stage2
from app.modules.m3_grants.rules import evaluate as stage3
from app.modules.m4_conflicts.rules import evaluate as stage4
from app.modules.m5_partitions.rules import evaluate as stage5
from app.modules.m6_audit.rules import evaluate as stage6
from app.modules.m7_seals.rules import evaluate as stage7
STAGES=[stage1,stage2,stage3,stage4,stage5,stage6,stage7]
SAMPLES={"dirty.csv","clean.csv","legacy.csv","identity.csv"}
def load_sample(name):
    if name not in SAMPLES: raise DomainError("BAD_SAMPLE","样例不存在",404)
    return (ROOT/"sample_data"/name).read_bytes()
def calculate(raw,params=None,stop=6):
    params=params or {};started=time.monotonic()
    index=identity.from_params(params)
    context={"parameters":params,"raw":raw,"quarantine":[],"identity":index}
    stages=[];rows=[];document=identity.document(index,[])
    for stage_number,stage in enumerate(STAGES[:stop+1]):
        if stage_number==0:
            result=stage(raw,context)
            result=scalar(result);rows=result["rows"]
            # 每批唯一的主体归属结论只覆盖本批访问数据里的原始标识。
            document=identity.document(index,[r.get("principal") for r in rows])
            context["identity_document"]=document
        elif stage_number==1:
            # 访问采信通过后立即定主体归属；此后资源、授权、对账、归档全部以主键为准。
            attributed=identity.attribute(rows,index)
            result=stage(attributed["rows"],context)
            result["quarantine"]=attributed["quarantine"]+result["quarantine"]
        else:
            result=stage(rows,context)
        result=scalar(result);rows=result["rows"]
        result["identity"]=document
        context["quarantine"].extend(result.get("quarantine",[]))
        if stage_number==0: context["intake"]=result["metrics"]
        result["cumulative_quarantine"]=list(context["quarantine"])
        context[MODULES[stage_number][0]]=result
        stages.append(result)
    result={"run_id":digest(raw,{**params,"__identity__":identity.fingerprint(index)})[:20],"stages":stages,"manifest":manifest(raw,params,started),"parameters":params,"identity":document}
    result["manifest"]["identity"]={"policy":document.get("policy",identity.STRICT),"version":document.get("version",identity.IDENTITY_VERSION),"fingerprint":identity.fingerprint(index),"complete":document.get("metrics",{}).get("complete")}
    return result
def execute(raw,params=None):
    result=calculate(raw,params);return store.save(result["run_id"],result,raw)
def stage_preview(index,payload):
    if "rows" in payload and index>0:
        if not isinstance(payload["rows"],list) or any(not isinstance(row,dict) for row in payload["rows"]): raise DomainError("BAD_ROWS","记录需要对象列表")
        if not isinstance(payload.get("context",{}),dict): raise DomainError("BAD_CONTEXT","上下文需要对象")
        return scalar(STAGES[index](payload["rows"],payload.get("context",{"parameters":{},"quarantine":[]})))
    raw=payload.get("csv")
    raw=raw.encode() if isinstance(raw,str) else load_sample(payload.get("sample","dirty.csv"))
    return calculate(raw,payload.get("parameters",{}),index)["stages"][-1]
