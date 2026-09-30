"""船舶污染物接收单据：权限归属与业务规则端到端自检。

跑法：backend 目录下用测试虚拟环境执行
  /tmp/venv311/bin/python scripts/check_pollutant.py
（文件名刻意不带 test_ 前缀，避免被当作正式测试套件收集。）
"""
from __future__ import annotations

import sys
from pathlib import Path

# 允许直接从 scripts/ 目录运行：把 backend/ 加进模块搜索路径。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from app.main import app
from app.security import OPERATORS

client = TestClient(app)
BASE = "/api/pollutant"
CHIEF = {"X-Operator-Id": "U001"}        # 陈大副 远洋之星 V-2609N
CHIEF2 = {"X-Operator-Id": "U002"}       # 林大副 海运先锋 V-2608N
CHIEF3 = {"X-Operator-Id": "U003"}       # 赵大副 江海湾 V-2607N
OFF_DUTY = {"X-Operator-Id": "U004"}     # 周大副 已调班
SUP = {"X-Operator-Id": "U101"}          # 马值班长
ENV = {"X-Operator-Id": "U201"}          # 贺环保 只读

passed: list[str] = []
failed: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    (passed if cond else failed).append(f"{name} :: {detail}")
    print(("  OK  " if cond else " FAIL ") + name + (f" —— {detail}" if detail and not cond else ""))


def body(resp) -> dict:
    try:
        return resp.json()
    except Exception:  # noqa: BLE001
        return {"raw": resp.text}


# ---------------------------------------------------------------- 1. 身份缺失/离岗
r = client.post(BASE, json={"values": {"船名": "远洋之星", "航次": "V-2609N", "污染物明细": {"含油污水": 1}}})
check("无身份写操作被403驳回", r.status_code == 403 and body(r)["detail"]["code"] == "permission_denied", str(body(r)))

r = client.get(BASE + "/me", headers=OFF_DUTY)
check("调班离岗人员被403驳回", r.status_code == 403 and "调班离岗" in body(r)["detail"]["message"], str(body(r)))

# ---------------------------------------------------------------- 2. 环保专责只读
r = client.post(BASE, headers=ENV, json={"values": {"船名": "x", "航次": "y", "污染物明细": {"含油污水": 1}}})
d = body(r)["detail"]
check("环保专责填报被403", r.status_code == 403 and d["missingPermission"] == "pollutant:create", d.get("message"))
check("驳回信息点明缺失权限", "缺少权限 pollutant:create" in d["message"], d["message"])

r = client.post(BASE + "/3/reject", headers=ENV, json={"values": {"理由": "测试"}})
check("环保专责打回被403", r.status_code == 403 and body(r)["detail"]["missingPermission"] == "pollutant:reject")

r = client.post(BASE + "/2/transfer", headers=ENV)
check("环保专责登记转运被403", r.status_code == 403 and body(r)["detail"]["missingPermission"] == "pollutant:transfer")

r = client.get(BASE, headers=ENV)
check("环保专责可查看列表", r.status_code == 200 and r.json()["total"] >= 4)

r = client.get(BASE + "/summary?scope=transferred", headers=ENV)
check("环保专责可查看已转运汇总", r.status_code == 200 and r.json()["单据数"] >= 1)

# ---------------------------------------------------------------- 3. 大副越界填报
r = client.post(BASE, headers=CHIEF, json={"values": {"船名": "海运先锋", "航次": "V-2608N", "污染物明细": {"含油污水": 1}}})
d = body(r)["detail"]
check("给别的船填报被403", r.status_code == 403 and d["missingPermission"] == "pollutant:create:other-ship", d["message"])

# ---------------------------------------------------------------- 4. 改挂他人名下
r = client.post(BASE + "/4/edit", headers=CHIEF, json={"values": {"污染物明细": {"含油污水": 3.2}, "填报人ID": "U002"}})
d = body(r)["detail"]
check("改挂他人名下被403", r.status_code == 403 and d["missingPermission"] == "pollutant:reassign", d["message"])

# ---------------------------------------------------------------- 5. 动别人的单据
r = client.post(BASE + "/3/edit", headers=CHIEF, json={"values": {"污染物明细": {"含油污水": 9}}})
d = body(r)["detail"]
check("大副改他人单据被403", r.status_code == 403 and d["missingPermission"] == "pollutant:edit:others", d["message"])

