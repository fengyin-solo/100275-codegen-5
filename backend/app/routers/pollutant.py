"""船舶污染物接收接口：填报、打回、确认、上岸转运与接收汇总。

身份约定：前端通过请求头 X-Operator-Id 带上当前操作人的 ASCII 登录标识，
可选再带 X-Operator-Role（chief_mate/supervisor/env_officer）做角色交叉校验；
HTTP 头只支持 latin-1，中文姓名/角色不能直接放头里，由后端按 id 对出名册。
为便于命令行调试，导出类 GET 也接受 operator_id 查询参数。越权操作不抛 500，
统一回 200 + ok=False，把“当前角色缺哪项权限”讲清楚。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query

from app.schemas import EntryPayload, PageResult
from app.services.pollutant import (
    ROLE_CODES,
    ROLES,
    PermissionDenied,
    PollutantService,
)

router = APIRouter(prefix="/api/pollutant", tags=["船舶污染物接收"])

service = PollutantService()


def _identity(
    operator_id: str | None, role_code: str | None, q_operator_id: str | None = None
) -> dict[str, str]:
    op_id = (operator_id or q_operator_id or "").strip()
    if not op_id:
        raise HTTPException(
            status_code=401,
            detail="缺少操作身份：请先在页面右上角选择当前角色（请求头 X-Operator-Id）",
        )
    claimed_role = ""
    if role_code:
        claimed_role = ROLE_CODES.get(role_code.strip(), "")
        if not claimed_role:
            raise HTTPException(
                status_code=400,
                detail=f"未知角色编码「{role_code}」，合法值：{', '.join(ROLE_CODES)}",
            )
    try:
        return service.resolve_identity(op_id, claimed_role)
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=exc.detail) from exc


def _denied(exc: PermissionDenied) -> dict[str, Any]:
    """越权结果：带上缺失权限，方便前端当场指出。"""
    return {
        "ok": False,
        "message": exc.detail,
        "entry": None,
        "role": exc.role,
        "missingPermission": exc.permission,
    }


@router.get("/identity")
def identity(
    x_operator_id: str | None = Header(default=None),
    x_operator_role: str | None = Header(default=None),
) -> dict[str, Any]:
    """返回当前操作人的角色、权限与可见范围说明，供前端按角色渲染按钮。"""
    from app.services.pollutant import ROLE_PERMISSIONS, ROSTER

    if not x_operator_id:
        return {
            "authenticated": False,
            "roles": ROLES,
            "operators": [
                {"id": p["id"], "name": p["name"], "role": p["role"],
                 "roleCode": next((c for c, r in ROLE_CODES.items() if r == p["role"]), ""),
                 "vessel": p["vessel"], "voyage": p["voyage"]}
                for p in ROSTER
            ],
        }
    claimed = ROLE_CODES.get((x_operator_role or "").strip(), "")
    try:
        person = service.resolve_identity(x_operator_id.strip(), claimed)
    except PermissionDenied as exc:
        return {"authenticated": False, "message": exc.detail, "roles": ROLES}
    return {
        "authenticated": True,
        "id": person["id"],
        "name": person["name"],
        "role": person["role"],
        "vessel": person["vessel"],
        "voyage": person["voyage"],
        "permissions": sorted(ROLE_PERMISSIONS[person["role"]]),
    }


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按接收单号、船名、航次检索"),
    status: str | None = Query(default=None, description="单据状态过滤"),
    page: int = 1,
    size: int = 20,
    x_operator_id: str | None = Header(default=None),
    x_operator_role: str | None = Header(default=None),
) -> PageResult[dict]:
    """按角色可见范围返回接收单据；大副只见本航次自己的，环保专责只见已上岸转运的。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    person = _identity(x_operator_id, x_operator_role)
    items, total = service.list_entries(person, keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/summary")
def get_summary(
    x_operator_id: str | None = Header(default=None),
    x_operator_role: str | None = Header(default=None),
) -> dict[str, Any]:
    """接收汇总：数量与接收单据逐张对账，任一持有查看权限的角色均可看自己范围内的汇总。"""
    person = _identity(x_operator_id, x_operator_role)
    return service.summary(person)


@router.get("/export/all")
def export_entries(
    x_operator_id: str | None = Header(default=None),
    x_operator_role: str | None = Header(default=None),
    operator_id: str | None = Query(default=None),
) -> dict[str, Any]:
    """导出当前角色可见范围内的接收清单与汇总（与页面汇总同一口径）。"""
    person = _identity(x_operator_id, x_operator_role, operator_id)
    items, total = service.list_entries(person, page=1, size=10000)
    return {"module": "pollutant", "total": total, "items": items, "summary": service.summary(person)}


@router.get("/{entry_id}")
def get_entry(
    entry_id: int,
    x_operator_id: str | None = Header(default=None),
    x_operator_role: str | None = Header(default=None),
) -> dict[str, Any]:
    person = _identity(x_operator_id, x_operator_role)
    entry = service.get_entry(entry_id, person)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"接收单据 {entry_id} 不存在或不在你的查看范围内")
    return entry


