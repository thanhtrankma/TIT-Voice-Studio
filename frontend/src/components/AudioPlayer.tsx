import { Download, Pause, Play } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { audioUrl, type HistoryItem } from '../api'
import { VoiceAvatar } from './VoiceLibrary'

const BARS = 90

export function formatTime(s: number) {
  if (!Number.isFinite(s)) return '0:00'
  const m = Math.floor(s / 60)
  return `${m}:${String(Math.floor(s % 60)).padStart(2, '0')}`
}

async function loadPeaks(url: string): Promise<number[]> {
  const buf = await (await fetch(url)).arrayBuffer()
  const ctx = new AudioContext()
  try {
    const data = (await ctx.decodeAudioData(buf)).getChannelData(0)
    const step = Math.floor(data.length / BARS) || 1
    const peaks = Array.from({ length: BARS }, (_, i) => {
      let max = 0
      for (let j = i * step; j < Math.min((i + 1) * step, data.length); j += 16) max = Math.max(max, Math.abs(data[j]))
      return max
    })
    const top = Math.max(...peaks, 0.01)
    return peaks.map((p) => Math.max(0.06, p / top))
  } finally {
    ctx.close()
  }
}

export default function AudioPlayer({ item, autoPlay = false }: { item: HistoryItem; autoPlay?: boolean }) {
  const audio = useRef<HTMLAudioElement>(null)
  const [peaks, setPeaks] = useState<number[]>([])
  const [playing, setPlaying] = useState(false)
  const [time, setTime] = useState(0)
  const url = audioUrl(item.id)

  useEffect(() => {
    let alive = true
    setPeaks([])
    loadPeaks(url).then((p) => alive && setPeaks(p)).catch(() => {})
    return () => {
      alive = false
    }
  }, [url])

  useEffect(() => {
    if (autoPlay) audio.current?.play().catch(() => {})
  }, [url, autoPlay])

  const progress = item.duration ? time / item.duration : 0

  function seek(e: React.MouseEvent<HTMLDivElement>) {
    const rect = e.currentTarget.getBoundingClientRect()
    const ratio = (e.clientX - rect.left) / rect.width
    if (audio.current) audio.current.currentTime = ratio * item.duration
  }

  return (
    <div className="flex items-center gap-4">
      <audio
        ref={audio}
        src={url}
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={() => setPlaying(false)}
        onTimeUpdate={(e) => setTime(e.currentTarget.currentTime)}
      />
      <button
        onClick={() => (playing ? audio.current?.pause() : audio.current?.play())}
        className="btn-brand grid size-11 shrink-0 place-items-center rounded-full text-white"
        aria-label={playing ? 'Tạm dừng' : 'Phát'}
      >
        {playing ? <Pause size={18} fill="currentColor" /> : <Play size={18} fill="currentColor" className="ml-0.5" />}
      </button>
      <VoiceAvatar name={item.voice} size={32} />
      <div className="min-w-0 flex-1">
        <div className="flex h-10 cursor-pointer items-center gap-[2px]" onClick={seek}>
          {(peaks.length ? peaks : Array(BARS).fill(0.08)).map((p, i) => (
            <span
              key={i}
              className={`w-full rounded-full transition-colors ${i / BARS < progress ? 'bg-brand-500' : 'bg-zinc-200'}`}
              style={{ height: `${p * 100}%` }}
            />
          ))}
        </div>
      </div>
      <span className="w-20 shrink-0 text-right text-xs tabular-nums text-muted">
        {formatTime(time)} / {formatTime(item.duration)}
      </span>
      <div className="flex shrink-0 gap-1.5">
        {(['wav', 'mp3'] as const).map((f) => (
          <a
            key={f}
            href={audioUrl(item.id, f, true)}
            className="inline-flex items-center gap-1 rounded-lg border border-line px-2.5 py-1.5 text-xs font-medium hover:border-zinc-300 hover:bg-canvas"
          >
            <Download size={13} /> {f.toUpperCase()}
          </a>
        ))}
      </div>
    </div>
  )
}
