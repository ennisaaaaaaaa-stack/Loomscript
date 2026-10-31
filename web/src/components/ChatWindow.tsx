import { useEffect, useRef, useState, type ReactNode } from 'react'
import type { Bundle, GameEvent } from '../contract/types'
import { ChatItem } from './eventView'

/** 主聊天 / 私聊窗 / 复盘自由交流 / 发现推荐 共用 */
export function ChatWindow({ title, events, bundle, me, extra, input, onClose, className = '' }: {
  title: ReactNode
  events: GameEvent[]
  bundle: Bundle
  /** 我扮演的角色，决定哪些气泡靠右 */
  me?: string
  extra?: ReactNode
  input?: { placeholder: string; disabled?: boolean; onSend: (text: string) => void }
  onClose?: () => void
  className?: string
}) {
  const end = useRef<HTMLDivElement>(null)
  const [draft, setDraft] = useState('')
  useEffect(() => { end.current?.scrollIntoView({ block: 'end', behavior: 'smooth' }) }, [events.length, extra])
  return (
    <section className={`chat ${className}`}>
      <header className="chat__head">
        <span>{title}</span>
        {onClose && <button className="ghost" onClick={onClose} aria-label="关闭">×</button>}
      </header>
      <div className="chat__flow">
        {events.map((e) => <ChatItem key={e.seq} e={e} b={bundle} me={me} />)}
        {extra}
        <div ref={end} />
      </div>
      {input && (
        <form
          className="chat__input"
          onSubmit={(ev) => { ev.preventDefault(); if (draft.trim()) { input.onSend(draft.trim()); setDraft('') } }}
        >
          <input value={draft} onChange={(e) => setDraft(e.target.value)} placeholder={input.placeholder} disabled={input.disabled} />
          <button disabled={input.disabled || !draft.trim()}>发送</button>
        </form>
      )}
    </section>
  )
}
