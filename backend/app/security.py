"""船舶污染物接收单据的身份与权限模型。

业务要求把单据的操作归属固定下来，因此每个写操作都必须带上操作人身份
（请求头 X-Operator-Id），由服务端按角色判定权限，前端传进来的"填报人"
一律不采信，归属只由服务端按身份写入。

角色：
- chief（船上大副）：只能填报本航次自己的接收单据，可修改自己被打回的单据；
- supervisor（码头值班长）：可打回单据并写明理由、确认接收、登记完成上岸转运；
- environmental（环保专责）：对已完成上岸转运的单据只能查看，没有任何写权限。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import Header, HTTPException

# 权限点：越权提示里直接引用这里的名称，说明"当前角色缺的是哪项权限"。
PERM_CREATE = "pollutant:create"          # 填报本航次接收单据
PERM_EDIT = "pollutant:edit"              # 修改接收量等填报内容（限本人单据）
PERM_REJECT = "pollutant:reject"          # 打回单据并写明理由
PERM_CONFIRM = "pollutant:confirm"        # 码头确认接收
PERM_TRANSFER = "pollutant:transfer"      # 登记完成上岸转运
PERM_VIEW = "pollutant:view"              # 查看接收单据

ROLE_PERMISSIONS: dict[str, set[str]] = {
    "chief": {PERM_CREATE, PERM_EDIT, PERM_VIEW},
    "supervisor": {PERM_REJECT, PERM_CONFIRM, PERM_TRANSFER, PERM_VIEW},
    "environmental": {PERM_VIEW},
}

ROLE_LABELS = {
    "chief": "船上大副",
    "supervisor": "码头值班长",
    "environmental": "环保专责",
}

# 固定人员名册：人员调班只改"在岗状态"，单据上的原填报人永远指向名册里的那个人。
# chief 角色额外绑定船名与航次，只能填报自己所在船舶本航次的单据。
OPERATORS: dict[str, dict[str, Any]] = {
    "U001": {
        "id": "U001", "name": "陈大副", "role": "chief",
        "ship": "远洋之星", "voyage": "V-2609N", "active": True,
    },
    "U002": {
        "id": "U002", "name": "林大副", "role": "chief",
        "ship": "海运先锋", "voyage": "V-2608N", "active": True,
    },
    "U003": {
        "id": "U003", "name": "赵大副", "role": "chief",
        "ship": "江海湾", "voyage": "V-2607N", "active": True,
    },
    "U004": {
        "id": "U004", "name": "周大副", "role": "chief",
        "ship": "远洋之星", "voyage": "V-2608N", "active": False,  # 已调班离船
    },
    "U101": {
        "id": "U101", "name": "马值班长", "role": "supervisor",
        "ship": None, "voyage": None, "active": True,
    },
    "U102": {
        "id": "U102", "name": "高值班长", "role": "supervisor",
        "ship": None, "voyage": None, "active": True,
    },
    "U201": {
        "id": "U201", "name": "贺环保", "role": "environmental",
        "ship": None, "voyage": None, "active": True,
    },
}


@dataclass(frozen=True)
class Operator:
    id: str
    name: str
    role: str

    @property
    def role_label(self) -> str:
        return ROLE_LABELS.get(self.role, self.role)

    def permissions(self) -> set[str]:
        return ROLE_PERMISSIONS.get(self.role, set())

    def can(self, permission: str) -> bool:
        return permission in self.permissions()


class PermissionDenied(Exception):
    """越权：HTTP 403，消息里点明操作人、角色与缺失的权限点。"""

    def __init__(self, operator: Operator, permission: str, reason: str = "") -> None:
        missing = f"当前角色「{operator.role_label}」缺少权限 {permission}"
        message = f"越权操作已当场驳回：{reason + '；' if reason else ''}{missing}"
        super().__init__(message)
        self.operator = operator
        self.permission = permission
        self.message = message

    def payload(self) -> dict[str, Any]:
        return {
            "code": "permission_denied",
            "message": self.message,
            "operator": self.operator.id,
            "operatorName": self.operator.name,
            "role": self.operator.role,
            "roleLabel": self.operator.role_label,
            "missingPermission": self.permission,
            "grantedPermissions": sorted(self.operator.permissions()),
        }

    def http(self) -> HTTPException:
        return HTTPException(status_code=403, detail=self.payload())


def current_operator(x_operator_id: str | None = Header(default=None, alias="X-Operator-Id")) -> Operator:
    """从请求头解析当前操作人；写接口缺身份或身份无效时直接 403。"""
    if not x_operator_id or not x_operator_id.strip():
        raise PermissionDenied(
            Operator(id="?", name="未识别操作人", role="anonymous"),
            PERM_VIEW,
            "请求未携带 X-Operator-Id，无法确认操作归属",
        ).http()
    key = x_operator_id.strip()
    data = OPERATORS.get(key)
    if data is None:
        raise PermissionDenied(
            Operator(id=key, name="未知人员", role="unknown"),
            PERM_VIEW,
            f"操作人「{key}」不在人员名册内",
        ).http()
    if not data.get("active", True):
        raise PermissionDenied(
            Operator(id=key, name=str(data["name"]), role=str(data["role"])),
            PERM_VIEW,
            "该人员已调班离岗，不能再操作接收单据",
        ).http()
    return Operator(id=str(data["id"]), name=str(data["name"]), role=str(data["role"]))


def require(operator: Operator, permission: str, reason: str = "") -> None:
    """权限断言：不满足就抛 PermissionDenied，由路由层转成 403。"""
    if not operator.can(permission):
        raise PermissionDenied(operator, permission, reason)


def operator_public(operator_id: str | None) -> dict[str, Any] | None:
    """给前端用的人员名册视图（不泄露权限实现细节以外的信息）。"""
    if not operator_id:
        return None
    data = OPERATORS.get(operator_id)
    if data is None:
        return None
    return {
        "id": data["id"],
        "name": data["name"],
        "role": data["role"],
        "roleLabel": ROLE_LABELS.get(data["role"], data["role"]),
        "ship": data["ship"],
        "voyage": data["voyage"],
        "active": data["active"],
        "permissions": sorted(ROLE_PERMISSIONS.get(data["role"], set())),
    }
