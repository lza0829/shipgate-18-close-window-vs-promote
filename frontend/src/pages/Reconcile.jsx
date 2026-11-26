import React, { useEffect, useState } from 'react'
import { api } from '../api'

export default function Reconcile() {
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')
  const load = () => api('/对账').then(setData).catch((e) => setErr(e.message))
  useEffect(() => { load() }, [])
  if (err) return <div className="panel err">{err}</div>
  if (!data) return <div className="panel">加载中</div>
  const s = data.发版统计 || {}
  const buckets = data.事务袋分桶 || {}
  const outOfGate = data.闸外跃迁 || []
  return (
    <div className="panel">
      <h2>发布对账</h2>
      <div className="grid">
        {Object.entries(s).map(([k, v]) => (
          <div className="stat" key={k}><div className="n">{v}</div><div className="l">{k}</div></div>
        ))}
        <div className="stat"><div className="n">{data.晋升事件数}</div><div className="l">晋升事件数</div></div>
      </div>
      <h2>晋升事务袋分桶</h2>
      <div className="grid">
        {Object.entries(buckets).map(([k, v]) => (
          <div className="stat" key={k}><div className="n">{v}</div><div className="l">{k}</div></div>
        ))}
        <div className="stat" style={outOfGate.length ? { borderBottomColor: 'var(--danger)' } : undefined}>
          <div className="n" style={outOfGate.length ? { color: 'var(--danger)' } : undefined}>{outOfGate.length}</div>
          <div className="l">闸外跃迁（须恒为零）</div>
        </div>
      </div>
      {outOfGate.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead><tr><th>袋编号</th><th>发版单号</th><th>目标环境</th><th>落决时间</th><th>问题</th></tr></thead>
            <tbody>
              {outOfGate.map((v, i) => (
                <tr key={i}><td>#{v.袋编号}</td><td>{v.发版单号}</td><td>{v.目标环境}</td><td>{v.落决时间}</td><td className="err">{v.问题}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <h2>名册与实例</h2>
      <div className="table-wrap">
        <table>
          <thead><tr><th>应用</th><th>环境</th><th>名册版本</th><th>实例版本们</th><th>红灯数</th></tr></thead>
          <tbody>
            {(data.名册与实例 || []).map((r, i) => (
              <tr key={i}><td>{r.应用}</td><td>{r.环境}</td><td>{r.名册版本}</td><td>{r.实例版本们 || '-'}</td><td>{r.红灯数}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="row"><button type="button" className="secondary" onClick={load}>刷新</button></div>
    </div>
  )
}
