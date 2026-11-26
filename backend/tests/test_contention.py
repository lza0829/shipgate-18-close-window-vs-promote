"""关闸与已进事务袋跃迁的争用对照（选定臂：关闸优先，整站一种）。

覆盖：关闸抢先 / 跃迁抢先 / 做到一半 / 闸外跃迁进对账 / 并发双写口，
以及关闸写口探针、审计时序过滤、发版单回执、在途事件、环境列与态势格同刷。
"""
import pytest
from fastapi.testclient import TestClient

import app.db as dbmod
from app.main import app
from app.seed import seed_if_empty


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(dbmod, "DB_PATH", tmp_path / "t.db")
    seed_if_empty()
    with TestClient(app) as c:
        yield c


# ---------- 夹具助手 ----------

def 进袋(client, rid=1, env="预"):
    r = client.post("/api/夹具/进袋", json={"发版单编号": rid, "目标环境": env})
    assert r.status_code == 200, r.text
    return r.json()["事务袋编号"]


def 关闸(client, env="预"):
    r = client.post("/api/夹具/关闸", json={"环境": env})
    assert r.status_code == 200, r.text
    return r.json()


def 落成(client, txn):
    r = client.post("/api/夹具/落成", json={"事务袋编号": txn})
    assert r.status_code == 200, r.text
    return r.json()


def 快照(client):
    r = client.get("/api/夹具/快照")
    assert r.status_code == 200, r.text
    return r.json()


def 袋行(snap, txn):
    return next(b for b in snap["事务袋"] if b["编号"] == txn)


def 环境版本(snap, app_name, env):
    return next(r["版本"] for r in snap["环境列"] if r["应用"] == app_name and r["环境"] == env)


def 发版行(snap, rid):
    return next(r for r in snap["发版单"] if r["编号"] == rid)


def 窗行(snap, env):
    return next(w for w in snap["窗口"] if w["环境"] == env)


def 袋窗审计序(snap):
    kinds = [(a["类别"], a["动作"]) for a in reversed(snap["审计尾"])]
    return [k for k in kinds if k[0] in ("晋升袋", "放行窗", "晋升")]


# ---------- 对照场景一：关闸抢先 ----------

def test_关闸抢先_跃迁整笔失败且各面对齐(client):
    txn = 进袋(client)
    gate = 关闸(client)
    assert gate["切断数"] == 1 and gate["切断事务袋"] == [txn]
    out = 落成(client, txn)
    assert out["结局"] == "已切断"

    s = 快照(client)
    rel = 发版行(s, 1)
    assert rel["当前环境"] == "测" and rel["状态"] == "已入闸"  # 发版单未推高、未记放行
    assert 环境版本(s, "结算网关", "预") == "1.1.0"  # 环境列未切
    bag = 袋行(s, txn)
    win = 窗行(s, "预")
    assert bag["状态"] == "已切断"
    assert win["状态"] == "窗关"
    # 关闸提交戳、袋落决戳、切断窗编号、审计戳对齐
    assert bag["落决时间"] == win["关闸提交"] == gate["时间"]
    assert bag["切断窗编号"] == win["编号"]
    # 对账分桶：切断入桶，闸外跃迁恒空
    assert s["对账"]["事务袋分桶"]["已切断"] == 1
    assert s["对账"]["闸外跃迁"] == []
    # 态势在途格：发版单仍在途但环境未动，不计闸外成功
    inflight = [r for r in s["在途"] if r["编号"] == 1]
    assert inflight and inflight[0]["当前环境"] == "测"
    # 审计时序：进袋 → 闸关切断 → 窗关
    assert 袋窗审计序(s) == [("晋升袋", "进袋"), ("晋升袋", "闸关切断"), ("放行窗", "窗关")]
    cut_audit = next(a for a in s["审计尾"] if a["动作"] == "闸关切断")
    assert cut_audit["时间"] == gate["时间"]


# ---------- 对照场景二：跃迁抢先 ----------

