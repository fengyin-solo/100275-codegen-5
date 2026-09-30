"""船舶污染物接收单据接口：填报、打回、确认、上岸转运、留痕查询与汇总对账。

所有写接口都要求请求头 X-Operator-Id 指定当前操作人；越权统一返回 403，
消息里点明当前角色缺少的权限点。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.security import (
    OPERATORS,
    Operator,
    PermissionDenied,
    ROLE_LABELS,
    ROLE_PERMISSIONS,
    current_operator,
    operator_public,
)
from app.services.pollutant import (
    FLOW_STATUSES,
    PollutantService,
)

router = APIRouter(prefix="/api/pollutant", tags=["船舶污染物接收"])

service = PollutantService()


def _denied(exc: PermissionDenied) -> HTTPException:
    """越权：403 当场驳回，结构化返回角色、缺失权限与可读原因。"""
    return exc.http()


def _business(exc: Exception) -> HTTPException:
    status = getattr(exc, "status_code", 400)
    return HTTPException(status_code=status, detail={"code": "business_rule", "message": str(exc)})


@router.get("/operators")
def list_operators() -> dict[str, Any]:
    """人员名册：供前端切换当前操作身份（模拟登录），调班离岗的人员置灰。"""
    return {
        "roles": [{"code": code, "label": label, "permissions": sorted(perms)}
                  for code, label in ROLE_LABELS.items()
                  for perms in [ROLE_PERMISSIONS[code]]],
        "operators": [operator_public(key) for key in OPERATORS],
    }


@router.get("/me")
def me(operator: Operator = Depends(current_operator)) -> dict[str, Any]:
    """确认当前操作身份及其权限点。"""
    return operator_public(operator.id) or {}


# 注意：/summary、/export 这类固定路径要排在 /{entry_id} 之前，否则会被当成单据 ID。
@router.get("/summary")
def receiving_summary(scope: str = Query(default="effective", description="effective=有效单据；transferred=已完成上岸转运")) -> dict[str, Any]:
    """接收汇总：数量实时从接收单据聚合，并附带与单据逐项对账的结果。"""
    if scope not in {"effective", "transferred"}:
        raise HTTPException(status_code=400, detail="scope 只支持 effective 或 transferred")
    return service.summary(scope=scope)


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按单据编号检索"),
    status: str | None = Query(default=None, description=f"状态：{'、'.join(FLOW_STATUSES)}"),
    ship: str | None = None,
    voyage: str | None = None,
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, ship=ship, voyage=voyage, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{entry_id}")
def get_entry(entry_id: int) -> dict[str, Any]:
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"接收单据 {entry_id} 不存在或已归档")
    return entry


@router.get("/{entry_id}/logs")
def get_logs(entry_id: int) -> dict[str, Any]:
    """数量改动留痕：谁、什么时候、把哪类污染物从多少改成多少，逐条可查。"""
    try:
        return {"entryId": entry_id, "logs": service.get_logs(entry_id)}
    except Exception as exc:  # noqa: BLE001 - 仅业务错误一种来源
        raise _business(exc) from exc


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload, operator: Operator = Depends(current_operator)) -> ActionResult:
    """船上大副填报本航次接收单据；重复船次 409，越权 403 并点明缺失权限。"""
    try:
        entry, problems = service.create_entry(operator, payload.values)
    except PermissionDenied as exc:
        raise _denied(exc) from exc
    except Exception as exc:  # noqa: BLE001
        raise _business(exc) from exc
    if problems:
        return ActionResult(ok=False, message="；".join(problems))
    return ActionResult(ok=True, message=f"接收单据 {entry['单据编号']} 已提交，归属填报人：{operator.name}", entry=entry)  # type: ignore[index]


@router.post("/{entry_id}/edit", response_model=ActionResult)
def edit_entry(entry_id: int, payload: EntryPayload, operator: Operator = Depends(current_operator)) -> ActionResult:
    """修改本人单据的接收量；改挂他人名下或改他人单据一律 403 驳回。"""
    try:
        entry, problems = service.edit_entry(operator, entry_id, payload.values)
    except PermissionDenied as exc:
        raise _denied(exc) from exc
    except Exception as exc:  # noqa: BLE001
        raise _business(exc) from exc
    if problems:
        return ActionResult(ok=False, message="；".join(problems))
    return ActionResult(ok=True, message="接收量已修改并留痕", entry=entry)


@router.post("/{entry_id}/resubmit", response_model=ActionResult)
def resubmit_entry(entry_id: int, payload: EntryPayload, operator: Operator = Depends(current_operator)) -> ActionResult:
    """原填报人按打回理由修订后重新提交；同船同航次仍是这一张单。"""
    try:
        entry, problems = service.resubmit_entry(operator, entry_id, payload.values)
    except PermissionDenied as exc:
        raise _denied(exc) from exc
    except Exception as exc:  # noqa: BLE001
        raise _business(exc) from exc
    if problems:
        return ActionResult(ok=False, message="；".join(problems))
    return ActionResult(ok=True, message="已按修订内容重新提交，等待码头确认", entry=entry)


@router.post("/{entry_id}/reject", response_model=ActionResult)
def reject_entry(entry_id: int, payload: EntryPayload, operator: Operator = Depends(current_operator)) -> ActionResult:
    """码头值班长打回单据，必须写清理由。"""
    reason = str(payload.values.get("理由") or payload.values.get("reason") or "").strip()
    try:
        entry = service.reject_entry(operator, entry_id, reason)
    except PermissionDenied as exc:
        raise _denied(exc) from exc
    except Exception as exc:  # noqa: BLE001
        raise _business(exc) from exc
    return ActionResult(ok=True, message=f"单据已打回，理由已记录：{reason}", entry=entry)


@router.post("/{entry_id}/confirm", response_model=ActionResult)
def confirm_entry(entry_id: int, operator: Operator = Depends(current_operator)) -> ActionResult:
    """码头值班长核对后确认接收，接收量就此锁定。"""
    try:
        entry = service.confirm_entry(operator, entry_id)
    except PermissionDenied as exc:
        raise _denied(exc) from exc
    except Exception as exc:  # noqa: BLE001
        raise _business(exc) from exc
    return ActionResult(ok=True, message="码头已确认接收，接收量锁定", entry=entry)


@router.post("/{entry_id}/transfer", response_model=ActionResult)
def transfer_entry(entry_id: int, operator: Operator = Depends(current_operator)) -> ActionResult:
    """码头值班长登记完成上岸转运；此后单据对所有人只读。"""
    try:
        entry = service.transfer_entry(operator, entry_id)
    except PermissionDenied as exc:
        raise _denied(exc) from exc
    except Exception as exc:  # noqa: BLE001
        raise _business(exc) from exc
    return ActionResult(ok=True, message="已登记完成上岸转运，单据转为只读", entry=entry)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出接收单据清单：返回全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "pollutant", "total": total, "items": items}
