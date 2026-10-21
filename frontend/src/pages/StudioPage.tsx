import { BookA, ChevronDown, Eraser, Gauge, Loader2, Sparkles, Wand2 } from 'lucide-react'
import { useRef, useState } from 'react'
import { api, waitForJob, type HistoryItem, type Voice } from '../api'
import AudioPlayer from '../components/AudioPlayer'
import TagEditor, { type TagEditorHandle } from '../components/TagEditor'
import VoiceLibrary, { VoiceAvatar } from '../components/VoiceLibrary'
import { EMOTION_VALUES, TAG_STYLES } from '../lib/tags'

const SAMPLES: { label: string; text: string }[] = [
  {
    label: 'Cảm xúc',
    text: 'Trời ơi, mình không tin được là mình vừa đạt giải nhất! [cười] Hôm nay đúng là ngày vui nhất đời mình.\n[nghỉ 1s] Nhưng nghĩ đến việc phải chuyển đi xa, rời xa mọi người… [thở dài] lòng mình lại thấy buồn.',
  },
  {
    label: 'Tin tức',
    text: 'Chào mừng quý vị đến với bản tin sáng nay. Theo Trung tâm Dự báo Khí tượng Thủy văn Quốc gia, khu vực Hà Nội hôm nay có nắng, nhiệt độ cao nhất khoảng ba mươi hai độ.',
  },
  {
    label: 'Kể chuyện',
    text: 'Ngày xửa ngày xưa, ở một ngôi làng nhỏ ven sông, có một cậu bé tên là An. [nghỉ 500ms] Mỗi sáng, An đều ra bờ sông ngắm những cánh buồm trắng và mơ về những vùng đất xa xôi.',
  },
  {
    label: 'Quảng cáo',
    text: 'Bạn đang tìm một giọng đọc tự nhiên cho video của mình? [hắng giọng] Chỉ với vài cú nhấp chuột, văn bản của bạn sẽ thành giọng nói sống động, chạy ngay trên máy tính, không cần Internet!',
  },
]

const PAUSES = ['500ms', '1s', '2s', '3s']

type Props = {
  voices: Voice[]
  ready: boolean
  onCreated: (item: HistoryItem) => void
  onOpenDictionary: () => void
}