def test_跃迁抢先_闸内落成再关闸(client):
    txn = 进袋(client)
    out = 落成(client, txn)
    assert out["结局"] == "已落成"
    gate = 关闸(client)
    assert gate["切断数"] == 0

    s = 快照(client)
    rel = 发版行(s, 1)
    assert rel["当前环境"] == "预" and rel["状态"] == "晋升中"
    assert 环境版本(s, "结算网关", "预") == "1.3.0"
    bag = 袋行(s, txn)
    assert bag["状态"] == "已落成" and bag["切断窗编号"] is None
    assert s["对账"]["事务袋分桶"]["已落成"] == 1
    assert s["对账"]["闸外跃迁"] == []
    assert s["对账"]["晋升事件数"] == 1
    assert 袋窗审计序(s) == [
        ("晋升袋", "进袋"),
        ("晋升袋", "落成"),
        ("晋升", "晋升到预"),
        ("放行窗", "窗关"),
    ]


# ---------- 对照场景三：做到一半 ----------

def test_做到一半_闸关环境列未切且留可核标(client):
    txn = 进袋(client)
    关闸(client)  # 袋进了一半，闸先落
    s = 快照(client)
    bag = 袋行(s, txn)
    win = 窗行(s, "预")
    # 禁止态是「闸关 + 环境列已切 + 无闸外可核标」；此处环境列未切、切断标齐备
    assert win["状态"] == "窗关"
    assert 环境版本(s, "结算网关", "预") == "1.1.0"
    assert bag["状态"] == "已切断"
    assert bag["落决时间"] and bag["切断窗编号"] == win["编号"]
    # 半截后再落成仍整笔失败，各面不再动
    out = 落成(client, txn)
    assert out["结局"] == "已切断"
    s2 = 快照(client)
    assert 环境版本(s2, "结算网关", "预") == "1.1.0"
    assert 发版行(s2, 1)["当前环境"] == "测"
    assert s2["对账"]["闸外跃迁"] == []


# ---------- 对照场景四：闸外跃迁进对账 ----------

def test_闸外跃迁桶在对账接口恒空(client):
    txn = 进袋(client)
    关闸(client)
    落成(client, txn)
    r = client.get("/api/对账")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["闸外跃迁"] == []
    assert data["事务袋分桶"] == {"进行中": 0, "已落成": 0, "已切断": 1}


# ---------- 并发双写口：同发争用，结局唯一不撕裂 ----------

@pytest.mark.parametrize("round_no", range(8))
def test_并发双写口_结局唯一不撕裂(client, round_no):
    r = client.post("/api/夹具/争用", json={"发版单编号": 1, "目标环境": "预", "顺序": "同发"})
    assert r.status_code == 200, r.text
    body = r.json()
    s = body["快照"]
    bag = 袋行(s, body["事务袋编号"])
    win = 窗行(s, "预")
    rel = 发版行(s, 1)
    ver = 环境版本(s, "结算网关", "预")
    assert win["状态"] == "窗关"
    if body["袋结局"] == "已落成":
        # 跃迁抢先：整笔落成，关闸切断为零
        assert bag["状态"] == "已落成"
        assert rel["当前环境"] == "预" and ver == "1.3.0"
        assert body["关闸结果"]["切断数"] == 0
    else:
        # 关闸抢先：跃迁整笔失败，各面不动
        assert body["袋结局"] == "已切断"
        assert bag["状态"] == "已切断"
        assert rel["当前环境"] == "测" and ver == "1.1.0"
        assert body["关闸结果"]["切断数"] == 1
        assert bag["落决时间"] == win["关闸提交"]
    assert s["对账"]["闸外跃迁"] == []


# ---------- 争用夹具两套确定性对照 ----------

