import { Loader2, Music, Pause, Play, Trash2, Upload } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { api, musicUrl, type MusicItem } from '../api'

type Props = {
  value: string | null
  onChange: (id: string | null) => void
  volume: number
  onVolume: (v: number) => void
}

/** Chọn nhạc nền: bản có sẵn hoặc nhạc tự tải lên, nghe thử, chỉnh âm lượng. */
export default function MusicPicker({ value, onChange, volume, onVolume }: Props) {
  const [items, setItems] = useState<MusicItem[]>([])
  const [playing, setPlaying] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const audio = useRef<HTMLAudioElement | null>(null)
  const file = useRef<HTMLInputElement>(null)
  const current = items.find((m) => m.id === value) ?? null

  useEffect(() => {
    api.music().then(setItems).catch(() => {})
  }, [])

  useEffect(() => {
    if (audio.current) audio.current.volume = Math.min(1, volume)
  }, [volume])

  // đổi bài hoặc tắt nhạc thì dừng bản đang nghe thử
  function select(id: string | null) {
    audio.current?.pause()
    setPlaying(false)
    onChange(id)
  }

  function toggle() {
    const a = audio.current
    if (!value || !a) return
    if (playing) {
      a.pause()
      setPlaying(false)
      return
    }
    a.volume = Math.min(1, volume)
    a.play().then(() => setPlaying(true)).catch(() => setError('Không phát được bản nhạc này.'))
  }

  async function upload(f: File) {
    setBusy(true)
    setError(null)
    try {
      const item = await api.uploadMusic(f)
      setItems((l) => [...l.filter((m) => m.builtin), item, ...l.filter((m) => !m.builtin)])
      select(item.id)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
      if (file.current) file.current.value = ''
    }
  }

  async function remove() {
    if (!current || current.builtin || !confirm(`Xoá “${current.name}” khỏi thư viện nhạc?`)) return
    await api.deleteMusic(current.id)
    setItems((l) => l.filter((m) => m.id !== current.id))
    select(null)
  }

  const iconBtn =
    'grid size-8 shrink-0 place-items-center rounded-lg border border-line text-muted transition hover:border-zinc-300 hover:text-ink disabled:opacity-50'

  return (
    <div className="space-y-2">
      {/* nghe thử: lặp, dừng khi rời trang vì thẻ bị gỡ */}
      <audio ref={audio} src={value ? musicUrl(value) : undefined} loop preload="none" onPause={() => setPlaying(false)} />
      <div className="flex items-center gap-2">
        <label className="flex min-w-0 flex-1 items-center gap-2 rounded-lg border border-line bg-canvas px-2 focus-within:border-brand-400">
          <Music size={15} className="shrink-0 text-muted" />
          <select
            value={value ?? ''}
            onChange={(e) => select(e.target.value || null)}
            className="min-w-0 flex-1 bg-transparent py-1.5 text-sm outline-none"
            aria-label="Nhạc nền"
          >
            <option value="">Không có nhạc nền</option>
            <optgroup label="Có sẵn">
              {items.filter((m) => m.builtin).map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name}
                </option>
              ))}
            </optgroup>
            {items.some((m) => !m.builtin) && (
              <optgroup label="Nhạc của bạn">
                {items.filter((m) => !m.builtin).map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name}
                  </option>
                ))}
              </optgroup>
            )}
          </select>
        </label>
        <button onClick={toggle} disabled={!value} className={iconBtn} aria-label={playing ? 'Dừng nghe thử' : 'Nghe thử nhạc'} title={playing ? 'Dừng' : 'Nghe thử'}>
          {playing ? <Pause size={14} /> : <Play size={14} />}
        </button>
        {current && !current.builtin && (
          <button onClick={remove} className={`${iconBtn} hover:bg-red-50 hover:text-red-600`} aria-label="Xoá bản nhạc" title="Xoá bản nhạc">
            <Trash2 size={14} />
          </button>
        )}
        <button
          onClick={() => file.current?.click()}
          disabled={busy}
          className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-line px-2.5 py-1.5 text-sm font-medium text-ink hover:border-zinc-300 hover:bg-canvas disabled:opacity-60"
        >
          {busy ? <Loader2 size={14} className="animate-spin" /> : <Upload size={14} />} Tải nhạc lên
        </button>
        <input
          ref={file}
          type="file"
          accept="audio/*,video/*"
          className="hidden"
          onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])}
        />
      </div>
      {value && (
        <div className="flex items-center gap-3">
          <span className="shrink-0 text-xs text-muted">Âm lượng</span>
          <input
            type="range"
            min={0.05}
            max={1}
            step={0.05}
            value={volume}
            onChange={(e) => onVolume(Number(e.target.value))}
            className="speed min-w-0 flex-1"
            aria-label="Âm lượng nhạc nền"
          />
          <span className="w-10 shrink-0 text-right text-xs font-semibold tabular-nums">{Math.round(volume * 100)}%</span>
        </div>
      )}
      <p className="text-xs leading-relaxed text-muted">
        {value
          ? 'Nhạc lặp suốt video, tự nhỏ đi khi có giọng đọc. Nhạc tải lên phải là nhạc bạn có quyền dùng, YouTube có thể chặn nhạc có bản quyền.'
          : 'Bản có sẵn do app tự tạo, dùng thoải mái. Có thể tải lên MP3, M4A, WAV (tối đa 80 MB).'}
      </p>
      {error && <p className="rounded-lg bg-red-50 px-2 py-1 text-xs text-red-700">{error}</p>}
    </div>
  )
}