@router.get("/{entry_id}/history")
def get_history(
    entry_id: int,
    x_operator_id: str | None = Header(default=None),
    x_operator_role: str | None = Header(default=None),
) -> dict[str, Any]:
    """操作记录：谁在什么时候改过接收量、打过回，全部可查。"""
    person = _identity(x_operator_id, x_operator_role)
    entry = service.get_entry(entry_id, person)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"接收单据 {entry_id} 不存在或不在你的查看范围内")
    return {"entryId": entry_id, "接收单号": entry["接收单号"], "items": service.history(entry_id, person)}


@router.post("")
def create_entry(
    payload: EntryPayload,
    x_operator_id: str | None = Header(default=None),
    x_operator_role: str | None = Header(default=None),
) -> dict[str, Any]:
    """填报本航次接收单据；越权填报、重复提交都会被驳回并说明原因。"""
    person = _identity(x_operator_id, x_operator_role)
    try:
        entry, missing, denied = service.create_entry(payload.values, person)
    except PermissionDenied as exc:
        return _denied(exc)
    if denied is not None:
        return _denied(denied)
    if missing:
        return {"ok": False, "message": f"缺少必填字段：{'、'.join(missing)}", "entry": None}
    return {"ok": True, "message": f"接收单据 {entry['接收单号']} 已填报，操作归属已固定为 {person['name']}",
            "entry": entry}


@router.put("/{entry_id}/quantities")
def update_quantities(
    entry_id: int,
    payload: EntryPayload,
    x_operator_id: str | None = Header(default=None),
    x_operator_role: str | None = Header(default=None),
) -> dict[str, Any]:
    """修改接收量（仅被打回、由原填报大副修改），每次变更写入操作记录。"""
    person = _identity(x_operator_id, x_operator_role)
    try:
        entry, message, denied = service.update_quantities(entry_id, payload.values, person)
    except PermissionDenied as exc:
        return _denied(exc)
    if denied is not None:
        return _denied(denied)
    if entry is None:
        return {"ok": False, "message": message, "entry": None}
    return {"ok": True, "message": message, "entry": entry}


@router.post("/{entry_id}/actions")
def run_action(
    entry_id: int,
    payload: EntryPayload,
    x_operator_id: str | None = Header(default=None),
    x_operator_role: str | None = Header(default=None),
) -> dict[str, Any]:
    """打回重报（需理由）、重新提交、确认接收、登记上岸转运；改派类动作一律驳回。"""
    person = _identity(x_operator_id, x_operator_role)
    action = str(payload.values.get("action") or "").strip()
    try:
        entry, message, denied = service.run_action(entry_id, action, person, payload.values)
    except PermissionDenied as exc:
        return _denied(exc)
    if denied is not None:
        return _denied(denied)
    if entry is None:
        return {"ok": False, "message": message, "entry": None}
    return {"ok": True, "message": message, "entry": entry}


@router.post("/{entry_id}/reassign")
def reassign_entry(
    entry_id: int,
    payload: EntryPayload,
    x_operator_id: str | None = Header(default=None),
    x_operator_role: str | None = Header(default=None),
) -> dict[str, Any]:
    """把单据改到别人名下：任何角色都缺「单据改派」权限，当场驳回并指出越权。"""
    person = _identity(x_operator_id, x_operator_role)
    target_id = str(payload.values.get("targetId") or "").strip()
    target_name = ""
    if target_id:
        try:
            target_name = service.resolve_identity(target_id)["name"]
        except PermissionDenied:
            target_name = target_id
    _, denied = service.reassign(entry_id, target_name, person)
    return _denied(denied)
