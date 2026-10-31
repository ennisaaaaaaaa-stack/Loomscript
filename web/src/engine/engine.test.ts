import { describe, expect, it } from 'vitest'
import full from '../../../bundles/macbeth_full.json'
import { advanceAct, Bundle, ContractError, drawCard, judgeEnding, opening, proposeClue, publicBundle, Session } from './engine'

// 与 src/server.py 对拍：同样的操作序列，事件类型与结局一致（对照录制见 fixtures/*.recorded.json）
describe('浏览器内引擎', () => {
  it('麦克白全本：走完五幕，班柯在 A3S2 死亡，结局 END03', () => {
    const s = new Session(new Bundle(full as never)).start()
    opening(s)
    for (const act of (full as { acts: { scenes: { scene_id: string }[] }[] }).acts) {
      for (const sc of act.scenes) { s.enterScene(sc.scene_id); s.fireReveals(sc.scene_id) }
      advanceAct(s)
    }
    const death = s.events.find((e) => e.type === 'death')
    expect(death).toMatchObject({ character_id: 'banquo', scene_id: 'A3S2' })
    expect(s.events.at(-1)).toMatchObject({ type: 'game_end', ending_id: 'END03' })
    expect(s.snapshot().character_states.banquo.alive).toBe(false)
    expect(s.events.map((e) => e.seq)).toEqual(s.events.map((_, i) => i))
  })

  it('死者不能在主频道说话；线索太早被拦、重复幂等；抽卡幂等', () => {
    const s = new Session(new Bundle(full as never)).start()
    expect(proposeClue(s, 'CL01')).toBeTruthy()
    expect(proposeClue(s, 'CL01')).toBeNull()
    expect(drawCard(s, 'CARD01')).toBeTruthy()
    expect(drawCard(s, 'CARD01')).toBeNull()
    s.enterScene('A1S1')
    while (s.s().act_id !== 'A3') advanceAct(s)
    s.enterScene('A3S2')
    expect(() => s.line('banquo', '我还在', 'main')).toThrow(ContractError)
    expect(() => s.line('banquo', '我在看', 'dm:banquo')).not.toThrow()
  })

  it('玩家视图只留本人秘密，剥掉演员包和预生成台词', () => {
    const v = publicBundle(full as never, 'macbeth')
    expect(v.actor_turns).toBeUndefined()
    expect(v.dm_lines).toBeUndefined()
    expect(v.characters.filter((c: { secret_sheet?: string }) => c.secret_sheet).map((c: { id: string }) => c.id)).toEqual(['macbeth'])
    expect(judgeEnding(new Session(new Bundle(full as never)).start())?.id).toBe('END03')
  })
})
