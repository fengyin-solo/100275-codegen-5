"""船舶污染物接收单据业务规则。

归属固定：单据的"原填报人"只由服务端按 X-Operator-Id 写入，任何入参里夹带的
填报人/改名人都不采信；人员调班后姓名仍从人员名册取，历史单据的归属不变。

数量留痕：接收量每次变化追加一条审计记录（原值→新值、改动量、操作人），
"接收量被谁改过"随时可查。

唯一性：同一艘船同一航次只认第一次提交的单据，后续重复提交当场 409 驳回；
被打回的单据由原填报人修改后重新提交，不会产生第二张单。

汇总对账：汇总数量不另行维护，始终从单据明细实时聚合，保证"汇总 = 单据"。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.security import (
    OPERATORS,
    Operator,
    PERM_CONFIRM,
    PERM_CREATE,
    PERM_EDIT,
    PERM_REJECT,
    PERM_TRANSFER,
    require,
)
from app.store import store

MODULE = "pollutant"

# 污染物类别与标准单位：前端按类别展示，汇总按类别对账。
POLLUTANT_UNITS: dict[str, str] = {
    "含油污水": "立方米",
    "生活污水": "立方米",
    "生活垃圾": "千克",
    "食品废弃物": "千克",
    "废矿物油": "升",
}

# 状态机：待确认 →（打回）→ 待修改 →（重新提交）→ 待确认 → 已接收 → 已完成上岸转运
STATUS_PENDING = "待码头确认"
STATUS_REJECTED = "已打回"
STATUS_RECEIVED = "已接收"
STATUS_TRANSFERRED = "已完成上岸转运"
FLOW_STATUSES = [STATUS_PENDING, STATUS_REJECTED, STATUS_RECEIVED, STATUS_TRANSFERRED]


class BusinessError(Exception):
    """业务规则不满足（区别于越权）：路由层转成对应 4xx。"""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _filed_by_name(operator_id: str) -> str:
    """原填报人姓名始终取人员名册：调班、改名都不影响历史单据显示。"""
    person = OPERATORS.get(operator_id)
    return person["name"] if person else f"未知人员({operator_id})"


def parse_details(values: dict[str, Any]) -> tuple[dict[str, float], list[str]]:
    """从提交内容里解析各类污染物接收量，返回 {类别: 数量} 与错误说明。"""
    errors: list[str] = []
    details: dict[str, float] = {}

    raw = values.get("污染物明细")
    if isinstance(raw, dict):
        for category, amount in raw.items():
            if category not in POLLUTANT_UNITS:
                errors.append(f"污染物类别「{category}」不在接收目录内")
                continue
            try:
                quantity = float(amount)
            except (TypeError, ValueError):
                errors.append(f"「{category}」的接收量必须是数字")
                continue
            if quantity < 0:
                errors.append(f"「{category}」的接收量不能为负数")
                continue
            if quantity > 0:
                details[category] = round(quantity, 3)
    else:
        # 兼容按字段平铺提交：含油污水量、生活垃圾量……
        for category, unit in POLLUTANT_UNITS.items():
            amount = values.get(f"{category}量")
            if amount in (None, ""):
                continue
            try:
                quantity = float(amount)
            except (TypeError, ValueError):
                errors.append(f"「{category}」的接收量必须是数字")
                continue
            if quantity < 0:
                errors.append(f"「{category}」的接收量不能为负数")
                continue
            if quantity > 0:
                details[category] = round(quantity, 3)

    if not errors and not details:
        errors.append("至少要填报一类污染物的接收量")
    return details, errors


def _total_amount(details: dict[str, float]) -> float:
    return round(sum(details.values()), 3)


def _details_view(details: dict[str, float]) -> list[dict[str, Any]]:
    return [
        {"类别": category, "数量": amount, "单位": POLLUTANT_UNITS[category]}
        for category, amount in details.items()
    ]


def _append_log(entry: dict[str, Any], log: dict[str, Any]) -> None:
    # 留痕只追加在单据自身的"操作记录"上，不另建数据表，保证谁改的量随时可查。
    entry.setdefault("操作记录", []).append(log)


def _public(entry: dict[str, Any]) -> dict[str, Any]:
    """对外视图：把内部 details 还原成带单位的明细，并补原填报人当前姓名。"""
    view = dict(entry)
    filed_id = str(entry.get("填报人ID", ""))
    view["原填报人"] = _filed_by_name(filed_id)
    view["原填报人在岗"] = bool(OPERATORS.get(filed_id, {}).get("active", False))
    view["污染物明细"] = _details_view(entry.get("details", {}))
    view["接收总量"] = _total_amount(entry.get("details", {}))
    return view


class PollutantService:
    # ---------------------------------------------------------------- 列表/详情
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        ship: str | None = None,
        voyage: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("单据编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        if ship:
            rows = [row for row in rows if str(row.get("船名", "")) == ship]
        if voyage:
            rows = [row for row in rows if str(row.get("航次", "")) == voyage]
        total = len(rows)
        start = max(page - 1, 0) * size
        return [_public(row) for row in rows[start:start + size]], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        return _public(entry) if entry else None

    def get_logs(self, entry_id: int) -> list[dict[str, Any]]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            raise BusinessError(f"接收单据 {entry_id} 不存在或已归档", 404)
        return list(entry.get("操作记录", []))

    # ---------------------------------------------------------------- 填报
    def create_entry(self, operator: Operator, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        require(operator, PERM_CREATE, "填报船舶污染物接收单据")

        ship = str(values.get("船名") or "").strip()
        voyage = str(values.get("航次") or "").strip()
        missing = [name for name, value in (("船名", ship), ("航次", voyage)) if not value]
        details, errors = parse_details(values)
        if missing:
            return None, [f"缺少必填字段：{'、'.join(missing)}"]
        if errors:
            return None, errors

        # 大副只能填报自己所在船舶本航次的单据：船名/航次必须与名册绑定一致。
        bound = OPERATORS[operator.id]
        if bound.get("ship") and ship != bound["ship"]:
            require(operator, "pollutant:create:other-ship", f"为船舶「{ship}」填报（本航次所在船舶为「{bound['ship']}」）")
        if bound.get("voyage") and voyage != bound["voyage"]:
            require(operator, "pollutant:create:other-voyage", f"填报航次「{voyage}」（本人绑定航次为「{bound['voyage']}」）")

        # 同一艘船同一航次只认第一次提交：重复提交当场驳回。
        duplicate = self._find_valid(ship, voyage)
        if duplicate is not None:
            first = _public(duplicate)
            raise BusinessError(
                f"船舶「{ship}」航次「{voyage}」已存在接收单据 {first['单据编号']}"
                f"（{first['status']}，原填报人：{first['原填报人']}），同一航次只认第一次提交的单据",
                409,
            )

        rows = store.rows(MODULE)
        entry_id = max((int(row.get("id", 0)) for row in rows), default=0) + 1
        entry = {
            "id": entry_id,
            "单据编号": f"PRC-{datetime.now():%Y%m%d}-{entry_id:04d}",
            "船名": ship,
            "航次": voyage,
            "details": details,
            "填报人ID": operator.id,          # 归属固定：只认服务端身份，不采信入参
            "填报时间": _now(),
            "status": STATUS_PENDING,
            "pending": True,
            "abnormal": False,
            "驳回理由": "",
            "打回人ID": "",
            "确认人ID": "",
            "转运人ID": "",
            "转运登记时间": "",
            "操作记录": [],
        }
        _append_log(entry, {
            "单据ID": entry_id,
            "时间": entry["填报时间"],
            "动作": "提交接收单据",
            "操作人ID": operator.id,
            "操作人": operator.name,
            "操作人角色": operator.role_label,
            "数量变化": [
                {"类别": category, "原值": 0.0, "新值": amount,
                 "改动量": amount, "单位": POLLUTANT_UNITS[category]}
                for category, amount in details.items()
            ],
            "说明": "首次填报",
        })
        rows.append(entry)
        return _public(entry), []

    # ---------------------------------------------------------------- 修改接收量
    def edit_entry(self, operator: Operator, entry_id: int, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        require(operator, PERM_EDIT, "修改接收单据内容")
        entry = store.find(MODULE, entry_id)
        if entry is None:
            raise BusinessError(f"接收单据 {entry_id} 不存在或已归档", 404)

        # 改到别人名下：无论入参里把填报人改成谁，一律当场驳回并指出越权。
        claimed = values.get("填报人ID") or values.get("原填报人") or values.get("填报人")
        if claimed and str(claimed).strip() not in {operator.id, operator.name, ""}:
            require(operator, "pollutant:reassign",
                    f"试图把单据 {entry['单据编号']} 的填报人改挂到「{claimed}」名下")

        if str(entry["填报人ID"]) != operator.id:
            require(operator, "pollutant:edit:others",
                    f"修改他人填报的单据 {entry['单据编号']}（原填报人：{_filed_by_name(str(entry['填报人ID']))}）")

        if entry["status"] == STATUS_TRANSFERRED:
            raise BusinessError(
                f"单据 {entry['单据编号']} 已完成上岸转运，按规定锁定，任何人不得再改接收量", 409)
        if entry["status"] == STATUS_RECEIVED:
            raise BusinessError(
                f"单据 {entry['单据编号']} 码头已确认接收，接收量已锁定；如需变更请先由值班长打回", 409)
        if entry["status"] == STATUS_REJECTED:
            raise BusinessError(
                f"单据 {entry['单据编号']} 已被打回，请按打回理由修订后走「重新提交」，不能直接覆盖", 409)

        details, errors = parse_details(values)
        if errors:
            return None, errors

        old_details: dict[str, float] = entry["details"]
        changes: list[dict[str, Any]] = []
        for category in sorted(set(old_details) | set(details)):
            old_value = old_details.get(category, 0.0)
            new_value = details.get(category, 0.0)
            if round(new_value - old_value, 3) != 0:
                changes.append({
                    "类别": category,
                    "原值": old_value,
                    "新值": new_value,
                    "改动量": round(new_value - old_value, 3),
                    "单位": POLLUTANT_UNITS[category],
                })
        if not changes:
            raise BusinessError("本次提交的接收量与单据现有数量一致，没有可保存的改动")

        entry["details"] = details
        _append_log(entry, {
            "单据ID": entry_id,
            "时间": _now(),
            "动作": "修改接收量",
            "操作人ID": operator.id,
            "操作人": operator.name,
            "操作人角色": operator.role_label,
            "数量变化": changes,
            "说明": str(values.get("修改说明") or "大副修订接收量"),
        })
        return _public(entry), []

    # ---------------------------------------------------------------- 重新提交
    def resubmit_entry(self, operator: Operator, entry_id: int, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        """被打回的单据由原填报人改好后重新提交：同一航次仍是这一张单。"""
        require(operator, PERM_EDIT, "重新提交被打回的接收单据")
        entry = store.find(MODULE, entry_id)
        if entry is None:
            raise BusinessError(f"接收单据 {entry_id} 不存在或已归档", 404)
        if str(entry["填报人ID"]) != operator.id:
            require(operator, "pollutant:edit:others",
                    f"重新提交他人填报的单据 {entry['单据编号']}（原填报人：{_filed_by_name(str(entry['填报人ID']))}）")
        if entry["status"] != STATUS_REJECTED:
            raise BusinessError(f"单据 {entry['单据编号']} 当前为「{entry['status']}」，只有被打回的单据才能重新提交", 409)

        details, errors = parse_details(values)
        if errors:
            return None, errors

        old_details: dict[str, float] = entry["details"]
        changes = []
        for category in sorted(set(old_details) | set(details)):
            old_value = old_details.get(category, 0.0)
            new_value = details.get(category, 0.0)
            if round(new_value - old_value, 3) != 0:
                changes.append({
                    "类别": category, "原值": old_value, "新值": new_value,
                    "改动量": round(new_value - old_value, 3),
                    "单位": POLLUTANT_UNITS[category],
                })

        entry["details"] = details
        entry["status"] = STATUS_PENDING
        entry["pending"] = True
        entry["abnormal"] = False
        entry["驳回理由"] = ""
        _append_log(entry, {
            "单据ID": entry_id,
            "时间": _now(),
            "动作": "修改后重新提交",
            "操作人ID": operator.id,
            "操作人": operator.name,
            "操作人角色": operator.role_label,
            "数量变化": changes,
            "说明": str(values.get("修改说明") or "按打回意见修订后重新提交"),
        })
        return _public(entry), []

    # ---------------------------------------------------------------- 打回
    def reject_entry(self, operator: Operator, entry_id: int, reason: str) -> dict[str, Any]:
        require(operator, PERM_REJECT, "打回接收单据")
        entry = store.find(MODULE, entry_id)
        if entry is None:
            raise BusinessError(f"接收单据 {entry_id} 不存在或已归档", 404)
        reason = (reason or "").strip()
        if not reason:
            raise BusinessError("打回必须写明理由，原填报人需要知道哪里不合格")
        if entry["status"] != STATUS_PENDING:
            raise BusinessError(f"单据 {entry['单据编号']} 当前为「{entry['status']}」，只有待确认的单据能打回", 409)

        entry["status"] = STATUS_REJECTED
        entry["pending"] = False
        entry["abnormal"] = True
        entry["驳回理由"] = reason
        entry["打回人ID"] = operator.id
        _append_log(entry, {
            "单据ID": entry_id,
            "时间": _now(),
            "动作": "打回单据",
            "操作人ID": operator.id,
            "操作人": operator.name,
            "操作人角色": operator.role_label,
            "数量变化": [],
            "说明": f"打回理由：{reason}",
        })
        return _public(entry)

    # ---------------------------------------------------------------- 码头确认接收
    def confirm_entry(self, operator: Operator, entry_id: int) -> dict[str, Any]:
        require(operator, PERM_CONFIRM, "确认接收污染物")
        entry = store.find(MODULE, entry_id)
        if entry is None:
            raise BusinessError(f"接收单据 {entry_id} 不存在或已归档", 404)
        if entry["status"] != STATUS_PENDING:
            raise BusinessError(f"单据 {entry['单据编号']} 当前为「{entry['status']}」，只有待确认的单据能确认接收", 409)

        entry["status"] = STATUS_RECEIVED
        entry["pending"] = False
        entry["abnormal"] = False
        entry["确认人ID"] = operator.id
        _append_log(entry, {
            "单据ID": entry_id,
            "时间": _now(),
            "动作": "确认接收",
            "操作人ID": operator.id,
            "操作人": operator.name,
            "操作人角色": operator.role_label,
            "数量变化": [],
            "说明": "码头核对后确认接收，接收量就此锁定",
        })
        return _public(entry)

    # ---------------------------------------------------------------- 登记完成上岸转运
    def transfer_entry(self, operator: Operator, entry_id: int) -> dict[str, Any]:
        require(operator, PERM_TRANSFER, "登记完成上岸转运")
        entry = store.find(MODULE, entry_id)
        if entry is None:
            raise BusinessError(f"接收单据 {entry_id} 不存在或已归档", 404)
        if entry["status"] != STATUS_RECEIVED:
            raise BusinessError(f"单据 {entry['单据编号']} 当前为「{entry['status']}」，已接收的单据才能登记上岸转运", 409)

        entry["status"] = STATUS_TRANSFERRED
        entry["pending"] = False
        entry["abnormal"] = False
        entry["转运人ID"] = operator.id
        entry["转运登记时间"] = _now()
        _append_log(entry, {
            "单据ID": entry_id,
            "时间": entry["转运登记时间"],
            "动作": "登记完成上岸转运",
            "操作人ID": operator.id,
            "操作人": operator.name,
            "操作人角色": operator.role_label,
            "数量变化": [],
            "说明": "完成上岸转运登记，单据转为只读",
        })
        return _public(entry)

    # ---------------------------------------------------------------- 汇总对账
    def summary(self, *, scope: str = "effective") -> dict[str, Any]:
        """接收汇总：数量始终从接收单据实时聚合，不另存一份，结构上保证对得上。

        scope=effective：只统计仍有效的单据（被打回修订中的旧数量不计入）；
        scope=transferred：环保专责关心的口径，只统计已完成上岸转运的单据。
        """
        rows = store.rows(MODULE)
        if scope == "transferred":
            rows = [row for row in rows if row["status"] == STATUS_TRANSFERRED]
        else:
            rows = [row for row in rows if row["status"] != STATUS_REJECTED]

        by_category = {category: 0.0 for category in POLLUTANT_UNITS}
        groups: list[dict[str, Any]] = []
        for row in rows:
            details: dict[str, float] = row.get("details", {})
            for category, amount in details.items():
                by_category[category] = round(by_category.get(category, 0.0) + amount, 3)
            groups.append({
                "单据编号": row["单据编号"],
                "船名": row["船名"],
                "航次": row["航次"],
                "状态": row["status"],
                "原填报人": _filed_by_name(str(row["填报人ID"])),
                "污染物明细": _details_view(details),
                "接收总量": _total_amount(details),
            })

        category_totals = [
            {"类别": category, "数量": amount, "单位": POLLUTANT_UNITS[category]}
            for category, amount in by_category.items()
        ]
        grand_total = round(sum(by_category.values()), 3)

        # 逐单据回算求和，与分类合计交叉核对；任何不一致都在 matched=False 里点名。
        recomputed = round(sum(item["接收总量"] for item in groups), 3)
        matched = recomputed == grand_total
        # 唯一性自检：同船同航次不允许出现两张有效单据（否则"只认第一次"被破坏）。
        keys = [(item["船名"], item["航次"]) for item in groups]
        duplicates = sorted({key for key in keys if keys.count(key) > 1})
        return {
            "口径": "已完成上岸转运" if scope == "transferred" else "全部有效单据",
            "单据数": len(groups),
            "分类合计": category_totals,
            "数量总计": grand_total,
            "按单据": groups,
            "对账": {
                "matched": matched and not duplicates,
                "单据逐项求和": recomputed,
                "分类合计求和": grand_total,
                "差异": round(grand_total - recomputed, 3),
                "重复船次": [{"船名": ship, "航次": voyage} for ship, voyage in duplicates],
            },
        }

    # ---------------------------------------------------------------- helpers
    def _find_valid(self, ship: str, voyage: str) -> dict[str, Any] | None:
        """同船同航次已认下的单据：被打回的不算重复（它仍是本航次唯一一张单）。"""
        for row in store.rows(MODULE):
            if str(row.get("船名")) == ship and str(row.get("航次")) == voyage:
                return row
        return None
