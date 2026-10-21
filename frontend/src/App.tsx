import { AudioLines, BookA, History, Mic } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { api, type Health, type HistoryItem, type Voice } from './api'
import { PreviewProvider } from './components/PreviewPlayer'
import ClonePage from './pages/ClonePage'
import DictionaryPage from './pages/DictionaryPage'
import HistoryPage from './pages/HistoryPage'
import StudioPage from './pages/StudioPage'

type Tab = 'studio' | 'clone' | 'history' | 'dictionary'

export default function App() {
  const [tab, setTab] = useState<Tab>('studio')
  const [health, setHealth] = useState<Health | null>(null)
  const [voices, setVoices] = useState<Voice[]>([])
  const [history, setHistory] = useState<HistoryItem[]>([])
  const ready = health?.status === 'ready'

  const loadVoices = useCallback(() => api.voices().then(setVoices).catch(() => {}), [])
  const loadHistory = useCallback(() => api.history().then(setHistory).catch(() => {}), [])

  useEffect(() => {
    let timer: number
    const poll = async () => {
      try {
        const h = await api.health()
        setHealth(h)
        if (h.status === 'ready') return loadVoices()
      } catch {
        setHealth(null)
      }
      timer = window.setTimeout(poll, 1500)
    }
    poll()
    loadHistory()
    return () => window.clearTimeout(timer)
  }, [loadVoices, loadHistory])

  const tabs: { id: Tab; label: string; icon: typeof Mic; badge?: number }[] = [
    { id: 'studio', label: 'Văn bản thành giọng nói', icon: AudioLines },
    { id: 'clone', label: 'Nhân bản giọng', icon: Mic },
    { id: 'history', label: 'Lịch sử', icon: History, badge: history.length },
    { id: 'dictionary', label: 'Từ điển', icon: BookA },
  ]

  return (
    <PreviewProvider>
      <div className="flex min-h-full flex-col">
        <header className="sticky top-0 z-20 border-b border-line bg-white/85 backdrop-blur">
          <div className="mx-auto flex max-w-[1400px] items-center gap-6 px-5 py-3">
            <div className="flex items-center gap-2.5">
              <img src="/favicon.svg" alt="" className="size-8" />
              <span className="text-[17px] font-bold tracking-tight">
                TIT <span className="text-brand-500">Voice</span> Studio
              </span>
            </div>
            <nav className="flex flex-1 items-center gap-1 overflow-x-auto [scrollbar-width:none]">
              {tabs.map(({ id, label, icon: Icon, badge }) => (
                <button
                  key={id}
                  onClick={() => setTab(id)}
                  className={`inline-flex shrink-0 items-center gap-2 rounded-full px-4 py-2 text-sm font-medium transition ${
                    tab === id ? 'bg-ink text-white' : 'text-muted hover:bg-canvas hover:text-ink'
                  }`}
                >
                  <Icon size={16} /> {label}
                  {!!badge && (
                    <span className={`rounded-full px-1.5 text-[11px] ${tab === id ? 'bg-white/20' : 'bg-canvas'}`}>{badge}</span>
                  )}
                </button>
              ))}
            </nav>
            <StatusPill health={health} />
          </div>
        </header>

        <main className="flex-1">
          {tab === 'studio' && (
            <StudioPage
              voices={voices}
              ready={ready}
              onCreated={(item) => setHistory((h) => [item, ...h])}
              onOpenDictionary={() => setTab('dictionary')}
            />
          )}
          {tab === 'clone' && (
            <ClonePage voices={voices} ready={ready} consentSentence={health?.consent_sentence ?? ''} onChange={loadVoices} />
          )}
          {tab === 'history' && <HistoryPage items={history} onChange={loadHistory} />}
          {tab === 'dictionary' && <DictionaryPage />}
        </main>
      </div>
    </PreviewProvider>
  )
}

function StatusPill({ health }: { health: Health | null }) {
  const [label, dot] = !health
    ? ['Mất kết nối backend', 'bg-red-500']
    : health.status === 'ready'
      ? [`Sẵn sàng · ${health.precision}`, 'bg-emerald-500']
      : health.status === 'loading'
        ? ['Đang nạp mô hình…', 'bg-amber-400 animate-pulse']
        : ['Mô hình lỗi', 'bg-red-500']
  return (
    <span className="hidden shrink-0 items-center gap-2 rounded-full border border-line px-3 py-1.5 text-xs font-medium text-muted md:inline-flex" title={health?.error ?? ''}>
      <span className={`size-2 rounded-full ${dot}`} /> {label}
    </span>
  )
}
