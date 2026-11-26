from __future__ import annotations
from fastapi import APIRouter
from app.db import db, rows_to_list

router = APIRouter(tags=["审计"])


@router.get("/审计")
def list_audit(类别: str = "", 关联编号: int | None = None):
    sql = """
        SELECT id AS 编号, kind AS 类别, ref_id AS 关联编号,
               action AS 动作, created_at AS 时间, note AS 备注
        FROM audit_events
    """
    conds, args = [], []
    if 类别:
        conds.append("kind=?")
        args.append(类别)
    if 关联编号 is not None:
        conds.append("ref_id=?")
        args.append(关联编号)
    if conds:
        sql += " WHERE " + " AND ".join(conds)
    sql += " ORDER BY id DESC LIMIT 200"
    with db() as conn:
        return rows_to_list(conn.execute(sql, tuple(args)).fetchall())
