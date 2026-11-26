import React, { useEffect, useState } from 'react'
import { api } from '../api'

const KINDS = ['', '晋升袋', '晋升', '放行窗', '回滚窗', '发版单', '回滚', '应用', '设置', '探针', '系统']

export default function Audit() {
  const [rows, setRows] = useState([])
  const [kind, setKind] = useState('')
  const [err, setErr] = useState('')
  const load = (k = kind) =>
    api('/审计' + (k ? `?类别=${encodeURIComponent(k)}` : '')).then(setRows).catch((e) => setErr(e.message))
  useEffect(() => { load() }, [])
  const pick = (k) => { setKind(k); load(k) }
  return (
    <div className="panel">
      <h2>审计流水</h2>
      {err && <p className="err">{err}</p>}
      <div className="row">
        <label>类别
          <select value={kind} onChange={(e) => pick(e.target.value)}>
            {KINDS.map((k) => <option key={k} value={k}>{k || '全部'}</option>)}
          </select>
        </label>
        <button type="button" className="secondary" onClick={() => load()}>刷新</button>
      </div>
      <div className="table-wrap">
        <table>
          <thead><tr><th>时间</th><th>类别</th><th>动作</th><th>关联</th><th>备注</th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.编号}><td>{r.时间}</td><td>{r.类别}</td><td>{r.动作}</td><td>{r.关联编号 || '-'}</td><td>{r.备注}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
