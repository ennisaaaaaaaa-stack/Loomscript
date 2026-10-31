import { useEffect, useRef, useState } from 'react'
import { CoverCard } from '../components/CoverCard'
import { Timeline, type TimelineItem } from '../components/Timeline'
import { applyGen, GEN_STAGES, initialGen, type GenView } from '../contract/gen'
import { applyPatch, blankChar, emptySpec, PRESETS, specReady, type CharSpec, type GenSpec, type SpecPatch } from '../contract/genSpec'
import { normalizeBundle } from '../contract/normalize'
import { startGen, type Stop } from '../data/gen'
import { useStore } from '../state/store'

const SEV_LABEL = { error: '错误', warning: '警告', info: '提示' } as const

interface ChatMsg { role: 'user' | 'assistant' | 'sys'; text: string; changes?: string[] }

const QUICK = ['帮我想一个背景', '按这个背景配 5 个角色', '给每个角色加一个不可告人的秘密', '检查一下结构有什么漏洞']

/** patch → 人话：助手这次改了什么 */
function describePatch(p: SpecPatch): string[] {
  const out: string[] = []
  const LABEL: Record<string, string> = { title: '标题', genre: '类型', era: '时代', world: '世界观', tone: '基调', acts: '幕数', notes: '其他要求' }
  for (const [k, v] of Object.entries(p.set ?? {})) if (v !== undefined && v !== '' && LABEL[k]) out.push(LABEL[k])
  for (const c of p.add_characters ?? []) if (c?.name) out.push(`+${c.name}`)
  for (const c of p.update_characters ?? []) if (c?.name) out.push(`改 ${c.name}`)
  for (const n of p.remove_characters ?? []) out.push(`−${n}`)
  return out
}