export default function StudioPage({ voices, ready, onCreated, onOpenDictionary }: Props) {
  const editor = useRef<TagEditorHandle>(null)
  const [text, setText] = useState(SAMPLES[0].text)
  const [voice, setVoice] = useState<string | null>(null)
  const [speed, setSpeed] = useState(1)
  const [pauseOpen, setPauseOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [progress, setProgress] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<HistoryItem | null>(null)

  const selectedVoice = voices.find((v) => v.id === voice) ?? voices[0]
  const chars = text.replace(/\[[^\]]*\]/g, '').trim().length

  async function generate() {
    if (!selectedVoice || !chars || busy) return
    setBusy(true)
    setError(null)
    setProgress(0)
    try {
      const { job_id } = await api.tts({ text, voice: selectedVoice.id, speed })
      const item = await waitForJob<HistoryItem>(job_id, (j) => setProgress(j.progress))
      setResult(item)
      onCreated(item)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mx-auto grid h-full max-w-[1400px] grid-cols-1 gap-5 p-5 lg:grid-cols-[minmax(0,1fr)_400px]">
      {/* Ô soạn thảo */}
      <section className="flex min-h-[520px] flex-col overflow-hidden rounded-3xl border border-line bg-white shadow-[0_1px_2px_rgb(0_0_0/0.03)]">
        <div className="flex items-center justify-between gap-3 border-b border-line px-6 py-3.5">
          <div className="flex items-center gap-2 text-sm text-muted">
            <span className="font-medium text-ink">Văn bản</span>
            <span>·</span>
            <span>VieNeu-TTS v3 Turbo</span>
          </div>
          <div className="flex items-center gap-1">
            <button
              onClick={onOpenDictionary}
              className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-sm text-muted hover:bg-canvas hover:text-ink"
            >
              <BookA size={15} /> Từ điển
            </button>
            <button
              onClick={() => editor.current?.clear()}
              className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-sm text-muted hover:bg-canvas hover:text-ink"
            >
              <Eraser size={15} /> Xoá
            </button>
          </div>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
          <TagEditor ref={editor} initialText={SAMPLES[0].text} onChange={setText} />
        </div>

        {/* Thanh chèn cảm xúc */}
        <div className="border-t border-line px-6 py-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="mr-1 inline-flex items-center gap-1.5 text-xs font-medium text-muted">
              <Sparkles size={14} className="text-brand-500" /> Chèn cảm xúc
            </span>
            {(Object.keys(EMOTION_VALUES) as (keyof typeof EMOTION_VALUES)[]).map((k) => (
              <button
                key={k}
                onClick={() => editor.current?.insertTag(EMOTION_VALUES[k])}
                className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-sm font-medium ring-1 transition hover:-translate-y-px hover:shadow-sm ${TAG_STYLES[k].className}`}
              >
                <span aria-hidden>{TAG_STYLES[k].emoji}</span>
                {TAG_STYLES[k].label}
              </button>
            ))}
            <div className="relative">
              <button
                onClick={() => setPauseOpen((o) => !o)}
                className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-sm font-medium ring-1 transition hover:-translate-y-px hover:shadow-sm ${TAG_STYLES.pause.className}`}
              >
                <span aria-hidden>{TAG_STYLES.pause.emoji}</span> Nghỉ <ChevronDown size={13} />
              </button>
              {pauseOpen && (
                <div className="absolute bottom-full left-0 z-10 mb-2 flex gap-1 rounded-xl border border-line bg-white p-1 shadow-lg">
                  {PAUSES.map((p) => (
                    <button
                      key={p}
                      onClick={() => {
                        editor.current?.insertTag(`nghỉ ${p}`)
                        setPauseOpen(false)
                      }}
                      className="rounded-lg px-2.5 py-1 text-sm hover:bg-canvas"
                    >
                      {p}
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line bg-canvas/60 px-6 py-3">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="mr-1 text-xs text-muted">Mẫu:</span>
            {SAMPLES.map((s) => (
              <button
                key={s.label}
                onClick={() => editor.current?.setText(s.text)}
                className="rounded-full border border-line bg-white px-3 py-1 text-xs font-medium text-ink hover:border-zinc-300"
              >
                {s.label}
              </button>
            ))}
          </div>
          <span className="text-xs tabular-nums text-muted">
            {chars.toLocaleString('vi-VN')} ký tự · ~{Math.max(1, Math.round(chars / 15 / speed))}s audio
          </span>
        </div>
      </section>

      {/* Cột phải: giọng + tốc độ + nút tạo */}
      <aside className="flex min-h-[520px] flex-col overflow-hidden rounded-3xl border border-line bg-white lg:max-h-[calc(100vh-170px)]">
        <div className="flex items-center justify-between px-5 pt-5 pb-3">
          <h2 className="text-base font-semibold">Thư viện giọng</h2>
          <span className="rounded-full bg-canvas px-2 py-0.5 text-xs text-muted">{voices.length} giọng</span>
        </div>
        <VoiceLibrary voices={voices} selected={selectedVoice?.id ?? null} onSelect={setVoice} />

        <div className="space-y-4 border-t border-line p-5">
          <div>
            <div className="mb-2 flex items-center justify-between text-sm">
              <span className="inline-flex items-center gap-1.5 font-medium">
                <Gauge size={15} className="text-muted" /> Tốc độ
              </span>
              <button
                onClick={() => setSpeed(1)}
                className="rounded-md bg-canvas px-2 py-0.5 text-xs tabular-nums font-semibold text-ink"
                title="Về 1.0x"
              >
                {speed.toFixed(2)}x
              </button>
            </div>
            <input
              type="range"
              min={0.75}
              max={1.5}
              step={0.05}
              value={speed}
              onChange={(e) => setSpeed(Number(e.target.value))}
              className="speed w-full"
              aria-label="Tốc độ đọc"
            />
            <div className="mt-1 flex justify-between text-[11px] text-muted">
              <span>Chậm</span>
              <span>Nhanh</span>
            </div>
          </div>

          <button
            onClick={generate}
            disabled={!ready || busy || !chars || !selectedVoice}
            className="btn-brand relative flex w-full items-center justify-center gap-2 overflow-hidden rounded-2xl py-3.5 font-semibold text-white transition hover:brightness-105 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {busy && (
              <span
                className="absolute inset-y-0 left-0 bg-white/20 transition-[width] duration-500"
                style={{ width: `${Math.round(progress * 100)}%` }}
              />
            )}
            {busy ? <Loader2 size={18} className="animate-spin" /> : <Wand2 size={18} />}
            <span className="relative">
              {busy ? `Đang tạo… ${Math.round(progress * 100)}%` : ready ? 'Tạo giọng nói' : 'Đang nạp mô hình…'}
            </span>
          </button>
          {selectedVoice && (
            <div className="flex items-center justify-center gap-2 text-xs text-muted">
              <VoiceAvatar name={selectedVoice.name} size={18} /> Giọng {selectedVoice.name}
            </div>
          )}
          {error && <p className="rounded-xl bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
        </div>
      </aside>

      {result && (
        <div className="sticky bottom-4 rounded-3xl border border-line bg-white/95 p-4 shadow-[0_12px_40px_-16px_rgb(0_0_0/0.25)] backdrop-blur lg:col-span-2">
          <AudioPlayer item={result} autoPlay />
        </div>
      )}
    </div>
  )
}