r = client.post(BASE + "/3/confirm", headers=CHIEF)
check("大副确认接收被403", r.status_code == 403 and body(r)["detail"]["missingPermission"] == "pollutant:confirm")

# ---------------------------------------------------------------- 6. 重复提交
r = client.post(BASE, headers=CHIEF3, json={"values": {"船名": "江海湾", "航次": "V-2607N", "污染物明细": {"含油污水": 2}}})
check("同船同航次重复提交被409", r.status_code == 409 and "只认第一次提交" in body(r)["detail"]["message"], str(body(r)))

# 被打回的单据再次"新建"也不认，必须走原单据重新提交
r = client.post(BASE, headers=CHIEF, json={"values": {"船名": "远洋之星", "航次": "V-2609N", "污染物明细": {"含油污水": 3.2}}})
check("被打回后新建第二张被409", r.status_code == 409 and "PRC-20260930-0004" in body(r)["detail"]["message"])

# ---------------------------------------------------------------- 7. 打回必须写理由
r = client.post(BASE + "/3/reject", headers=SUP, json={"values": {"理由": "  "}})
check("打回不写理由被400", r.status_code == 400 and "写明理由" in body(r)["detail"]["message"])

# ---------------------------------------------------------------- 8. 正常流程：打回 → 修订重报 → 确认 → 转运
r = client.post(BASE + "/3/reject", headers=SUP, json={"values": {"理由": "生活垃圾量请重新过磅"}})
check("值班长打回", r.status_code == 200 and r.json()["entry"]["status"] == "已打回")

r = client.post(BASE + "/3/resubmit", headers=CHIEF3,
                json={"values": {"污染物明细": {"含油污水": 1.8, "生活垃圾": 75.5}, "修改说明": "已重新过磅"}})
entry = r.json()["entry"]
check("原填报人重新提交", r.status_code == 200 and entry["status"] == "待码头确认", str(body(r)))

r = client.post(BASE + "/3/confirm", headers=SUP)
check("值班长确认接收", r.status_code == 200 and r.json()["entry"]["status"] == "已接收")

r = client.post(BASE + "/3/edit", headers=CHIEF3, json={"values": {"污染物明细": {"含油污水": 99}}})
check("确认后大副改量被409锁定", r.status_code == 409 and "锁定" in body(r)["detail"]["message"])

r = client.post(BASE + "/3/transfer", headers=SUP)
check("值班长登记完成上岸转运", r.status_code == 200 and r.json()["entry"]["status"] == "已完成上岸转运")

r = client.post(BASE + "/3/reject", headers=SUP, json={"values": {"理由": "晚了"}})
check("转运后再打回被409", r.status_code == 409)

r = client.post(BASE + "/3/edit", headers=CHIEF3, json={"values": {"污染物明细": {"含油污水": 1}}})
check("转运后改量被409锁定", r.status_code == 409 and "任何人不得再改" in body(r)["detail"]["message"])

# ---------------------------------------------------------------- 9. 被打回单据修订重报（数量留痕）
r = client.post(BASE + "/4/resubmit", headers=CHIEF,
                json={"values": {"污染物明细": {"含油污水": 3.2, "生活垃圾": 30}, "修改说明": "按流量计读数更正"}})
entry = r.json()["entry"]
check("陈大副按打回理由重新提交", r.status_code == 200 and entry["status"] == "待码头确认" and entry["驳回理由"] == "")

r = client.get(BASE + "/4/logs")
logs = r.json()["logs"]
actions = [log["动作"] for log in logs]
check("操作记录含提交/打回/重报", actions == ["提交接收单据", "打回单据", "修改后重新提交"], str(actions))
resubmit_log = logs[-1]
diffs = {(c["类别"], c["原值"], c["新值"]) for c in resubmit_log["数量变化"]}
check("数量变化逐类留痕(谁改/原值/新值)", ("含油污水", 5.0, 3.2) in diffs and ("生活垃圾", 0.0, 30.0) in diffs, str(diffs))
check("留痕记录操作人", resubmit_log["操作人"] == "陈大副" and resubmit_log["操作人角色"] == "船上大副")

# ---------------------------------------------------------------- 10. 待确认阶段改量也留痕
r = client.post(BASE + "/4/edit", headers=CHIEF, json={"values": {"污染物明细": {"含油污水": 3.3, "生活垃圾": 30}, "修改说明": "复核微调"}})
check("本人单据待确认阶段可改量", r.status_code == 200)
r = client.get(BASE + "/4/logs")
last = r.json()["logs"][-1]
check("改量动作留痕含改动量", last["动作"] == "修改接收量" and last["数量变化"][0]["改动量"] == 0.1, str(last))

