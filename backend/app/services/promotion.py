"""晋升事务袋：环境链跃迁与关闸的争用裁决。

整站敲定的唯一争用臂（不再另设开关、不弹选项）：

  关闸优先 —— 关闸提交成功即切断该环境全部在途晋升事务袋；
  被切断的跃迁整笔失败、回到争用前：不改应用环境列、不改发版单当前环境、
  不写放行事件、不动实例，态势格不得计闸外成功，发版单不得记已放行。

可核事实登记形态（整站一种）：promote_txns 事务袋行，
状态机 进行中 → 已落成 / 已切断，落决戳 decided_at 与关闸提交戳
release_windows.closed_at 同源同时，审计时序可重放。

两阶段写口（每阶段各自一个 BEGIN IMMEDIATE 事务，库级串行化）：
  enter_bag  阶段一：校验 + 进袋（闸外硬拒在入场即拒，不进袋）
  settle_bag 阶段二：落成或整笔失败（袋被切断/闸已关 → 只登记切断事实）
"""
from __future__ import annotations
from fastapi import HTTPException
from app.services.common import (
    active_release_window,
    audit,
    env_by_code,
    get_release,
    get_setting,
    now_str,
    ordered_envs,
    set_app_env_version,
    upsert_instance,
)

BAG_INFLIGHT = "进行中"
BAG_LANDED = "已落成"
BAG_CUT = "已切断"

BAG_SELECT = """
SELECT t.id AS 编号, t.release_id AS 发版单编号, r.serial AS 发版单号, a.name AS 应用,
       fe.code AS 源环境, te.code AS 目标环境, t.state AS 状态,
       t.entered_at AS 进袋时间, t.decided_at AS 落决时间,
       t.gate_window_id AS 入场窗编号, t.cut_by_window_id AS 切断窗编号,
       t.note AS 备注
FROM promote_txns t
JOIN releases r ON r.id = t.release_id
JOIN apps a ON a.id = r.app_id
JOIN environments te ON te.id = t.to_env_id
LEFT JOIN environments fe ON fe.id = t.from_env_id
"""


def enter_bag(conn, release_id: int, target_env: str, note: str = "") -> int:
    """阶段一：校验并登记晋升事务袋（须在 immediate 事务内调用）。"""
    r = conn.execute("SELECT * FROM releases WHERE id=?", (release_id,)).fetchone()
    if not r:
        raise HTTPException(404, "发版单不存在")
    if r["status"] not in ("已入闸", "晋升中"):
        raise HTTPException(400, "当前状态不可晋升")
    to_env = env_by_code(conn, target_env)
    envs = ordered_envs(conn)
    codes = [e["code"] for e in envs]
    if target_env not in codes:
        raise HTTPException(400, "目标环境非法")
    cur_env = None
    if r["current_env_id"]:
        cur_env = conn.execute(
            "SELECT * FROM environments WHERE id=?", (r["current_env_id"],)
        ).fetchone()
    allow_skip = get_setting(conn, "允许跳级", "否") == "是"
    if cur_env:
        cur_idx = codes.index(cur_env["code"])
        to_idx = codes.index(target_env)
        if to_idx <= cur_idx:
            raise HTTPException(400, "只能向更高环境晋升")
        if not allow_skip and to_idx != cur_idx + 1:
            raise HTTPException(400, "禁止跳级，须逐级晋升")
    else:
        if target_env != "测":
            raise HTTPException(400, "未落地时只能先入测")

    win = active_release_window(conn, to_env["id"])
    hard = get_setting(conn, "维护窗硬拒", "是") == "是"
    if hard and not win:
        # 闸外硬拒（既有入场策略，不在本闸争用范围内，保持不变）
        raise HTTPException(400, "目标环境放行窗已关，禁止晋升")

    now = now_str()
    cur = conn.execute(
        """
        INSERT INTO promote_txns(release_id, from_env_id, to_env_id, state,
                                 gate_window_id, entered_at, note)
        VALUES (?, ?, ?, '进行中', ?, ?, ?)
        """,
        (release_id, r["current_env_id"], to_env["id"], win["id"] if win else None, now, note),
    )
    txn_id = cur.lastrowid
    audit(conn, "晋升袋", txn_id, "进袋", f"发版单{r['serial']}→{target_env}")
    return txn_id


