import React, { useEffect, useState } from 'react'
import { api } from '../api'

export default function Fixture() {
  const [releases, setReleases] = useState([])
  const [rid, setRid] = useState('')
  const [env, setEnv] = useState('预')
  const [txn, setTxn] = useState('')
  const [order, setOrder] = useState('同发')
  const [snap, setSnap] = useState(null)
  const [result, setResult] = useState('')
  const [err, setErr] = useState('')

  const loadSnap = () => api('/夹具/快照').then(setSnap).catch((e) => setErr(e.message))
  const load = async () => {
    const all = await api('/发版单')
    const active = all.filter((r) => ['已入闸', '晋升中'].includes(r.状态))
    setReleases(active)
    if (!rid && active[0]) setRid(String(active[0].编号))
    await loadSnap()
  }
  useEffect(() => { load().catch((e) => setErr(e.message)) }, [])

  const run = async (fn, label) => {
    setErr('')
    setResult('')
    try {
      const res = await fn()
      if (label) setResult(typeof res === 'string' ? res : `${label}：${JSON.stringify(res)}`)
      await load()
    } catch (e) { setErr(e.message); loadSnap().catch(() => {}) }
  }

  const enter = () => run(async () => {
    const res = await api('/夹具/进袋', { method: 'POST', body: JSON.stringify({ 发版单编号: Number(rid), 目标环境: env }) })
    setTxn(String(res.事务袋编号))
    return `进袋成功 · 事务袋 #${res.事务袋编号} 进行中`
  }, '')
  const settle = () => run(async () => {
    const res = await api('/夹具/落成', { method: 'POST', body: JSON.stringify({ 事务袋编号: Number(txn) }) })
    return `落成结局 ${res.结局} · 事务袋 #${res.事务袋编号}`
  }, '')
  const close = () => run(async () => {
    const res = await api('/夹具/关闸', { method: 'POST', body: JSON.stringify({ 环境: env }) })
    return `关闸提交 ${res.时间} · 切断在途跃迁 ${res.切断数} 笔`
  }, '')
  const race = () => run(async () => {
    const res = await api('/夹具/争用', {
      method: 'POST',
      body: JSON.stringify({ 发版单编号: Number(rid), 目标环境: env, 顺序: order }),
    })
    setTxn(String(res.事务袋编号))
    return `争用（${res.顺序}）· 袋结局 ${res.袋结局} · 关闸切断 ${res.关闸结果.切断数} 笔 · 关闸提交 ${res.关闸结果.时间}`
  }, '')

  const s = snap
  return (
    <div className="panel">
      <h2>争用夹具 · 关闸 vs 已进事务袋跃迁</h2>
      <p className="muted">选定臂：关闸优先 —— 关闸提交成功即切断在途跃迁，跃迁整笔失败不改环境列；跃迁先落成则记闸内跃迁。</p>
      {err && <p className="err">{err}</p>}
      {result && <p className="muted">{result}</p>}
      <div className="row">
        <label>发版单
          <select value={rid} onChange={(e) => setRid(e.target.value)}>
            {releases.map((r) => <option key={r.编号} value={r.编号}>{r.发版单号} · {r.应用} · {r.当前环境}</option>)}
          </select>
        </label>
        <label>目标环境
          <select value={env} onChange={(e) => setEnv(e.target.value)}>
            <option value="测">测</option>
            <option value="预">预</option>
            <option value="产">产</option>
          </select>
        </label>
        <label>事务袋编号<input value={txn} onChange={(e) => setTxn(e.target.value)} placeholder="进袋后自动填" /></label>
      </div>
      <div className="row">
        <button type="button" className="secondary" onClick={enter}>① 进袋</button>
        <button type="button" className="danger" onClick={close}>② 关闸</button>
        <button type="button" className="secondary" onClick={settle}>③ 落成</button>
        <label>争用顺序
          <select value={order} onChange={(e) => setOrder(e.target.value)}>
            <option value="同发">同发（并发双写口）</option>
            <option value="关闸抢先">关闸抢先</option>
            <option value="跃迁抢先">跃迁抢先</option>
          </select>
        </label>
        <button type="button" onClick={race}>争用一把梭</button>
        <button type="button" className="secondary" onClick={() => load().catch((e) => setErr(e.message))}>刷新快照</button>
      </div>
      {s && (
        <>
          <h2>闸态与事务袋</h2>
          <div className="table-wrap">
            <table>
              <thead><tr><th>环境</th><th>闸态</th><th>关闸提交</th></tr></thead>
              <tbody>{s.窗口.map((w) => <tr key={w.编号}><td>{w.环境}</td><td>{w.状态}</td><td>{w.关闸提交 || '-'}</td></tr>)}</tbody>
            </table>
          </div>
          <div className="table-wrap">
            <table>
              <thead><tr><th>袋编号</th><th>发版单号</th><th>应用</th><th>源</th><th>目标</th><th>状态</th><th>进袋</th><th>落决</th><th>切断窗</th></tr></thead>
              <tbody>
                {s.事务袋.map((b) => (
                  <tr key={b.编号}>
                    <td>#{b.编号}</td><td>{b.发版单号}</td><td>{b.应用}</td><td>{b.源环境 || '-'}</td><td>{b.目标环境}</td>
                    <td>{b.状态}</td><td>{b.进袋时间}</td><td>{b.落决时间 || '-'}</td><td>{b.切断窗编号 || '-'}</td>
                  </tr>
                ))}
                {!s.事务袋.length && <tr><td colSpan="9" className="muted">暂无事务袋</td></tr>}
              </tbody>
            </table>
          </div>
          <h2>环境列 · 在途 · 对账桶</h2>
          <div className="grid">
            {Object.entries(s.对账.事务袋分桶 || {}).map(([k, v]) => (
              <div className="stat" key={k}><div className="n">{v}</div><div className="l">事务袋{k}</div></div>
            ))}
            <div className="stat" style={(s.对账.闸外跃迁 || []).length ? { borderBottomColor: 'var(--danger)' } : undefined}>
              <div className="n" style={(s.对账.闸外跃迁 || []).length ? { color: 'var(--danger)' } : undefined}>
                {(s.对账.闸外跃迁 || []).length}
              </div>
              <div className="l">闸外跃迁（须恒为零）</div>
            </div>
            <div className="stat"><div className="n">{s.在途.length}</div><div className="l">在途发版</div></div>
          </div>
          <div className="table-wrap">
            <table>
              <thead><tr><th>应用</th><th>环境</th><th>版本</th><th>更新时间</th></tr></thead>
              <tbody>{s.环境列.map((v, i) => <tr key={i}><td>{v.应用}</td><td>{v.环境}</td><td>{v.版本 || '-'}</td><td>{v.更新时间 || '-'}</td></tr>)}</tbody>
            </table>
          </div>
          <h2>审计尾</h2>
          <div className="table-wrap">
            <table>
              <thead><tr><th>编号</th><th>时间</th><th>类别</th><th>动作</th><th>备注</th></tr></thead>
              <tbody>{s.审计尾.map((a) => <tr key={a.编号}><td>{a.编号}</td><td>{a.时间}</td><td>{a.类别}</td><td>{a.动作}</td><td>{a.备注}</td></tr>)}</tbody>
            </table>
          </div>
        </>
      )}
    </div>
  )
}
