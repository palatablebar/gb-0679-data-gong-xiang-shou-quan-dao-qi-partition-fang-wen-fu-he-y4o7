"""主体归属（identity attribution）。

裁决结论：采用 ``strict_shared_credentials``——只有在共同凭据（姓名、成本中心）
完全一致时才合并同一工号的多条标识记录；历史工号只是众多标识之一，不能覆盖
姓名/成本中心冲突。理由：审计场景里错误合并（同名不同成本中心）比未合并更难
发现和纠正。

同时保留 ``historical_no_first`` 作为可切换的对照策略，供复核人员比较，但默认
不启用。切换失败时旧批次、旧结论和原始标识保持不变（见 app.main 的 switch 接口）。
"""
import hashlib,json
from app.errors import DomainError

STRICT = "strict_shared_credentials"
HISTORICAL_FIRST = "historical_no_first"
POLICIES = (STRICT, HISTORICAL_FIRST)
DECISION = {
    "chosen": STRICT,
    "chosen_label": "严格共同凭据合并",
    "reason": "同名不同成本中心的错误合并不可逆，严格合并可把不确定项留在隔离区人工复核",
    "historical_no_role": "历史工号与当前工号、账号同为标识；命中历史工号可唯一归属，但不得覆盖共同凭据冲突",
    "rejected": HISTORICAL_FIRST,
    "rejected_label": "历史工号优先",
    "rejected_reason": "历史工号优先会在凭据冲突时静默选边，审计上无法证明选边依据",
}
IDENTITY_VERSION = "2026.11.19-i1"

# 仓内演示目录。employee_no 是每批结论的主键；historical_nos/accounts 是该员工
# 在共享访问数据和授权规则里的其它标识。
DEFAULT_DIRECTORY = [
    {
        "employee_no": "analyst",
        "name": "分析员",
        "cost_center": "CC-DATA",
        "historical_nos": [],
        "accounts": ["analyst", "analyst.legacy"],
    },
    {
        "employee_no": "auditor",
        "name": "审计员",
        "cost_center": "CC-RISK",
        "historical_nos": [],
        "accounts": ["auditor"],
    },
    {
        "employee_no": "guest",
        "name": "访客",
        "cost_center": "CC-GUEST",
        "historical_nos": [],
        "accounts": ["guest"],
    },
    {
        "employee_no": "000100",
        "name": "张三",
        "cost_center": "CC-EAST",
        "historical_nos": ["E00123"],
        "accounts": ["zhangsan", "zhang.san@corp"],
    },
    {
        "employee_no": "000101",
        "name": "张三",
        "cost_center": "CC-WEST",
        "historical_nos": ["E00124"],
        "accounts": ["zhangsan.west"],
    },
    {
        "employee_no": "000102",
        "name": "李四",
        "cost_center": "CC-EAST",
        "historical_nos": ["E00125"],
        "accounts": ["lisi"],
    },
    {
        "employee_no": "000103",
        "name": "王五",
        "cost_center": "",
        "historical_nos": ["E00126"],
        "accounts": ["wangwu"],
    },
    {
        "employee_no": "000104",
        "name": "赵六",
        "cost_center": "CC-NORTH",
        "historical_nos": ["E00127"],
        "accounts": ["contractor"],
    },
    {
        "employee_no": "000105",
        "name": "钱七",
        "cost_center": "CC-SOUTH",
        "historical_nos": ["E00128"],
        "accounts": ["contractor"],
    },
]

_EMPLOYEE_KEYS = ("employee_no", "current_employee_no", "emp_no", "工号")
_HISTORY_KEYS = ("historical_nos", "historical_employee_nos", "history_nos", "历史工号")
_ACCOUNT_KEYS = ("accounts", "identifiers", "aliases", "account", "账号")
_NAME_KEYS = ("name", "姓名")
_CC_KEYS = ("cost_center", "cost_centre", "成本中心", "cc")


def _text(raw, keys):
    for key in keys:
        if key in raw and raw[key] is not None:
            value = raw[key]
            if not isinstance(value, str):
                value = str(value)
            return value.strip()
    return ""


def _list(value, field):
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        items = list(value)
    elif isinstance(value, str):
        normalized = value.replace("；", ";").replace("，", ",")
        items = normalized.replace(";", ",").split(",")
    else:
        raise DomainError("BAD_IDENTITY", f"{field}需要文本或列表")
    result = []
    for item in items:
        if not isinstance(item, str):
            raise DomainError("BAD_IDENTITY", f"{field}的标识必须是文本")
        text = item.strip()
        if text and text not in result:
            result.append(text)
    return result