def settle_bag(conn, txn_id: int) -> dict:
    """阶段二：落成或整笔切断（须在 immediate 事务内调用）。

    进入本函数时写锁已持有，读到的事务袋状态与闸态即终局：
    袋仍进行中且闸仍开 → 整笔落成；否则只登记切断事实，其余一概不动。
    """
    txn = conn.execute("SELECT * FROM promote_txns WHERE id=?", (txn_id,)).fetchone()
    if not txn:
        raise HTTPException(404, "晋升事务袋不存在")
    if txn["state"] == BAG_LANDED:
        return {"结局": BAG_LANDED, "事务袋编号": txn_id,
                "发版单": dict(get_release(conn, txn["release_id"]))}

    now = now_str()
    hard = get_setting(conn, "维护窗硬拒", "是") == "是"
    win = active_release_window(conn, txn["to_env_id"])
    if txn["state"] != BAG_INFLIGHT or (hard and not win):
        # 关闸抢先：闸已关 → 跃迁整笔失败，回争用前。
        # 环境列 / 发版单 / 实例 / 放行事件一概不写，只补登记切断事实（幂等）。
        if txn["state"] == BAG_INFLIGHT:
            conn.execute(
                "UPDATE promote_txns SET state='已切断', decided_at=? WHERE id=?",
                (now, txn_id),
            )
            audit(conn, "晋升袋", txn_id, "闸关切断", "闸先关，跃迁整笔失败")
        return {"结局": BAG_CUT, "事务袋编号": txn_id,
                "发版单": dict(get_release(conn, txn["release_id"]))}

    # 跃迁抢先：袋在闸内整笔落成。
    r = conn.execute("SELECT * FROM releases WHERE id=?", (txn["release_id"],)).fetchone()
    to_env = conn.execute("SELECT * FROM environments WHERE id=?", (txn["to_env_id"],)).fetchone()
    conn.execute(
        """
        INSERT INTO promote_events(release_id, from_env_id, to_env_id, decision, created_at, note, txn_id)
        VALUES (?, ?, ?, '放行', ?, ?, ?)
        """,
        (txn["release_id"], txn["from_env_id"], txn["to_env_id"], now, txn["note"], txn_id),
    )
    new_status = "已放行" if to_env["code"] == "产" else "晋升中"
    released_at = now if to_env["code"] == "产" else r["released_at"]
    conn.execute(
        "UPDATE releases SET status=?, current_env_id=?, released_at=? WHERE id=?",
        (new_status, txn["to_env_id"], released_at, txn["release_id"]),
    )
    set_app_env_version(conn, r["app_id"], txn["to_env_id"], r["target_version"])
    upsert_instance(conn, r["app_id"], txn["to_env_id"], r["target_version"], "探针绿", txn["release_id"])
    conn.execute(
        "UPDATE promote_txns SET state='已落成', decided_at=? WHERE id=?",
        (now, txn_id),
    )
    audit(conn, "晋升袋", txn_id, "落成", f"发版单{r['serial']}→{to_env['code']}")
    audit(conn, "晋升", txn["release_id"], f"晋升到{to_env['code']}", txn["note"])
    return {"结局": BAG_LANDED, "事务袋编号": txn_id,
            "发版单": dict(get_release(conn, txn["release_id"]))}


def close_release_gate(conn, env_code: str) -> dict:
    """关闸写口（须在 immediate 事务内）。

    关闸提交成功即切断该环境全部在途晋升事务袋；关闸提交戳、
    袋落决戳、审计戳同源同时。关闸从不因在途跃迁而失败。
    """
    env = env_by_code(conn, env_code)
    row = conn.execute(
        "SELECT * FROM release_windows WHERE env_id=? ORDER BY id DESC LIMIT 1",
        (env["id"],),
    ).fetchone()
    if not row:
        raise HTTPException(404, "无放行窗记录")
    now = now_str()
    cut = conn.execute(
        "SELECT id, release_id FROM promote_txns WHERE to_env_id=? AND state='进行中'",
        (env["id"],),
    ).fetchall()
    for t in cut:
        conn.execute(
            """
            UPDATE promote_txns SET state='已切断', decided_at=?, cut_by_window_id=?
            WHERE id=?
            """,
            (now, row["id"], t["id"]),
        )
        audit(conn, "晋升袋", t["id"], "闸关切断", f"{env_code}闸先关，跃迁整笔失败")
    conn.execute(
        "UPDATE release_windows SET status='窗关', closed_at=? WHERE id=?",
        (now, row["id"]),
    )
    audit(conn, "放行窗", row["id"], "窗关", f"{env_code} 切断在途跃迁{len(cut)}笔")
    return {
        "环境": env_code,
        "状态": "窗关",
        "时间": now,
        "切断事务袋": [t["id"] for t in cut],
        "切断数": len(cut),
    }


def open_release_gate(conn, env_code: str) -> dict:
    """开闸写口（须在 immediate 事务内）：重开并清关闸提交戳。"""
    env = env_by_code(conn, env_code)
    row = conn.execute(
        "SELECT * FROM release_windows WHERE env_id=? ORDER BY id DESC LIMIT 1",
        (env["id"],),
    ).fetchone()
    if not row:
        raise HTTPException(404, "无放行窗记录")
    conn.execute(
        "UPDATE release_windows SET status='窗开', closed_at=NULL WHERE id=?",
        (row["id"],),
    )
    audit(conn, "放行窗", row["id"], "窗开", env_code)
    return {"环境": env_code, "状态": "窗开", "时间": now_str()}