def test_争用夹具_关闸抢先(client):
    r = client.post("/api/夹具/争用", json={"发版单编号": 1, "目标环境": "预", "顺序": "关闸抢先"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["袋结局"] == "已切断"
    assert body["关闸结果"]["切断数"] == 1
    s = body["快照"]
    assert 环境版本(s, "结算网关", "预") == "1.1.0"
    assert 发版行(s, 1)["当前环境"] == "测"
    assert s["对账"]["闸外跃迁"] == []


def test_争用夹具_跃迁抢先(client):
    r = client.post("/api/夹具/争用", json={"发版单编号": 1, "目标环境": "预", "顺序": "跃迁抢先"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["袋结局"] == "已落成"
    assert body["关闸结果"]["切断数"] == 0
    s = body["快照"]
    assert 环境版本(s, "结算网关", "预") == "1.3.0"
    assert 发版行(s, 1)["当前环境"] == "预"
    assert s["对账"]["闸外跃迁"] == []


# ---------- 探针：关闸写口 ----------

def test_关闸写口探针_无在途切断为零且重开清戳(client):
    gate = 关闸(client, "预")
    assert gate["切断数"] == 0 and gate["切断事务袋"] == []
    s = 快照(client)
    win = 窗行(s, "预")
    assert win["状态"] == "窗关" and win["关闸提交"] == gate["时间"]
    r = client.post("/api/放行窗/切换", json={"环境": "预", "状态": "窗开"})
    assert r.status_code == 200, r.text
    s = 快照(client)
    win = 窗行(s, "预")
    assert win["状态"] == "窗开" and win["关闸提交"] is None


# ---------- 探针：发版单回执与晋升写口 ----------

def test_发版晋升写口_回执与落袋一致(client):
    r = client.post("/api/发版单/1/晋升", json={"目标环境": "预"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["当前环境"] == "预" and body["结局"] == "已落成" and body["事务袋编号"]
    s = 快照(client)
    assert 袋行(s, body["事务袋编号"])["状态"] == "已落成"
    assert 环境版本(s, "结算网关", "预") == "1.3.0"


def test_闸外硬拒不变_闸关新晋升不进袋(client):
    关闸(client, "预")
    r = client.post("/api/发版单/1/晋升", json={"目标环境": "预"})
    assert r.status_code == 400
    assert "放行窗已关" in r.json()["detail"]
    s = 快照(client)
    assert s["事务袋"] == []  # 硬拒于入场，不进袋
    assert s["对账"]["闸外跃迁"] == []


# ---------- 探针：审计时序过滤 ----------

def test_审计时序过滤(client):
    txn = 进袋(client)
    关闸(client)
    r = client.get("/api/审计", params={"类别": "晋升袋"})
    rows = r.json()
    assert rows and all(x["类别"] == "晋升袋" for x in rows)
    ids = [x["编号"] for x in rows]
    assert ids == sorted(ids, reverse=True)
    r = client.get("/api/审计", params={"类别": "放行窗"})
    assert r.json() and all(x["类别"] == "放行窗" for x in r.json())
    r = client.get("/api/审计", params={"类别": "晋升袋", "关联编号": txn})
    assert r.json() and all(x["关联编号"] == txn for x in r.json())


# ---------- 探针：在途事件 ----------

def test_在途事件_事务袋进出(client):
    txn = 进袋(client)
    r = client.get("/api/晋升事务袋", params={"状态": "进行中"})
    assert [b["编号"] for b in r.json()] == [txn]
    ov = client.get("/api/总览").json()
    assert [b["编号"] for b in ov["事务袋在途"]] == [txn]
    关闸(client)
    assert client.get("/api/晋升事务袋", params={"状态": "进行中"}).json() == []
    assert client.get("/api/总览").json()["事务袋在途"] == []
    r = client.get("/api/晋升事务袋", params={"状态": "已切断"})
    assert [b["编号"] for b in r.json()] == [txn]


# ---------- 探针：环境列与态势格同刷 ----------

def test_环境列与态势格同刷(client):
    txn = 进袋(client)
    落成(client, txn)
    s = 快照(client)
    assert 环境版本(s, "结算网关", "预") == "1.3.0"
    inflight = next(r for r in s["在途"] if r["编号"] == 1)
    assert inflight["当前环境"] == "预"
    ov = client.get("/api/总览").json()
    row = next(v for v in ov["环境版本"] if v["应用"] == "结算网关" and v["环境"] == "预")
    assert row["版本"] == "1.3.0"
    assert next(r for r in ov["在途"] if r["编号"] == 1)["当前环境"] == "预"