def _entry(raw, position):
    if not isinstance(raw, dict):
        raise DomainError("BAD_IDENTITY", f"第{position + 1}条主体需要对象")
    employee_no = _text(raw, _EMPLOYEE_KEYS)
    if not employee_no:
        raise DomainError("BAD_IDENTITY", f"第{position + 1}条主体缺少工号")
    historical = _list(raw.get(_HISTORY_KEYS[0], raw.get(_HISTORY_KEYS[1], raw.get(_HISTORY_KEYS[2], raw.get(_HISTORY_KEYS[3])))), "历史工号")
    accounts = _list(raw.get(_ACCOUNT_KEYS[0], raw.get(_ACCOUNT_KEYS[1], raw.get(_ACCOUNT_KEYS[2], raw.get(_ACCOUNT_KEYS[3], raw.get(_ACCOUNT_KEYS[4]))))), "账号")
    explicit = _list(raw.get("identifiers"), "标识")
    accounts = list(dict.fromkeys(accounts + explicit))
    name = _text(raw, _NAME_KEYS)
    cost_center = _text(raw, _CC_KEYS)
    identifiers = list(dict.fromkeys([employee_no] + historical + accounts))
    return {
        "employee_no": employee_no,
        "name": name,
        "cost_center": cost_center,
        "historical_nos": historical,
        "accounts": accounts,
        "identifiers": identifiers,
        "complete": bool(employee_no and name and cost_center),
        "source": f"directory[{position}]",
        "conflicted": False,
    }


def _missing(entry):
    return [label for label, value in (("name", entry["name"]), ("cost_center", entry["cost_center"])) if not value]


def _shared(entry):
    """共同凭据：姓名 + 成本中心。任一缺失即不完整，不能用于合并。"""
    return (entry["name"], entry["cost_center"])


def _merge(previous, entry):
    for key in ("historical_nos", "accounts", "identifiers"):
        previous[key] = list(dict.fromkeys(previous[key] + entry[key]))
    for field in ("name", "cost_center"):
        if not previous[field] and entry[field]:
            previous[field] = entry[field]
    previous["complete"] = previous["complete"] or entry["complete"]


def build(directory, policy=STRICT):
    """把目录编译成唯一主体表；结构非法直接拒绝，凭据冲突留给结论。"""
    if policy not in POLICIES:
        raise DomainError("BAD_IDENTITY_POLICY", "未知的主体归属策略")
    if not isinstance(directory, list):
        raise DomainError("BAD_IDENTITY", "主体目录需要列表")
    entries = []
    by_no = {}
    conflicts = []
    for position, raw in enumerate(directory):
        entry = _entry(raw, position)
        previous = by_no.get(entry["employee_no"])
        if previous is None:
            by_no[entry["employee_no"]] = entry
            entries.append(entry)
            continue
        # 同一工号重复出现：共同凭据完全一致才合并；不一致时保留全部标识并标记冲突。
        shared = [field for field in ("name", "cost_center") if previous[field] and entry[field]]
        differing = [field for field in shared if previous[field] != entry[field]]
        if differing and policy == STRICT:
            previous["conflicted"] = True
            conflicts.append({
                "identifier": entry["employee_no"],
                "status": "conflict",
                "reason": "同一工号的共同凭据不一致",
                "fields": differing,
                "candidates": [entry["employee_no"]],
                "sources": [previous["source"], entry["source"]],
            })
            _merge(previous, entry)
            continue
        if differing:
            # 对照策略：历史工号优先，选有历史工号的一条作为主记录。
            primary, secondary = (previous, entry)
            if entry["historical_nos"] and not previous["historical_nos"]:
                primary, secondary = entry, previous
            _merge(primary, secondary)
            if primary is not previous:
                by_no[entry["employee_no"]] = primary
                entries[entries.index(previous)] = primary
            continue
        _merge(previous, entry)
    identifier_map = {}
    merges = []
    for entry in entries:
        for identifier in entry["identifiers"]:
            identifier_map.setdefault(identifier, set()).add(entry["employee_no"])
    for identifier in sorted(identifier_map):
        owners = sorted(identifier_map[identifier])
        if len(owners) < 2:
            continue
        owner_entries = [by_no[owner] for owner in owners]
        if policy == HISTORICAL_FIRST:
            historical = [entry for entry in owner_entries if identifier in entry["historical_nos"]]
            if len(historical) == 1:
                identifier_map[identifier] = {historical[0]["employee_no"]}
                continue
        if policy == STRICT and all(entry["complete"] for entry in owner_entries) and len({_shared(entry) for entry in owner_entries}) == 1:
            # 共同凭据（姓名 + 成本中心）完全一致：合并到确定性的主键。
            canonical = owners[0]
            identifier_map[identifier] = {canonical}
            for owner in owners[1:]:
                _merge(by_no[canonical], by_no[owner])
                by_no[canonical]["conflicted"] = by_no[canonical]["conflicted"] or by_no[owner]["conflicted"]
                for other in by_no[owner]["identifiers"]:
                    identifier_map[other] = {canonical}
                merges.append({
                    "identifier": identifier,
                    "merged": owners,
                    "into": canonical,
                    "basis": "共同凭据完全一致",
                })
                del by_no[owner]
            continue
        conflicts.append({
            "identifier": identifier,
            "status": "conflict",
            "reason": "同一标识指向多个主体",
            "fields": ["identifiers"],
            "candidates": owners,
            "sources": [by_no[owner]["source"] for owner in owners],
        })
    entries = [entry for entry in entries if by_no.get(entry["employee_no"]) is entry]
    name_map = {}
    for entry in entries:
        if entry["name"]:
            name_map.setdefault(entry["name"], set()).add(entry["employee_no"])
    return {
        "active": True,
        "policy": policy,
        "version": IDENTITY_VERSION,
        "decision": DECISION,
        "entries": {entry["employee_no"]: entry for entry in entries},
        "identifiers": identifier_map,
        "names": name_map,
        "merges": merges,
        "conflicted": {entry["employee_no"] for entry in entries if entry["conflicted"]},
        "conflicts": conflicts,
    }


