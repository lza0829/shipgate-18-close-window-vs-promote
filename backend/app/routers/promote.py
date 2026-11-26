from __future__ import annotations
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.db import db, rows_to_list
from app.services.promotion import BAG_SELECT, enter_bag, settle_bag

router = APIRouter(tags=["晋升"])


class PromoteIn(BaseModel):
    目标环境: str
    备注: str = ""


@router.post("/发版单/{release_id}/晋升")
def promote(release_id: int, body: PromoteIn):
    # 阶段一：校验 + 进晋升事务袋（独立事务，袋行进库即对关闸可见）
    with db(immediate=True) as conn:
        txn_id = enter_bag(conn, release_id, body.目标环境, body.备注)
    # 阶段二：落成或整笔切断（与关闸写口库级串行，谁先提交谁生效）
    with db(immediate=True) as conn:
        outcome = settle_bag(conn, txn_id)
    if outcome["结局"] == "已切断":
        raise HTTPException(
            409,
            f"放行窗已关，晋升事务袋#{txn_id}被切断，跃迁整笔失败（环境列未改、发版单未放行）",
        )
    receipt = outcome["发版单"]
    receipt["事务袋编号"] = txn_id
    receipt["结局"] = outcome["结局"]
    return receipt


@router.get("/晋升事务袋")
def list_bags(状态: str = ""):
    sql = BAG_SELECT
    args: tuple = ()
    if 状态:
        sql += " WHERE t.state=?"
        args = (状态,)
    sql += " ORDER BY t.id DESC LIMIT 100"
    with db() as conn:
        return rows_to_list(conn.execute(sql, args).fetchall())
