import React, { useEffect, useState } from 'react'
import { api } from '../api'

export default function Promote() {
  const [rows, setRows] = useState([])
  const [bags, setBags] = useState([])
  const [rid, setRid] = useState('')
  const [env, setEnv] = useState('预')
  const [err, setErr] = useState('')
  const [ok, setOk] = useState('')
  const load = async () => {
    const all = await api('/发版单')
    const active = all.filter((r) => ['已入闸', '晋升中'].includes(r.状态))
    setRows(active)
    if (!rid && active[0]) setRid(String(active[0].编号))
    setBags(await api('/晋升事务袋'))
  }
  useEffect(() => { load().catch((e) => setErr(e.message)) }, [])
  const go = async () => {
    setErr('')
    setOk('')
    try {
      const res = await api(`/发版单/${rid}/晋升`, { method: 'POST', body: JSON.stringify({ 目标环境: env }) })
      setOk(`跃迁落成 · 事务袋 #${res.事务袋编号} 已落成 · ${res.发版单号} 当前环境 ${res.当前环境}`)
      load()
    } catch (e) { setErr(e.message); load().catch(() => {}) }
  }
  return (
    <div className="panel">
      <h2>环境晋升</h2>
      {err && <p className="err">{err}</p>}
      {ok && <p className="muted">{ok}</p>}
      <div className="row">
        <label>发版单
          <select value={rid} onChange={(e) => setRid(e.target.value)}>
            {rows.map((r) => <option key={r.编号} value={r.编号}>{r.发版单号} · {r.应用} · {r.当前环境}</option>)}
          </select>
        </label>
        <label>目标环境
          <select value={env} onChange={(e) => setEnv(e.target.value)}>
            <option value="测">测</option>
            <option value="预">预</option>
            <option value="产">产</option>
          </select>
        </label>
        <button type="button" onClick={go}>晋升</button>
        <button type="button" className="secondary" onClick={() => load().catch((e) => setErr(e.message))}>刷新</button>
      </div>
      <div className="table-wrap">
        <table>
          <thead><tr><th>发版单号</th><th>应用</th><th>目标版本</th><th>状态</th><th>当前环境</th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.编号}><td>{r.发版单号}</td><td>{r.应用}</td><td>{r.目标版本}</td><td>{r.状态}</td><td>{r.当前环境}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
      <h2>晋升事务袋</h2>
      <div className="table-wrap">
        <table>
          <thead><tr><th>袋编号</th><th>发版单号</th><th>应用</th><th>源环境</th><th>目标环境</th><th>状态</th><th>进袋时间</th><th>落决时间</th></tr></thead>
          <tbody>
            {bags.map((b) => (
              <tr key={b.编号}>
                <td>#{b.编号}</td><td>{b.发版单号}</td><td>{b.应用}</td><td>{b.源环境 || '-'}</td><td>{b.目标环境}</td>
                <td>{b.状态}</td><td>{b.进袋时间}</td><td>{b.落决时间 || '-'}</td>
              </tr>
            ))}
            {!bags.length && <tr><td colSpan="8" className="muted">暂无事务袋</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  )
}