# ---------------------------------------------------------------- 11. 调班后原填报人不变
r = client.get(BASE + "/1")
entry = r.json()
check("转运单据标出原填报人(调班前的人)", entry["原填报人"] == "周大副", entry.get("原填报人", ""))
check("原填报人在岗状态如实标出", entry["原填报人在岗"] is False)

# ---------------------------------------------------------------- 12. 全新航次首报成功 + 第二次409
OPERATORS["U003"]["voyage"] = "V-2610N"  # 赵大副本航次换到新航次（模拟新航次绑定）
r = client.post(BASE, headers=CHIEF3, json={"values": {"船名": "江海湾", "航次": "V-2610N", "污染物明细": {"废矿物油": 12}}})
check("新航次首次填报成功", r.status_code == 200 and r.json()["ok"] is True, str(body(r)))
new_id = r.json()["entry"]["id"]
check("服务端固定归属为当前大副", r.json()["entry"]["填报人ID"] == "U003" and r.json()["entry"]["原填报人"] == "赵大副")
r = client.post(BASE, headers=CHIEF3, json={"values": {"船名": "江海湾", "航次": "V-2610N", "污染物明细": {"废矿物油": 13}}})
check("新航次第二次提交仍被409", r.status_code == 409)

# 非法数量（输入校验先于航次越界检查）
r = client.post(BASE, headers=CHIEF2, json={"values": {"船名": "海运先锋", "航次": "V-9999", "污染物明细": {"含油污水": -1}}})
check("负数数量被拦下", r.status_code == 200 and r.json()["ok"] is False and "不能为负" in r.json()["message"], str(body(r)))
OPERATORS["U002"]["voyage"] = "V-9999"
r = client.post(BASE, headers=CHIEF2, json={"values": {"船名": "海运先锋", "航次": "V-9998", "污染物明细": {"含油污水": 1}}})
check("数量合法但越界航次仍403", r.status_code == 403 and body(r)["detail"]["missingPermission"] == "pollutant:create:other-voyage", str(body(r)))
r = client.post(BASE, headers=CHIEF2, json={"values": {"船名": "海运先锋", "航次": "V-9999", "污染物明细": {}}})
check("空明细被拦下", r.status_code == 200 and r.json()["ok"] is False and "至少" in r.json()["message"])

# ---------------------------------------------------------------- 13. 汇总与单据对账
r = client.get(BASE + "/summary")
s = r.json()
check("汇总单据数=有效单据数(被打回不计)", s["单据数"] == 5, str(s["单据数"]))  # 1,2,3,4,5(new)
check("对账一致", s["对账"]["matched"] is True and s["对账"]["差异"] == 0.0, str(s["对账"]))
# 逐张单据回算验证汇总数量真的来自单据
by_id = {item["单据编号"]: item["接收总量"] for item in s["按单据"]}
calc = round(sum(by_id.values()), 3)
check("汇总总计=逐单据求和", s["数量总计"] == calc, f"{s['数量总计']} vs {calc}")
# 分类合计交叉验证
cat_sum = round(sum(c["数量"] for c in s["分类合计"]), 3)
check("分类合计求和=总计", cat_sum == s["数量总计"], f"{cat_sum} vs {s['数量总计']}")

r = client.get(BASE + "/summary?scope=transferred")
s2 = r.json()
transferred_ids = {item["单据编号"] for item in s2["按单据"]}
check("转运口径只含已转运单据", s2["单据数"] == 2 and transferred_ids == {"PRC-20260927-0001", "PRC-20260930-0003"}, str(transferred_ids))
check("转运口径对账一致", s2["对账"]["matched"] is True)

# ---------------------------------------------------------------- 14. 值班长不能改数量（没有 edit 权限）
r = client.post(BASE + "/4/edit", headers=SUP, json={"values": {"污染物明细": {"含油污水": 1}}})
check("值班长改量被403", r.status_code == 403 and body(r)["detail"]["missingPermission"] == "pollutant:edit")

print()
print(f"通过 {len(passed)} 项，失败 {len(failed)} 项")
if failed:
    for item in failed:
        print("  - " + item)
    raise SystemExit(1)
print("全部通过")
