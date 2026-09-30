"""船舶污染物接收 端到端 HTTP 用例：需先在本机起后端（uvicorn app.main:app --port 8000）。

覆盖：身份校验、三角色数据可见范围、越权改派当场驳回并指出所缺权限、
打回必须写理由、改量留痕、人员调班归属不变、汇总与单据对账、同船同航次去重。
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:8000"
ZHANG = ("chief_zhang", "chief_mate")
LI = ("chief_li", "chief_mate")
WANG = ("supervisor_wang", "supervisor")
ZHAO = ("env_zhao", "env_officer")


def call(method, path, oid=None, role=None, body=None):
    headers = {"Content-Type": "application/json"}
    if oid:
        headers["X-Operator-Id"] = oid
    if role:
        headers["X-Operator-Role"] = role
    data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())


def main() -> None:
    # 身份与名册
    s, b = call("GET", "/api/pollutant/identity")
    assert len(b["operators"]) == 4
    s, b = call("GET", "/api/pollutant/identity", *ZHAO)
    assert b["authenticated"] and b["permissions"] == ["接收单据查看"]
    assert call("GET", "/api/pollutant")[0] == 401
    assert call("GET", "/api/pollutant", "nobody")[0] == 403
    assert call("GET", "/api/pollutant", "supervisor_wang", "env_officer")[0] == 403
    assert call("GET", "/api/pollutant", "env_zhao", "bad")[0] == 400

    # 可见范围
    assert [x["接收单号"] for x in call("GET", "/api/pollutant", *ZHANG)[1]["items"]] == ["POL-0003"]
    assert [x["接收单号"] for x in call("GET", "/api/pollutant", *LI)[1]["items"]] == ["POL-0002"]
    assert [x["接收单号"] for x in call("GET", "/api/pollutant", *ZHAO)[1]["items"]] == ["POL-0001"]
    assert sorted(x["接收单号"] for x in call("GET", "/api/pollutant", *WANG)[1]["items"]) == [
        "POL-0002", "POL-0003"
    ]

    # 环保专责只读
    s, b = call("POST", "/api/pollutant", *ZHAO, {"values": {"船名": "x", "航次": "y"}})
    assert b["missingPermission"] == "接收单据填报"
    assert call("POST", "/api/pollutant/1/actions", *ZHAO, {"values": {"action": "确认接收"}})[1][
        "missingPermission"
    ] == "接收单确认"
    assert call("PUT", "/api/pollutant/1/quantities", *ZHAO, {"values": {"生活垃圾": 1}})[1][
        "missingPermission"
    ] == "接收量修改"

    # 大副填报范围 + 同船同航次去重
    s, b = call("POST", "/api/pollutant", *ZHANG,
                {"values": {"船名": "海运号", "航次": "V-2409", "生活垃圾": 1}})
    assert b["missingPermission"] == "接收单据填报" and "越权填报" in b["message"]
    s, b = call("POST", "/api/pollutant", *ZHANG,
                {"values": {"船名": "远洋号", "航次": "V-2409", "生活垃圾": 1}})
    assert "只认第一次" in b["message"]

    # 改派三角色全驳回（含可见范围外的单据）
    for who in (ZHANG, WANG, ZHAO):
        s, b = call("POST", "/api/pollutant/3/reassign", *who, {"values": {"targetId": "chief_li"}})
        assert b["missingPermission"] == "单据改派", b
    assert call("POST", "/api/pollutant/3/actions", *WANG, {"values": {"action": "转交填报"}})[1][
        "missingPermission"
    ] == "单据改派"
    assert call("PUT", "/api/pollutant/3/quantities", *ZHANG, {"values": {"原填报人": "chief_li"}})[1][
        "missingPermission"
    ] == "单据改派"

    # 打回：理由必填、大副无权、值班长写理由后打回
    assert "写清理由" in call("POST", "/api/pollutant/3/actions", *WANG,
                             {"values": {"action": "打回重报"}})[1]["message"]
    assert call("POST", "/api/pollutant/3/actions", *ZHANG,
                {"values": {"action": "打回重报", "reason": "x"}})[1][
        "missingPermission"
    ] == "接收单据打回"
    s, b = call("POST", "/api/pollutant/3/actions", *WANG,
                {"values": {"action": "打回重报", "reason": "残油数据复核"}})
    assert b["entry"]["status"] == "已打回" and b["entry"]["打回理由"] == "残油数据复核"

    # 改量：原填报人可改并留痕；别人（另一名大副）被数据范围挡下；非数字/负数
    s, b = call("PUT", "/api/pollutant/3/quantities", *ZHANG, {"values": {"残油废油": 0.08}})
    assert b["ok"] and b["entry"]["残油废油"] == 0.08
    s, b = call("PUT", "/api/pollutant/3/quantities", *LI, {"values": {"残油废油": 0.09}})
    assert b["ok"] is False and "查看范围" in b["message"]
    s, b = call("GET", "/api/pollutant/3/history", *ZHANG)
    assert any(h["动作"] == "修改接收量" and "0.05 → 0.08" in h["明细"] for h in b["items"])
    assert "数字" in call("PUT", "/api/pollutant/3/quantities", *ZHANG,
                          {"values": {"生活垃圾": "x"}})[1]["message"]
    assert "负数" in call("PUT", "/api/pollutant/3/quantities", *ZHANG,
                          {"values": {"生活垃圾": -1}})[1]["message"]

    # 重新提交：归属保持原填报人；别的大副顶替 = 改派驳回
    s, b = call("POST", "/api/pollutant/3/actions", *ZHANG, {"values": {"action": "重新提交"}})
    assert b["entry"]["原填报人"] == "张伟（大副）" and b["entry"]["status"] == "待值班长确认"
    # 先把 2 号打回，再让张伟顶替李强的单据
    call("POST", "/api/pollutant/2/actions", *WANG, {"values": {"action": "打回重报", "reason": "核对"}})
    s, b = call("POST", "/api/pollutant/2/actions", *ZHANG, {"values": {"action": "重新提交"}})
    assert b["missingPermission"] == "单据改派", b

    # 确认 -> 锁定改量 -> 转运需去向 -> 完成后仅环保专责可见
    s, b = call("POST", "/api/pollutant/3/actions", *WANG, {"values": {"action": "确认接收"}})
    assert b["entry"]["status"] == "已确认"
    assert "锁定" in call("PUT", "/api/pollutant/3/quantities", *ZHANG,
                          {"values": {"生活垃圾": 2}})[1]["message"]
    assert "转运去向" in call("POST", "/api/pollutant/3/actions", *WANG,
                              {"values": {"action": "登记上岸转运"}})[1]["message"]
    s, b = call("POST", "/api/pollutant/3/actions", *WANG,
                {"values": {"action": "登记上岸转运", "destination": "绿源处置站"}})
    assert b["entry"]["status"] == "已完成上岸转运"
    assert call("GET", "/api/pollutant/3", *WANG)[0] == 404
    assert call("GET", "/api/pollutant/3", *ZHAO)[0] == 200

    # 汇总对账（环保专责此刻可见 POL-0001 与 POL-0003）
    s, b = call("GET", "/api/pollutant/summary", *ZHAO)
    assert b["对账"]["一致"] and b["单据数"] == 2
    manual = (0.42 + 3.5 + 5.0) + (0.18 + 1.2 + 2.4 + 0.08)
    assert abs(b["接收总量"] - manual) < 1e-9
    groups = {g["船名"] + "/" + g["航次"]: g for g in b["按船舶航次"]}
    assert abs(groups["远洋号/V-2409"]["残油废油"] - 0.08) < 1e-9
    assert call("GET", "/api/pollutant/summary", *WANG)[1]["对账"]["一致"]

    # 导出（查询参数身份，模拟新开标签页）
    q = urllib.parse.urlencode({"operator_id": "env_zhao"})
    s, b = call("GET", f"/api/pollutant/export/all?{q}")
    assert s == 200 and b["summary"]["对账"]["一致"] and b["total"] == 2

    print("ALL HTTP TESTS PASSED")


if __name__ == "__main__":
    main()