def disabled():
    return {
        "active": False,
        "policy": STRICT,
        "version": IDENTITY_VERSION,
        "decision": DECISION,
        "entries": {},
        "identifiers": {},
        "names": {},
        "merges": [],
        "conflicted": set(),
        "conflicts": [],
    }


def from_params(params):
    """identities 缺省使用仓内目录；显式空列表或 identity_enabled=false 关闭。"""
    params = params or {}
    if params.get("identity_enabled") is False:
        return disabled()
    policy = params.get("identity_policy") or params.get("policy") or STRICT
    for key in ("identities", "directory", "principals"):
        if key in params:
            directory = params[key]
            if directory is None:
                return disabled()
            if isinstance(directory, list) and not directory:
                return disabled()
            return build(directory, policy)
    return build(DEFAULT_DIRECTORY, policy)


def fingerprint(index):
    payload = {
        "version": index.get("version"),
        "policy": index.get("policy"),
        "active": index.get("active"),
        "entries": sorted(
            (
                {
                    "employee_no": entry["employee_no"],
                    "name": entry["name"],
                    "cost_center": entry["cost_center"],
                    "historical_nos": entry["historical_nos"],
                    "accounts": entry["accounts"],
                }
                for entry in index.get("entries", {}).values()
            ),
            key=lambda item: item["employee_no"],
        ),
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def resolve(identifier, index):
    """返回 (主键或 None, 状态, 证据列表)。状态才是归档依据。"""
    if not index.get("active"):
        return identifier, "not_applicable", []
    text = "" if identifier is None else str(identifier).strip()
    owners = sorted(index["identifiers"].get(text, ()))
    if owners:
        if len(owners) > 1:
            return None, "conflict", [{"reason": "标识同时指向多个主体", "candidates": owners}]
        owner = owners[0]
        entry = index["entries"][owner]
        if owner in index["conflicted"]:
            return None, "conflict", [{"reason": "主体共同凭据存在冲突", "candidates": [owner]}]
        if not entry["complete"]:
            return owner, "incomplete", [{
                "reason": "主体凭据不完整",
                "candidates": [owner],
                "missing": _missing(entry),
            }]
        return owner, "resolved", [{
            "source": entry["source"],
            "identifier": text,
            "employee_no": owner,
            "name": entry["name"],
            "cost_center": entry["cost_center"],
        }]
    candidates = sorted(index["names"].get(text, ()))
    if len(candidates) > 1:
        return None, "ambiguous", [{"reason": "姓名对应多个主体，不能按姓名合并", "candidates": candidates}]
    if candidates:
        return None, "name_only", [{"reason": "姓名不是唯一标识，不能单独归属", "candidates": candidates}]
    return None, "unresolved", [{"reason": "主体未在目录中登记"}]


REASON_BY_STATUS = {
    "conflict": "IDENTITY_CONFLICT",
    "ambiguous": "IDENTITY_AMBIGUOUS",
    "name_only": "IDENTITY_NAME_ONLY",
    "unresolved": "IDENTITY_UNRESOLVED",
    "incomplete": "IDENTITY_INCOMPLETE",
}


def attribute_grants(grants, index):
    """把授权规则里的主体标识解析到同一主键；不能唯一归属的授权不参与命中。"""
    resolved, issues = [], []
    for grant in grants:
        principal = grant.get("principal", "")
        owner, status, evidence = resolve(principal, index)
        item = {**grant, "principal_original": principal, "identity_status": status}
        if status in {"resolved", "not_applicable"}:
            item["principal"] = owner
        else:
            item["principal"] = None
            detail = evidence[0] if evidence else {}
            issues.append({
                "grant_id": grant.get("id", ""),
                "identifier": principal,
                "status": status,
                "reason": detail.get("reason", ""),
                "candidates": detail.get("candidates", []),
                "missing": detail.get("missing", []),
            })
        resolved.append(item)
    return resolved, issues


def attribute(rows, index):
    """把每行原始标识归属到唯一主键；不能唯一归属或凭据不完整的行进入隔离。"""
    from app.reasons import reject

    good, bad = [], []
    for row in rows:
        original = row.get("principal", "")
        owner, status, evidence = resolve(original, index)
        if status in {"resolved", "not_applicable"}:
            attributed = {
                **row,
                "principal_original": original,
                "principal": owner,
                "identity_status": status,
                "identity_evidence": evidence,
            }
            if status == "resolved":
                attributed["identity_source"] = evidence[0]["source"]
                attributed["identity_name"] = evidence[0]["name"]
                attributed["identity_cost_center"] = evidence[0]["cost_center"]
            good.append(attributed)
            continue
        detail = evidence[0].get("reason", "") if evidence else ""
        missing = evidence[0].get("missing", []) if evidence else []
        if missing:
            detail = f"{detail}（缺少：{', '.join(missing)}）"
        bad.append(reject({
            **row,
            "principal_original": original,
            "identity_status": status,
            "identity_evidence": evidence,
        }, REASON_BY_STATUS[status], detail))
    return {"rows": good, "quarantine": bad}


def document(index, referenced):
    """生成每批唯一的主体归属结论。referenced 为原始标识集合。"""
    referenced = sorted({str(item).strip() for item in referenced if item is not None and str(item).strip()})
    if not index.get("active"):
        return {
            "active": False,
            "policy": DECISION["chosen"],
            "version": IDENTITY_VERSION,
            "decision": DECISION,
            "conclusions": [],
            "unresolved": [],
            "conflicts": [],
            "original_identifiers": referenced,
            "metrics": {
                "referenced": len(referenced),
                "resolved": 0,
                "unresolved": 0,
                "ambiguous": 0,
                "conflicts": 0,
                "incomplete": 0,
                "complete": True,
            },
        }
    groups = {}
    unresolved = []
    for identifier in referenced:
        owner, status, evidence = resolve(identifier, index)
        if owner:
            group = groups.setdefault(owner, {"status": status, "referenced": [], "evidence": []})
            group["referenced"].append(identifier)
            group["evidence"].extend(evidence)
            if status != "resolved":
                group["status"] = status
        else:
            detail = evidence[0] if evidence else {}
            unresolved.append({
                "identifier": identifier,
                "status": status,
                "reason": detail.get("reason", ""),
                "candidates": detail.get("candidates", []),
                "missing": detail.get("missing", []),
            })
    conclusions = []
    for owner in sorted(groups):
        entry = index["entries"][owner]
        group = groups[owner]
        conclusions.append({
            "principal": owner,
            "employee_no": owner,
            "name": entry["name"],
            "cost_center": entry["cost_center"],
            "historical_nos": list(entry["historical_nos"]),
            "accounts": list(entry["accounts"]),
            "identifiers": list(entry["identifiers"]),
            "referenced": sorted(set(group["referenced"])),
            "status": group["status"],
            "credential_complete": entry["complete"],
            "evidence": group["evidence"],
        })
    blocking = list(unresolved)
    blocking += [item for item in conclusions if item["status"] != "resolved"]
    metrics = {
        "referenced": len(referenced),
        "resolved": sum(item["status"] == "resolved" for item in conclusions),
        "unresolved": len(unresolved),
        "ambiguous": sum(item["status"] == "ambiguous" for item in unresolved),
        "conflicts": sum(item["status"] == "conflict" for item in unresolved),
        "incomplete": sum(item["status"] == "incomplete" for item in conclusions),
        "complete": not blocking,
    }
    return {
        "active": True,
        "policy": index.get("policy", STRICT),
        "version": IDENTITY_VERSION,
        "decision": DECISION,
        "conclusions": conclusions,
        "unresolved": unresolved,
        "conflicts": index["conflicts"],
        "original_identifiers": referenced,
        "metrics": metrics,
    }
