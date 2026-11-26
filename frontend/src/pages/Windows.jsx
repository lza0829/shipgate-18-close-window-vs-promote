import React, { useEffect, useState } from 'react'
import { api } from '../api'

export default function Windows() {
  const [rel, setRel] = useState([])
  const [rb, setRb] = useState([])
  const [bags, setBags] = useState([])
  const [env, setEnv] = useState('产')
  const [err, setErr] = useState('')
  const [report, setReport] = useState(null)
  const load = async () => {
    setRel(await api('/放行窗'))
    setRb(await api('/回滚窗'))
    setBags(await api('/晋升事务袋?状态=进行中'))
  }
  useEffect(() => { load().catch((e) => setErr(e.message)) }, [])
  const toggle = async (kind, status) => {
    setErr('')
    setReport(null)
    try {
      const path = kind === '放行' ? '/放行窗/切换' : '/回滚窗/切换'
      const res = await api(path, { method: 'POST', body: JSON.stringify({ 环境: env, 状态: status }) })
      if (kind === '放行' && status === '窗关') {
        setReport(`关闸提交 ${res.时间} · ${env}闸已关 · 切断在途跃迁 ${res.切断数} 笔` +
          (res.切断数 ? `（事务袋 ${res.切断事务袋.map((i) => `#${i}`).join(' ')}，跃迁整笔失败）` : ''))
      } else {
        setReport(`${kind}窗${status === '窗开' ? '已开' : '已关'} · ${res.时间}`)
      }
      load()
    } catch (e) { setErr(e.message) }
  }
  return (
    <div className="panel">
      <h2>放行窗 / 回滚窗</h2>
      {err && <p className="err">{err}</p>}
      {report && <p className="muted">{report}</p>}
      <div className="row">
        <label>环境
          <select value={env} onChange={(e) => setEnv(e.target.value)}>
            <option value="测">测</option>
            <option value="预">预</option>
            <option value="产">产</option>
          </select>
        </label>
        <button type="button" onClick={() => toggle('放行', '窗开')}>放行窗开</button>
        <button type="button" className="danger" onClick={() => toggle('放行', '窗关')}>放行窗关</button>
        <button type="button" onClick={() => toggle('回滚', '窗开')}>回滚窗开</button>
        <button type="button" className="danger" onClick={() => toggle('回滚', '窗关')}>回滚窗关</button>
        <button type="button" className="secondary" onClick={() => load().catch((e) => setErr(e.message))}>刷新</button>
      </div>
      <h2>在途晋升事务袋（关闸即切断）</h2>
      <div className="table-wrap">
        <table>
          <thead><tr><th>袋编号</th><th>发版单号</th><th>应用</th><th>源环境</th><th>目标环境</th><th>进袋时间</th></tr></thead>
          <tbody>
            {bags.map((b) => (
              <tr key={b.编号}><td>#{b.编号}</td><td>{b.发版单号}</td><td>{b.应用}</td><td>{b.源环境 || '-'}</td><td>{b.目标环境}</td><td>{b.进袋时间}</td></tr>
            ))}
            {!bags.length && <tr><td colSpan="6" className="muted">无在途跃迁</td></tr>}
          </tbody>
        </table>
      </div>
      <h2>放行窗</h2>
      <div className="table-wrap">
        <table>
          <thead><tr><th>环境</th><th>开启</th><th>关闭</th><th>状态</th><th>关闸提交</th></tr></thead>
          <tbody>{rel.map((w) => <tr key={w.编号}><td>{w.环境}</td><td>{w.开启}</td><td>{w.关闭}</td><td>{w.状态}</td><td>{w.关闸提交 || '-'}</td></tr>)}</tbody>
        </table>
      </div>
      <h2>回滚窗</h2>
      <div className="table-wrap">
        <table>
          <thead><tr><th>环境</th><th>开启</th><th>关闭</th><th>状态</th></tr></thead>
          <tbody>{rb.map((w) => <tr key={w.编号}><td>{w.环境}</td><td>{w.开启}</td><td>{w.关闭}</td><td>{w.状态}</td></tr>)}</tbody>
        </table>
      </div>
    </div>
  )
}
