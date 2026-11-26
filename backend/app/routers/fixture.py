"""争用夹具：关闸与已进事务袋跃迁的对照场景，逐招可单独复现。

- POST /夹具/进袋      只走阶段一（进晋升事务袋），返回事务袋编号
- POST /夹具/落成      只走阶段二（落成或整笔切断），结局看响应字段
- POST /夹具/关闸      关闸写口探针：切断在途袋并回报切断清单
- POST /夹具/争用      对照场景一把梭：关闸抢先 / 跃迁抢先 / 同发并发双写口
- GET  /夹具/快照      单事务对齐快照：闸态、事务袋、发版单、环境列、
                       在途态势、对账分桶、审计尾，用于核对各面不裂
"""
from __future__ import annotations
import threading
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.db import db, rows_to_list
from app.services.common import RELEASE_SELECT
from app.services.promotion import BAG_SELECT, close_release_gate, enter_bag, settle_bag
from app.routers.reconcile import reconcile_payload

router = APIRouter(tags=["夹具"])


class EnterIn(BaseModel):
    发版单编号: int
    目标环境: str
    备注: str = ""


class SettleIn(BaseModel):
    事务袋编号: int


class GateIn(BaseModel):
    环境: str


class RaceIn(BaseModel):
    发版单编号: int
    目标环境: str
    顺序: str = "同发"  # 关闸抢先 | 跃迁抢先 | 同发
    备注: str = ""


def _snapshot(conn) -> dict:
    return {
        "窗口": rows_to_list(
            conn.execute(
                """
                SELECT w.id AS 编号, e.code AS 环境, w.status AS 状态,
                       w.open_at AS 开启, w.close_at AS 关闭, w.closed_at AS 关闸提交
                FROM release_windows w JOIN environments e ON e.id = w.env_id
                ORDER BY e.sort_order, w.id DESC
                """
            ).fetchall()
        ),
        "事务袋": rows_to_list(conn.execute(BAG_SELECT + " ORDER BY t.id DESC LIMIT 20").fetchall()),
        "发版单": rows_to_list(conn.execute(RELEASE_SELECT + " ORDER BY r.id DESC").fetchall()),
        "环境列": rows_to_list(
            conn.execute(
                """
                SELECT a.name AS 应用, e.code AS 环境, v.version AS 版本, v.updated_at AS 更新时间
                FROM app_env_versions v
                JOIN apps a ON a.id = v.app_id
                JOIN environments e ON e.id = v.env_id
                ORDER BY a.id, e.sort_order
                """
            ).fetchall()
        ),
        "在途": rows_to_list(
            conn.execute(
                RELEASE_SELECT
                + " WHERE r.status IN ('已入闸','晋升中','已放行','回滚中') ORDER BY r.id DESC"
            ).fetchall()
        ),
        "对账": reconcile_payload(conn),
        "审计尾": rows_to_list(
            conn.execute(
                """
                SELECT id AS 编号, kind AS 类别, ref_id AS 关联编号,
                       action AS 动作, created_at AS 时间, note AS 备注
                FROM audit_events ORDER BY id DESC LIMIT 15
                """
            ).fetchall()
        ),
    }


@router.get("/夹具/快照")
def snapshot():
    with db() as conn:
        return _snapshot(conn)


@router.post("/夹具/进袋")
def fixture_enter(body: EnterIn):
    with db(immediate=True) as conn:
        txn_id = enter_bag(conn, body.发版单编号, body.目标环境, body.备注)
    return {"事务袋编号": txn_id, "状态": "进行中"}


@router.post("/夹具/落成")
def fixture_settle(body: SettleIn):
    with db(immediate=True) as conn:
        return settle_bag(conn, body.事务袋编号)


@router.post("/夹具/关闸")
def fixture_close(body: GateIn):
    with db(immediate=True) as conn:
        return close_release_gate(conn, body.环境)


def _race(txn_id: int, env_code: str) -> dict:
    """并发双写口：落成与关闸同发，库级串行化后必居其一。"""
    barrier = threading.Barrier(2)
    results: dict = {}
    errors: list = []

    def do_settle():
        try:
            barrier.wait()
            with db(immediate=True) as conn:
                results["袋"] = settle_bag(conn, txn_id)
        except Exception as exc:  # pragma: no cover - 防御
            errors.append(f"落成写口：{exc}")

    def do_close():
        try:
            barrier.wait()
            with db(immediate=True) as conn:
                results["闸"] = close_release_gate(conn, env_code)
        except Exception as exc:  # pragma: no cover - 防御
            errors.append(f"关闸写口：{exc}")

    t1 = threading.Thread(target=do_settle)
    t2 = threading.Thread(target=do_close)
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    if errors:
        raise HTTPException(500, "；".join(errors))
    return results


@router.post("/夹具/争用")
def fixture_race(body: RaceIn):
    if body.顺序 not in ("关闸抢先", "跃迁抢先", "同发"):
        raise HTTPException(400, "顺序仅允许 关闸抢先 / 跃迁抢先 / 同发")
    with db(immediate=True) as conn:
        txn_id = enter_bag(conn, body.发版单编号, body.目标环境, body.备注)

    if body.顺序 == "关闸抢先":
        with db(immediate=True) as conn:
            gate = close_release_gate(conn, body.目标环境)
        with db(immediate=True) as conn:
            bag = settle_bag(conn, txn_id)
    elif body.顺序 == "跃迁抢先":
        with db(immediate=True) as conn:
            bag = settle_bag(conn, txn_id)
        with db(immediate=True) as conn:
            gate = close_release_gate(conn, body.目标环境)
    else:
        results = _race(txn_id, body.目标环境)
        bag = results.get("袋", {})
        gate = results.get("闸", {})

    with db() as conn:
        snap = _snapshot(conn)
    return {
        "事务袋编号": txn_id,
        "顺序": body.顺序,
        "袋结局": bag.get("结局"),
        "关闸结果": gate,
        "快照": snap,
    }