export function GenPage() {
  const { handoff, load, startLive } = useStore()
  const [spec, setSpec] = useState<GenSpec>(emptySpec)
  const [text, setText] = useState('')
  const [view, setView] = useState<GenView | null>(null)
  const [chat, setChat] = useState<ChatMsg[]>([{ role: 'assistant', text: '我是创作助手。先说说你想做一个什么样的本：什么年代、什么氛围、想让玩家在哪一刻背后发凉？也可以直接点左边的背景预设，或者让我替你起个头。' }])
  const [draft, setDraft] = useState('')
  const [thinking, setThinking] = useState(false)
  const [flash, setFlash] = useState<string[]>([])
  const stop = useRef<Stop | null>(null)
  const chatEnd = useRef<HTMLDivElement>(null)
  useEffect(() => () => stop.current?.(), [])
  useEffect(() => { chatEnd.current?.scrollIntoView({ block: 'nearest' }) }, [chat, thinking])

  const set = <K extends keyof GenSpec>(k: K, v: GenSpec[K]) => setSpec((s) => ({ ...s, [k]: v }))
  const setChar = (key: string, p: Partial<CharSpec>) => setSpec((s) => ({ ...s, characters: s.characters.map((c) => (c.key === key ? { ...c, ...p } : c)) }))
  const ready = specReady(spec, text)

  const send = async (message: string) => {
    const m = message.trim()
    if (!m || thinking) return
    const history = chat.filter((c) => c.role !== 'sys').map((c) => ({ role: c.role as 'user' | 'assistant', text: c.text }))
    setChat((c) => [...c, { role: 'user', text: m }])
    setDraft('')
    setThinking(true)
    try {
      const { assistGen } = await import('../engine/ai')
      const { reply, patch } = await assistGen(spec, text, history, m)
      const changes = describePatch(patch)
      setSpec((s) => applyPatch(s, patch))
      setChat((c) => [...c, { role: 'assistant', text: reply, changes }])
      setFlash(changes)
      setTimeout(() => setFlash([]), 2400)
    } catch (e) {
      setChat((c) => [...c, { role: 'sys', text: `助手没接上：${e instanceof Error ? e.message : String(e)}。左边的表单可以直接手填，生成照样能用。` }])
    } finally {
      setThinking(false)
    }
  }

  const running = !!view && !view.bundle && view.stages.done.status !== 'failed'
  const run = () => {
    stop.current?.()
    setView(initialGen())
    stop.current = startGen(text, (e) => setView((v) => applyGen(v ?? initialGen(), e, normalizeBundle)), handoff?.bundle, spec)
  }

  const stageIds = view ? Object.keys(view.stages) : GEN_STAGES.map((s) => s.id as string)
  const items: TimelineItem[] = stageIds.map((id) => {
    const st = view?.stages[id]
    const label = GEN_STAGES.find((s) => s.id === id)?.label ?? id
    const status: TimelineItem['status'] = !st || st.status === 'pending' ? 'pending' : st.status === 'running' ? 'active' : st.status === 'failed' ? 'error' : 'done'
    return {
      id,
      status,
      title: <>{label}{st?.status === 'ok' && ' ✓'}{st?.status === 'skipped' && '（跳过）'}</>,
      sub: st && st.status !== 'pending' ? (
        <>
          {st.status === 'running' && <span className="bar"><i style={{ width: `${Math.round(st.progress * 100)}%` }} /></span>}
          {st.message}
          {st.issues.map((i, k) => (
            <span key={k} className={`issue issue--${i.severity}`}>
              {SEV_LABEL[i.severity] ?? i.severity}：{i.message}{i.auto_fixed && '（已自动处理）'}
            </span>
          ))}
        </>
      ) : undefined,
    }
  })
  const hl = (k: string) => (flash.includes(k) ? ' flash' : '')

  return (
    <div className="gen2">
      <div className="gen2__form">
        <h2>创作一个新剧本</h2>
        <p className="muted small">填多少算多少：空着的部分生成时由 Claude 补。右边的助手会把聊出来的设定直接填进这里，你随时可以改。</p>

        <section className="card">
          <h4>背景设定</h4>
          <div className="chips">
            {PRESETS.map((p) => (
              <button key={p.label} className={spec.genre === p.set.genre ? 'pill on' : 'pill'} onClick={() => setSpec((s) => ({ ...s, ...p.set }))}>{p.label}</button>
            ))}
          </div>
          <div className="grid2">
            <label className={`field${hl('标题')}`}>标题<input value={spec.title} onChange={(e) => set('title', e.target.value)} placeholder="留空则自动起名" /></label>
            <label className={`field${hl('类型')}`}>类型<input value={spec.genre} onChange={(e) => set('genre', e.target.value)} placeholder="如：宫廷权谋 / 本格推理" /></label>
            <label className={`field${hl('时代')}`}>时代 / 地点<input value={spec.era} onChange={(e) => set('era', e.target.value)} placeholder="如：1930 年代上海" /></label>
            <label className={`field${hl('基调')}`}>基调<input value={spec.tone} onChange={(e) => set('tone', e.target.value)} placeholder="如：压抑、互相猜疑" /></label>
          </div>
          <label className={`field${hl('世界观')}`}>世界观与故事起点
            <textarea rows={3} value={spec.world} onChange={(e) => set('world', e.target.value)} placeholder="发生了什么事、大家为什么聚在这里、桌上摆着什么谜题" />
          </label>
          <div className="row">
            <span className={`field-inline${hl('幕数')}`}>幕数
              {[2, 3, 4, 5].map((n) => <button key={n} className={spec.acts === n ? 'pill on' : 'pill'} onClick={() => set('acts', n)}>{n}</button>)}
            </span>
          </div>
        </section>

        <section className="card">
          <div className="row between">
            <h4>角色卡 <span className="muted small">{ready.chars} 个 · 可扮演 {ready.players}</span></h4>
            <button className="ghost" onClick={() => setSpec((s) => ({ ...s, characters: [...s.characters, blankChar()] }))}>＋ 添加角色</button>
          </div>
          {!spec.characters.length && <p className="muted small">还没有角色。手动添加，或者让助手「按这个背景配 5 个角色」。</p>}
          <div className="charcards">
            {spec.characters.map((c) => (
              <div key={c.key} className={`charcard${flash.some((f) => f.endsWith(c.name) && c.name) ? ' flash' : ''}`}>
                <div className="row between">
                  <input className="charcard__name" value={c.name} onChange={(e) => setChar(c.key, { name: e.target.value })} placeholder="名字" />
                  <label className="toggle"><input type="checkbox" checked={c.is_player} onChange={(e) => setChar(c.key, { is_player: e.target.checked })} />可扮演</label>
                  <button className="ghost small" title="删除" onClick={() => setSpec((s) => ({ ...s, characters: s.characters.filter((x) => x.key !== c.key) }))}>×</button>
                </div>
                <input value={c.identity} onChange={(e) => setChar(c.key, { identity: e.target.value })} placeholder="公开身份" />
                <textarea rows={2} value={c.secret} onChange={(e) => setChar(c.key, { secret: e.target.value })} placeholder="秘密（只有 TA 自己知道）" />
                <input value={c.goal} onChange={(e) => setChar(c.key, { goal: e.target.value })} placeholder="目标（TA 这局想得到什么）" />
              </div>
            ))}
          </div>
        </section>

        <section className="card">
          <details open={!!text}>
            <summary><h4>原文（可选）</h4></summary>
            <textarea value={text} onChange={(e) => setText(e.target.value)} placeholder="贴一段小说、剧本或新闻做底本；不贴就按上面的结构原创" rows={6} />
            <span className="muted small">{text.length} 字</span>
          </details>
          <label className={`field${hl('其他要求')}`}>其他要求
            <input value={spec.notes} onChange={(e) => set('notes', e.target.value)} placeholder="如：要有一个反转结局；凶手必须是可扮演角色" />
          </label>
        </section>

        <div className="row">
          <button className="primary" disabled={!ready.hasAnything || running} onClick={run}>{running ? '生成中…' : '按这个结构生成'}</button>
          <span className="muted small">{ready.hasAnything ? `${spec.acts} 幕 · ${ready.chars ? `${ready.chars} 个指定角色` : '角色由 Claude 设计'}${text ? ' · 参考原文' : ''} · 约半分钟到一分钟` : '先填点什么，或者和右边的助手聊两句'}</span>
        </div>
      </div>

      <aside className="gen2__chat">
        <div className="chat">
          <div className="chat__head">创作助手</div>
          <div className="chat__flow">
            {chat.map((m, i) => (
              m.role === 'sys'
                ? <div key={i} className="sys"><div className="sys__sub">{m.text}</div></div>
                : (
                  <div key={i} className={m.role === 'user' ? 'msg msg--mine' : 'msg'}>
                    <div className="msg__body">
                      <div className="msg__text">{m.text}</div>
                      {!!m.changes?.length && <div className="msg__changes">已填入：{m.changes.join('、')}</div>}
                    </div>
                  </div>
                )
            ))}
            {thinking && <div className="typing"><span>助手正在想</span><i /><i /><i /></div>}
            <div ref={chatEnd} />
          </div>
          <div className="chips chat__quick">
            {QUICK.map((q) => <button key={q} className="pill" disabled={thinking} onClick={() => void send(q)}>{q}</button>)}
          </div>
          <form className="chat__input" onSubmit={(e) => { e.preventDefault(); void send(draft) }}>
            <input value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="说说你的想法，比如：凶手是管家，但要让大家都怀疑女主人" disabled={thinking} />
            <button className="primary" disabled={!draft.trim() || thinking}>发送</button>
          </form>
        </div>
      </aside>

      {view && (
        <section className="gen2__progress card">
          <h4>生成进度 {view.jobId && <code>{view.jobId}</code>}</h4>
          <Timeline items={items} />
          {view.bundle && (
            <div className="gen__preview">
              <h4>bundle 预览</h4>
              <CoverCard bundle={view.bundle} compact />
              <p className="muted small">{view.bundle.characters.map((c) => `${c.name}${c.is_player ? '' : '（AI）'}`).join('、')}</p>
              <a className="primary" href="#play" onClick={(ev) => {
                const nb = view.bundle!
                const me = nb.characters.find((c) => c.is_player)?.id
                if (view.jobId?.startsWith('gen-') && me) {
                  // 真生成的本子已挂进本地剧本库：直接开一局
                  ev.preventDefault()
                  void startLive(nb.id, me).then(() => { location.hash = '#play' })
                } else if (nb.id !== handoff?.bundle.id) {
                  // 模拟生成：只换 bundle，进开场前状态
                  load({ bundle: nb, events: [], snapshot: null }, `生成：${nb.title}`)
                }
              }}>一键游玩</a>
            </div>
          )}
        </section>
      )}
    </div>
  )
}
