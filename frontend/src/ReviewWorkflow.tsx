import { useEffect, useState } from 'react'
import './ReviewWorkflow.css'

const captions = ['Add your content', 'Check against guidance', 'Review suggested changes'] as const

function Scene({ kind, active }: { kind: 0 | 1 | 2; active: boolean }) {
  return <div className={`workflow-scene workflow-scene-${kind}`} data-active={active}>
    <div className="workflow-copy"><span className="workflow-number">0{kind + 1} / 03</span><h3>{captions[kind]}</h3></div>
    <div className="workflow-art" aria-hidden="true">
      {kind === 0 && <><div className="workflow-document upload-document"><span/><span/><span/></div><div className="workflow-tray"><span>↑</span></div></>}
      {kind === 1 && <><div className="workflow-document review-document"><span/><span className="highlight"/><span/></div><div className="workflow-connector"/><div className="workflow-guidance"><strong>Guideline</strong><span>Use clear language</span><i/><i/></div></>}
      {kind === 2 && <div className="workflow-result"><div><small>Original</small><span>Original wording</span></div><div><small>Suggested</small><span>Revised wording</span></div><footer><span>ⓘ Source</span><span>◉ Human review</span></footer></div>}
    </div>
  </div>
}

export default function ReviewWorkflow() {
  const [paused, setPaused] = useState(false)
  const [hidden, setHidden] = useState(() => document.hidden)
  const [active, setActive] = useState(0)
  useEffect(() => {
    const update = () => setHidden(document.hidden)
    document.addEventListener('visibilitychange', update)
    return () => document.removeEventListener('visibilitychange', update)
  }, [])
  useEffect(() => {
    if (paused || hidden) return
    const timer = window.setInterval(() => setActive(value => (value + 1) % 3), 3000)
    return () => window.clearInterval(timer)
  }, [paused, hidden])

  return <section className="panel workflow" aria-labelledby="workflow-title" data-paused={paused || hidden}>
    <div className="workflow-heading"><div><span className="workflow-label">Illustrative workflow</span><h2 id="workflow-title">How your review works</h2></div><button className="workflow-pause" type="button" onClick={() => setPaused(value => !value)} aria-label={paused ? 'Resume workflow animation' : 'Pause workflow animation'}>{paused ? '▶ Resume' : 'Ⅱ Pause'}</button></div>
    <div className="workflow-window"><div className="workflow-track"><Scene kind={0} active={active === 0}/><Scene kind={1} active={active === 1}/><Scene kind={2} active={active === 2}/></div></div>
  </section>
}
