import { useEffect, useState } from 'react'
import './ReviewWorkflow.css'

const scenes = [
  { title: 'Add brand guidelines', description: 'Upload approved guidelines and facts in Brand Knowledge.', image: 'workflow-guidelines-v2.png', destination: 'Brand Knowledge upload' },
  { title: 'Add your content', description: 'Paste text or upload an image or PDF in New Review.', image: 'workflow-content-v2.png', destination: 'New Review' },
  { title: 'Let the review run', description: 'Your content is checked against available guidance and evidence.', image: 'workflow-review-v2.png', destination: 'Review Library' },
  { title: 'Review suggested changes', description: 'Compare wording, open sources, and accept or edit suggestions.', image: 'workflow-results-v2.png', destination: 'Review Library' },
] as const

function Scene({ scene, active, onClick, onInteraction }: { scene: typeof scenes[number]; active: boolean; onClick: () => void; onInteraction: (value: boolean) => void }) {
  return <button type="button" className="workflow-scene" data-active={active} onClick={onClick}
    onPointerEnter={() => onInteraction(true)} onPointerLeave={() => onInteraction(false)}
    onFocus={() => onInteraction(true)} onBlur={() => onInteraction(false)}
    aria-label={`${scene.title}. Opens ${scene.destination}.`}>
    <span className="workflow-art" aria-hidden="true"><img src={`${import.meta.env.BASE_URL}assets/${scene.image}`} alt="" /></span>
    <span className="workflow-copy"><span className="workflow-card-title">{scene.title}</span><span className="workflow-description">{scene.description}</span>{scene.destination === 'Review Library' && <span className="workflow-destination">Open Review Library</span>}</span>
  </button>
}

export default function ReviewWorkflow({ onGuidelines, onContent, onLibrary }: { onGuidelines: () => void; onContent: () => void; onLibrary: () => void }) {
  const [paused, setPaused] = useState(false)
  const [hidden, setHidden] = useState(() => document.hidden)
  const [active, setActive] = useState(0)
  const [interacting, setInteracting] = useState(false)
  useEffect(() => {
    const update = () => setHidden(document.hidden)
    document.addEventListener('visibilitychange', update)
    return () => document.removeEventListener('visibilitychange', update)
  }, [])
  useEffect(() => {
    if (paused || hidden || interacting) return
    const timer = window.setInterval(() => setActive(value => (value + 1) % scenes.length), 3000)
    return () => window.clearInterval(timer)
  }, [paused, hidden, interacting])

  return <section className="panel workflow" aria-labelledby="workflow-title" data-paused={paused || hidden || interacting}>
    <div className="workflow-heading"><div><span className="workflow-label">Illustrative workflow</span><h2 id="workflow-title">How your review works</h2></div><button className="workflow-pause" type="button" onClick={() => setPaused(value => !value)} aria-label={paused ? 'Resume workflow animation' : 'Pause workflow animation'}>{paused ? '▶ Resume' : 'Ⅱ Pause'}</button></div>
    <div className="workflow-window"><div className="workflow-track">{scenes.map((scene, index) => <Scene key={scene.image} scene={scene} active={active === index} onClick={[onGuidelines, onContent, onLibrary, onLibrary][index]} onInteraction={setInteracting}/>)}</div></div>
  </section>
}
