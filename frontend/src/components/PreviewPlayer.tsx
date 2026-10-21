import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react'
import { fetchPreview } from '../api'

type State = { voice: string | null; loading: boolean }
type Ctx = State & { toggle: (voice: string) => void; stop: () => void }

const PreviewContext = createContext<Ctx | null>(null)

/** Một trình phát dùng chung cho mọi nút nghe thử giọng: bấm giọng khác thì giọng cũ dừng. */
export function PreviewProvider({ children }: { children: ReactNode }) {
  const audio = useRef<HTMLAudioElement>(new Audio())
  const [state, setState] = useState<State>({ voice: null, loading: false })
  const current = useRef<string | null>(null)

  useEffect(() => {
    const el = audio.current
    const ended = () => {
      current.current = null
      setState({ voice: null, loading: false })
    }
    el.addEventListener('ended', ended)
    return () => el.removeEventListener('ended', ended)
  }, [])

  const stop = useCallback(() => {
    audio.current.pause()
    current.current = null
    setState({ voice: null, loading: false })
  }, [])

  const toggle = useCallback(
    async (voice: string) => {
      if (current.current === voice) return stop()
      audio.current.pause()
      current.current = voice
      setState({ voice, loading: true })
      try {
        const url = await fetchPreview(voice)
        if (current.current !== voice) return
        audio.current.src = url
        await audio.current.play()
        setState({ voice, loading: false })
      } catch {
        if (current.current === voice) stop()
      }
    },
    [stop],
  )

  return <PreviewContext.Provider value={{ ...state, toggle, stop }}>{children}</PreviewContext.Provider>
}

export function usePreview() {
  const ctx = useContext(PreviewContext)
  if (!ctx) throw new Error('usePreview cần PreviewProvider')
  return ctx
}
