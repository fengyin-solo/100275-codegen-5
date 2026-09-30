"""船舶污染物接收业务规则：操作归属（RBAC）、状态流转、审计留痕与数量汇总。

设计要点（对应业务诉求）：
- 角色固定为 船上大副 / 码头值班长 / 环保专责，按“最小权限”分配动作；
- 单据一旦填报，原填报人（原操作归属）固定不变，任何“改到别人名下”的动作当场驳回，
  并指出当前角色缺少哪项权限；
- 每次数量修改都追加一条操作记录（谁、何时、改了什么），接收量被谁改过可追溯；
- 汇总数量由首次生效的接收单据实时聚合，保证汇总与单据对得上；
- 同一艘船同一航次只认第一次提交的单据，重复提交直接驳回。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.store import store

MODULE = "pollutant"

# 角色
ROLE_CHIEF_MATE = "船上大副"
ROLE_SUPERVISOR = "码头值班长"
ROLE_ENV_OFFICER = "环保专责"
ROLES = [ROLE_CHIEF_MATE, ROLE_SUPERVISOR, ROLE_ENV_OFFICER]

# 角色的 ASCII 编码（HTTP 头只支持 latin-1），供 X-Operator-Role 选用
ROLE_CODES: dict[str, str] = {
    "chief_mate": ROLE_CHIEF_MATE,
    "supervisor": ROLE_SUPERVISOR,
    "env_officer": ROLE_ENV_OFFICER,
}

# 权限项（单据的操作归属）
PERM_VIEW = "接收单据查看"
PERM_SUBMIT = "接收单据填报"
PERM_REJECT = "接收单据打回"
PERM_CONFIRM = "接收单确认"
PERM_TRANSFER = "上岸转运登记"
PERM_EDIT_QTY = "接收量修改"
# 单据改派（把单据改到别人名下）——任何角色都不持有，故所有改派尝试均被驳回
PERM_REASSIGN = "单据改派"

# 角色 → 持有的权限
ROLE_PERMISSIONS: dict[str, set[str]] = {
    ROLE_CHIEF_MATE: {PERM_VIEW, PERM_SUBMIT, PERM_EDIT_QTY},
    ROLE_SUPERVISOR: {PERM_VIEW, PERM_REJECT, PERM_CONFIRM, PERM_TRANSFER},
    ROLE_ENV_OFFICER: {PERM_VIEW},
}

# 演示用人员名册：大副只能填报自己所在船舶/航次的单据；值班长、环保专责不绑定船舶。
# id 为 ASCII 登录标识（HTTP 头只能传 latin-1，中文姓名/角色不能直接放头里），
# 后端按 id 对出名册里的中文姓名与角色。
ROSTER: list[dict[str, str]] = [
    {"id": "chief_zhang", "name": "张伟（大副）", "role": ROLE_CHIEF_MATE, "vessel": "远洋号", "voyage": "V-2409"},
    {"id": "chief_li", "name": "李强（大副）", "role": ROLE_CHIEF_MATE, "vessel": "海运号", "voyage": "V-2409"},
    {"id": "supervisor_wang", "name": "王磊（值班长）", "role": ROLE_SUPERVISOR, "vessel": "", "voyage": ""},
    {"id": "env_zhao", "name": "赵敏（环保专责）", "role": ROLE_ENV_OFFICER, "vessel": "", "voyage": ""},
]

# 单据状态
STATUS_PENDING = "待值班长确认"
STATUS_REJECTED = "已打回"
STATUS_CONFIRMED = "已确认"
STATUS_TRANSFERRED = "已完成上岸转运"

# 接收污染物种类（单位统一为吨/立方米，按重量折算，数值）
QUANTITY_FIELDS = ["生活垃圾", "含油污水", "生活污水", "残油废油"]

REQUIRED_FIELDS = ["船名", "航次"]


class PermissionDenied(Exception):
    """越权操作：携带当前角色与所缺权限，供路由层当场驳回并说明。"""

    def __init__(self, role: str, permission: str, detail: str) -> None:
        self.role = role
        self.permission = permission
        self.detail = detail
        super().__init__(detail)


def roster_for(operator_id: str) -> dict[str, str] | None:
    for person in ROSTER:
        if person["id"] == operator_id:
            return person
    return None


class PollutantService:
    # ---------- 身份与权限 ----------
    def resolve_identity(self, operator_id: str, claimed_role: str = "") -> dict[str, str]:
        """按 ASCII 登录标识对到名册；如携带角色头，角色与名册不符一律不放行。"""
        person = roster_for(operator_id)
        if person is None:
            raise PermissionDenied(claimed_role, PERM_VIEW,
                                   f"操作员账号「{operator_id}」不在污染物接收人员名册内")
        if claimed_role and claimed_role != person["role"]:
            raise PermissionDenied(
                claimed_role,
                PERM_VIEW,
                f"「{person['name']}」的登记角色为{person['role']}，与所持角色{claimed_role}不符",
            )
        return person

    def _require(self, role: str, permission: str) -> None:
        if permission not in ROLE_PERMISSIONS.get(role, set()):
            raise PermissionDenied(
                role,
                permission,
                f"越权操作：当前角色「{role}」缺少「{permission}」权限，该操作已当场驳回",
            )

    # ---------- 可见范围 ----------
    def _can_see(self, entry: dict[str, Any], person: dict[str, str]) -> bool:
        """大副只见本航次自己的单据；值班长见在办单据；环保专责只见已完成上岸转运的单据。"""
        role = person["role"]
        if role == ROLE_CHIEF_MATE:
            return (
                entry.get("原填报人") == person["name"]
                and entry.get("船名") == person["vessel"]
                and entry.get("航次") == person["voyage"]
            )
        if role == ROLE_SUPERVISOR:
            return entry.get("status") != STATUS_TRANSFERRED
        # 环保专责：仅对已完成上岸转运的单据可查看
        return entry.get("status") == STATUS_TRANSFERRED

    # ---------- 查询 ----------
    def list_entries(
        self,
        person: dict[str, str],
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = [row for row in store.rows(MODULE) if self._can_see(row, person)]
        if keyword:
            rows = [
                row
                for row in rows
                if keyword in str(row.get("接收单号", ""))
                or keyword in str(row.get("船名", ""))
                or keyword in str(row.get("航次", ""))
            ]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        rows.sort(key=lambda row: int(row.get("id", 0)), reverse=True)
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int, person: dict[str, str]) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        if entry is None or not self._can_see(entry, person):
            # 不暴露无权查看/不存在单据的区别
            return None
        return entry

    def history(self, entry_id: int, person: dict[str, str]) -> list[dict[str, Any]]:
        entry = self.get_entry(entry_id, person)
        if entry is None:
            return []
        return list(entry.get("操作记录", []))

    # ---------- 填报 ----------
    def create_entry(
        self, values: dict[str, Any], person: dict[str, str]
    ) -> tuple[dict[str, Any] | None, list[str], PermissionDenied | None]:
        try:
            self._require(person["role"], PERM_SUBMIT)
        except PermissionDenied as exc:
            return None, [], exc
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing, None

        vessel = str(values.get("船名")).strip()
        voyage = str(values.get("航次")).strip()
        # 大副只可填报本航次自己的接收单据
        if person["role"] == ROLE_CHIEF_MATE and (
            vessel != person["vessel"] or voyage != person["voyage"]
        ):
            return (
                None,
                [],
                PermissionDenied(
                    person["role"],
                    PERM_SUBMIT,
                    f"越权填报：{person['name']} 只能填报 {person['vessel']}/{person['voyage']} "
                    f"本航次的接收单据，不能替 {vessel}/{voyage} 填报",
                ),
            )

        # 同一艘船同一航次重复提交接收，只认第一次的单据
        existing = self._find_by_vessel_voyage(vessel, voyage)
        if existing is not None:
            return (
                None,
                [],
                PermissionDenied(
                    person["role"],
                    PERM_SUBMIT,
                    f"{vessel}/{voyage} 的接收单据已存在（单号 {existing['接收单号']}），"
                    "同一艘船同一航次只认第一次提交的单据，重复提交已驳回",
                ),
            )

        quantities, qty_error = self._parse_quantities(values, person["role"])
        if qty_error:
            return None, [], qty_error

        rows = store.rows(MODULE)
        entry_id = max((int(row.get("id", 0)) for row in rows), default=0) + 1
        now = self._now()
        entry: dict[str, Any] = {
            "id": entry_id,
            "接收单号": f"POL-{entry_id:04d}",
            "船名": vessel,
            "航次": voyage,
            "原填报人": person["name"],  # 操作归属：首次填报即固定
            "当前填报人": person["name"],
            **quantities,
            "接收时间": now,
            "转运去向": "",
            "打回理由": "",
            "status": STATUS_PENDING,
            "pending": True,
            "abnormal": False,
            "操作记录": [
                {
                    "时间": now,
                    "操作人": person["name"],
                    "角色": person["role"],
                    "动作": "填报提交",
                    "明细": f"首次填报接收量：{self._describe_quantities(quantities)}",
                }
            ],
        }
        rows.append(entry)
        return entry, [], None

    # ---------- 数量修改（留痕） ----------
    def update_quantities(
        self, entry_id: int, values: dict[str, Any], person: dict[str, str]
    ) -> tuple[dict[str, Any] | None, str | None, PermissionDenied | None]:
        # 先做权限判断：让“当前角色缺哪项权限”的驳回优先于可见范围提示。
        try:
            if self._claims_new_owner(values):
                # 改到别人名下属于改派：任何角色都不持有，直接指出缺「单据改派」权限
                return None, None, self._reassign_denial(person["role"])
            self._require(person["role"], PERM_EDIT_QTY)
        except PermissionDenied as exc:
            return None, None, exc

        entry = store.find(MODULE, entry_id)
        if entry is None or not self._can_see(entry, person):
            return None, f"接收单据 {entry_id} 不存在或不在你的查看范围内", None

        # 先校验数量格式，再判状态：非法数字不能被“状态不允许改”掩盖
        quantities, qty_error = self._parse_quantities(values, person["role"])
        if qty_error:
            return None, None, qty_error

        # 可见范围已保证大副只能看到本航次自己的单据，能进到这里的必为原填报人本人；
        # 值班长与环保专责没有「接收量修改」权限，上面的校验即会当场驳回。
        if entry["status"] in (STATUS_CONFIRMED, STATUS_TRANSFERRED):
            return None, f"单据已{entry['status']}，接收量已锁定，不能再修改", None
        if entry["status"] == STATUS_PENDING:
            return None, "单据正等待值班长确认；被打回后才能改量重报", None

        changes = []
        for field in QUANTITY_FIELDS:
            if field in values:
                old = float(entry.get(field, 0) or 0)
                new = quantities[field]
                if abs(old - new) > 1e-9:
                    changes.append(f"{field}：{old:g} → {new:g}")
                    entry[field] = new
        if changes:
            entry["操作记录"].append(
                {
                    "时间": self._now(),
                    "操作人": person["name"],
                    "角色": person["role"],
                    "动作": "修改接收量",
                    "明细": "；".join(changes),
                }
            )
        return entry, "接收量已更新并留痕", None

    # ---------- 状态动作 ----------
    def run_action(
        self, entry_id: int, action: str, person: dict[str, str], payload: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, str | None, PermissionDenied | None]:
        # 任何“把单据改到别人名下”的动作都走改派授权：无人持有 → 当场驳回
        if action in ("改派单据", "转交填报", "变更填报人"):
            return None, None, self._reassign_denial(person["role"])

        # 动作 → 所需权限：先判权限，缺权限时当场说明，不被可见范围提示盖过
        action_permissions = {
            "打回重报": PERM_REJECT,
            "重新提交": PERM_SUBMIT,
            "确认接收": PERM_CONFIRM,
            "登记上岸转运": PERM_TRANSFER,
        }
        if action not in action_permissions:
            return None, f"动作「{action}」不属于船舶污染物接收可执行范围", None
        try:
            self._require(person["role"], action_permissions[action])
        except PermissionDenied as exc:
            return None, None, exc

        raw_entry = store.find(MODULE, entry_id)
        # 大副重新提交别人名下的单据 = 试图顶替原填报人，按改派当场驳回（即使该单据不在其可见范围）
        if action == "重新提交" and raw_entry is not None and raw_entry.get("原填报人") != person["name"]:
            return None, None, self._reassign_denial(
                person["role"],
                f"试图以本人名义重新提交 {raw_entry.get('接收单号', entry_id)}（原填报人："
                f"{raw_entry.get('原填报人')}）；",
            )

        entry = raw_entry
        if entry is None or not self._can_see(entry, person):
            return None, f"接收单据 {entry_id} 不存在或不在你的查看范围内", None

        if action == "打回重报":
            reason = str(payload.get("reason") or "").strip()
            if not reason:
                return None, "打回单据必须写清理由", None
            if entry["status"] != STATUS_PENDING:
                return None, f"当前状态为「{entry['status']}」，只有待确认单据可以打回", None
            entry["status"] = STATUS_REJECTED
            entry["pending"] = False
            entry["abnormal"] = True
            entry["打回理由"] = reason
            self._log(entry, person, "打回重报", f"打回理由：{reason}")
            return entry, "单据已打回，理由已记录", None

        if action == "重新提交":
            if entry.get("原填报人") != person["name"]:
                return None, None, self._reassign_denial(person["role"])
            if entry["status"] != STATUS_REJECTED:
                return None, "只有被打回的单据才能重新提交", None
            # 人员调班后原填报人不变：归属沿用首次填报人
            entry["status"] = STATUS_PENDING
            entry["pending"] = True
            entry["abnormal"] = False
            entry["打回理由"] = ""
            self._log(entry, person, "重新提交", f"原填报人仍为 {entry['原填报人']}")
            return entry, "单据已重新提交，原填报人保持不变", None

        if action == "确认接收":
            if entry["status"] != STATUS_PENDING:
                return None, f"当前状态为「{entry['status']}」，不能确认", None
            entry["status"] = STATUS_CONFIRMED
            entry["pending"] = False
            entry["abnormal"] = False
            self._log(entry, person, "确认接收", "核对接收量无误，予以确认")
            return entry, "接收单据已确认", None

        if action == "登记上岸转运":
            if entry["status"] != STATUS_CONFIRMED:
                return None, "只有已确认的单据才能登记上岸转运", None
            destination = str(payload.get("destination") or "").strip()
            if not destination:
                return None, "登记上岸转运必须填写转运去向", None
            entry["status"] = STATUS_TRANSFERRED
            entry["pending"] = False
            entry["abnormal"] = False
            entry["转运去向"] = destination
            self._log(entry, person, "登记上岸转运", f"转运去向：{destination}；接收量锁定")
            return entry, "上岸转运已登记，单据转为只读", None

        return entry, "动作已执行", None

    def reassign(
        self, entry_id: int, target_name: str, person: dict[str, str]
    ) -> tuple[dict[str, Any] | None, PermissionDenied | None]:
        """显式改派接口：把单据改到别人名下。任何角色都缺少改派权限，一律当场驳回。

        改派是针对“操作归属”本身的越权尝试，无论单据是否在该角色可见范围内，
        都要先点破所缺权限，不能用“看不到该单据”搪塞过去。
        """
        prefix = f"试图把单据 {entry_id} 改派给「{target_name}」；" if target_name else ""
        if PERM_REASSIGN not in ROLE_PERMISSIONS.get(person["role"], set()):
            return None, self._reassign_denial(person["role"], prefix)
        entry = store.find(MODULE, entry_id)
        if entry is None or not self._can_see(entry, person):
            return None, PermissionDenied(person["role"], PERM_REASSIGN,
                                         f"接收单据 {entry_id} 不存在或不在你的查看范围内")
        return None, self._reassign_denial(person["role"], prefix)

    # ---------- 汇总 ----------
    def summary(self, person: dict[str, str]) -> dict[str, Any]:
        """按角色可见范围汇总接收量；汇总数由单据实时相加，并回算对账，保证两者对得上。"""
        self._require(person["role"], PERM_VIEW)
        rows = [row for row in store.rows(MODULE) if self._can_see(row, person)]

        by_type = {field: 0.0 for field in QUANTITY_FIELDS}
        groups: dict[str, dict[str, Any]] = {}
        for row in rows:
            key = f"{row.get('船名', '')}/{row.get('航次', '')}"
            group = groups.setdefault(
                key,
                {"船名": row.get("船名", ""), "航次": row.get("航次", ""), "单据数": 0,
                 "接收单号": [], **{field: 0.0 for field in QUANTITY_FIELDS}},
            )
            group["单据数"] += 1
            group["接收单号"].append(row.get("接收单号"))
            for field in QUANTITY_FIELDS:
                value = float(row.get(field, 0) or 0)
                by_type[field] += value
                group[field] += value

        total_quantity = sum(by_type.values())
        # 对账：逐单据把接收量再加一遍，与汇总额比对
        recalc = {field: 0.0 for field in QUANTITY_FIELDS}
        for row in rows:
            for field in QUANTITY_FIELDS:
                recalc[field] += float(row.get(field, 0) or 0)
        matched = all(abs(recalc[f] - by_type[f]) < 1e-9 for f in QUANTITY_FIELDS)

        return {
            "口径": "按接收单据实时汇总（同一船舶同一航次仅首张单据生效）",
            "单据数": len(rows),
            "分类型合计": {k: round(v, 3) for k, v in by_type.items()},
            "接收总量": round(total_quantity, 3),
            "按船舶航次": [
                {**g, **{f: round(g[f], 3) for f in QUANTITY_FIELDS}} for g in groups.values()
            ],
            "对账": {
                "一致": matched,
                "说明": "汇总数量与各接收单据逐张加总一致" if matched
                else "汇总与单据存在差额，请核查",
            },
        }

    # ---------- 辅助 ----------
    def _find_by_vessel_voyage(
        self, vessel: str, voyage: str
    ) -> dict[str, Any] | None:
        for row in store.rows(MODULE):
            if row.get("船名") == vessel and row.get("航次") == voyage:
                return row
        return None

    def _claims_new_owner(self, values: dict[str, Any]) -> bool:
        # 数量修改接口只允许传数量；任何携带“填报人/归属”字段的请求都按改派处理。
        for key in ("原填报人", "当前填报人", "填报人"):
            value = values.get(key)
            if value is not None and str(value).strip():
                return True
        return False

    def _reassign_denial(self, role: str, prefix: str = "") -> PermissionDenied:
        return PermissionDenied(
            role,
            PERM_REASSIGN,
            f"{prefix}越权操作：单据的操作归属固定为原填报人，当前角色「{role}」"
            f"缺少「{PERM_REASSIGN}」权限，改派已当场驳回",
        )

    def _parse_quantities(
        self, values: dict[str, Any], role: str = ""
    ) -> tuple[dict[str, float], PermissionDenied | None]:
        result: dict[str, float] = {}
        for field in QUANTITY_FIELDS:
            raw = values.get(field)
            if raw is None or str(raw).strip() == "":
                result[field] = 0.0
                continue
            try:
                number = float(raw)
            except (TypeError, ValueError):
                return {}, PermissionDenied(role, PERM_EDIT_QTY, f"{field}必须是数字，收到：{raw}")
            if number < 0:
                return {}, PermissionDenied(role, PERM_EDIT_QTY, f"{field}不能为负数")
            result[field] = number
        return result, None

    def _describe_quantities(self, quantities: dict[str, float]) -> str:
        parts = [f"{k} {v:g}" for k, v in quantities.items() if v]
        return "；".join(parts) if parts else "各类均为 0"

    def _log(
        self, entry: dict[str, Any], person: dict[str, str], action: str, detail: str
    ) -> None:
        entry.setdefault("操作记录", []).append(
            {
                "时间": self._now(),
                "操作人": person["name"],
                "角色": person["role"],
                "动作": action,
                "明细": detail,
            }
        )

    @staticmethod
    def _now() -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
