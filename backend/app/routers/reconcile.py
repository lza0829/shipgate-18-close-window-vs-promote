from __future__ import annotations
from fastapi import APIRouter
from app.db import db, rows_to_list
from app.services.promotion import BAG_CUT, BAG_INFLIGHT, BAG_LANDED

router = APIRouter(tags=["对账"])


def reconcile_payload(conn) -> dict:
    release_stats = {
        "申请数": conn.execute("SELECT COUNT(*) AS c FROM releases").fetchone()["c"],
        "已放行": conn.execute(
            "SELECT COUNT(*) AS c FROM releases WHERE status='已放行'"
        ).fetchone()["c"],
        "已回滚": conn.execute(
            "SELECT COUNT(*) AS c FROM releases WHERE status='已回滚'"
        ).fetchone()["c"],
        "在途": conn.execute(
            """
            SELECT COUNT(*) AS c FROM releases
            WHERE status IN ('已入闸','晋升中','已放行','回滚中')
            """
        ).fetchone()["c"],
    }
    version_vs_instance = rows_to_list(
        conn.execute(
            """
            SELECT a.name AS 应用, e.code AS 环境,
                   v.version AS 名册版本,
                   GROUP_CONCAT(i.version, ',') AS 实例版本们,
                   SUM(CASE WHEN i.health='探针红' THEN 1 ELSE 0 END) AS 红灯数
            FROM app_env_versions v
            JOIN apps a ON a.id = v.app_id
            JOIN environments e ON e.id = v.env_id
            LEFT JOIN instances i ON i.app_id = v.app_id AND i.env_id = v.env_id
            GROUP BY v.app_id, v.env_id
            ORDER BY a.id, e.sort_order
            """
        ).fetchall()
    )
    promote_count = conn.execute("SELECT COUNT(*) AS c FROM promote_events").fetchone()["c"]
    # 晋升事务袋分桶：争用结局在对账侧的分桶登记
    bag_buckets = {}
    for state in (BAG_INFLIGHT, BAG_LANDED, BAG_CUT):
        bag_buckets[state] = conn.execute(
            "SELECT COUNT(*) AS c FROM promote_txns WHERE state=?", (state,)
        ).fetchone()["c"]
    # 闸外跃迁桶（关闸优先臂下须恒空）：被切断事务袋却留下落成痕迹即违例
    out_of_gate = rows_to_list(
        conn.execute(
            """
            SELECT t.id AS 袋编号, r.serial AS 发版单号, te.code AS 目标环境,
                   t.decided_at AS 落决时间, '切断袋留有放行事件' AS 问题
            FROM promote_txns t
            JOIN releases r ON r.id = t.release_id
            JOIN environments te ON te.id = t.to_env_id
            WHERE t.state='已切断'
              AND EXISTS (
                    SELECT 1 FROM promote_events p
                    WHERE p.txn_id = t.id AND p.decision='放行'
                  )
            UNION ALL
            SELECT t.id, r.serial, te.code, t.decided_at,
                   '切断袋目标环境已落且无落成袋'
            FROM promote_txns t
            JOIN releases r ON r.id = t.release_id
            JOIN environments te ON te.id = t.to_env_id
            WHERE t.state='已切断'
              AND r.current_env_id = t.to_env_id
              AND NOT EXISTS (
                    SELECT 1 FROM promote_txns t2
                    WHERE t2.release_id = t.release_id
                      AND t2.to_env_id = t.to_env_id
                      AND t2.state = '已落成'
                  )
            ORDER BY 1
            """
        ).fetchall()
    )
    return {
        "发版统计": release_stats,
        "晋升事件数": promote_count,
        "名册与实例": version_vs_instance,
        "事务袋分桶": bag_buckets,
        "闸外跃迁": out_of_gate,
    }


@router.get("/对账")
def reconcile():
    with db() as conn:
        return reconcile_payload(conn)
