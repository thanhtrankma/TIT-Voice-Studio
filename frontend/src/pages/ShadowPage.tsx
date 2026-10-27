import { Captions, Clapperboard, Download, Eraser, ExternalLink, Film, Loader2, Music, Trash2, Upload } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { api, shadowUrl, waitForJob, type EnglishStatus, type ShadowLesson, type ShadowRequest, type Voice } from '../api'
import { formatTime } from '../components/AudioPlayer'
import Segmented from '../components/Segmented'
import VoiceLibrary, { VoiceAvatar } from '../components/VoiceLibrary'
import YouTubePublish from '../components/YouTubePublish'

const SAMPLES: { label: string; title: string; text: string }[] = [
  {
    label: 'Giao tiếp hằng ngày',
    title: 'Giao tiếp hằng ngày',
    text: [
      'Good morning! How are you doing today? | Chào buổi sáng! Hôm nay bạn thế nào?',
      "I'm doing great, thanks for asking. | Mình khoẻ lắm, cảm ơn bạn đã hỏi.",
      'I usually take the bus to work, but today I decided to walk. | Mình thường đi xe buýt đi làm, nhưng hôm nay mình quyết định đi bộ.',
      'Could you tell me where the nearest coffee shop is? | Bạn chỉ giúp mình quán cà phê gần nhất ở đâu được không?',
      "Actually, I think I'd rather have a cup of tea. | Thật ra, mình nghĩ mình muốn uống một tách trà hơn.",
    ].join('\n'),
  },
  {
    label: 'Phỏng vấn xin việc',
    title: 'Phỏng vấn xin việc',
    text: [
      'Thank you for inviting me to this interview. | Cảm ơn anh chị đã mời tôi đến buổi phỏng vấn này.',
      'I have three years of experience in customer service. | Tôi có ba năm kinh nghiệm chăm sóc khách hàng.',
      'I enjoy solving problems and working with a team. | Tôi thích giải quyết vấn đề và làm việc nhóm.',
      'My greatest strength is that I learn new things quickly. | Điểm mạnh lớn nhất của tôi là học điều mới rất nhanh.',
      'Could you tell me more about the daily responsibilities of this role? | Anh chị có thể nói thêm về công việc hằng ngày của vị trí này không?',
    ].join('\n'),
  },
  {
    label: 'Du lịch',
    title: 'Ở sân bay và khách sạn',
    text: [
      "Excuse me, where can I check in for my flight? | Xin lỗi, tôi làm thủ tục cho chuyến bay ở đâu?",
      'I would like a window seat, please. | Làm ơn cho tôi ghế cạnh cửa sổ.',
      'How long does it take to get to the city center? | Đi vào trung tâm thành phố mất bao lâu?',
      'I have a reservation under the name Nguyen. | Tôi đã đặt phòng dưới tên Nguyễn.',
      'What time is breakfast served? | Bữa sáng được phục vụ lúc mấy giờ?',
    ].join('\n'),
  },
]

const REPEATS = [1, 2, 3]
const SLOW = [
  { value: 1, label: 'Tắt' },
  { value: 0.7, label: '0.7x' },
  { value: 0.8, label: '0.8x' },
  { value: 0.9, label: '0.9x' },
]
type VoiceSource = 'native' | 'vieneu'
const SOURCES: { value: VoiceSource; label: string }[] = [
  { value: 'native', label: 'Bản xứ Mỹ/Anh' },
  { value: 'vieneu', label: 'Giọng VieNeu' },
]
const DEFAULT_VOICE: Record<VoiceSource, string> = { native: 'kokoro:af_heart', vieneu: 'Adam' }
const ASPECTS: { value: ShadowRequest['aspect']; label: string }[] = [
  { value: '16:9', label: 'Ngang 16:9' },
  { value: '9:16', label: 'Dọc 9:16' },
]

/** Đếm câu giống backend (app/shadow.py: parse_lesson) để ước lượng trước khi tạo. */
function lessonLines(text: string): string[] {
  return text.split('\n').flatMap((raw) => {
    const [en, ...vi] = raw.split('|')
    const sentence = en.trim()
    if (!sentence) return []
    if (vi.join('|').trim()) return [sentence]
    return sentence.split(/(?<=[.!?])\s+(?=["'“(]?[A-Z0-9])/).filter((s) => s.trim())
  })
}

/** Ước lượng độ dài video: mô hình đọc tiếng Anh khoảng 18 ký tự mỗi giây. */
function estimate(lines: string[], s: Pick<ShadowRequest, 'repeats' | 'slow_speed' | 'gap_factor' | 'full_run'>) {
  let total = 5
  for (const line of lines) {
    const d = Math.max(0.8, line.length / 18)
    const gap = Math.max(1.5, d * s.gap_factor)
    total += s.repeats * (d + gap + (s.slow_speed < 0.99 ? (d + gap) / s.slow_speed : 0))
    if (s.full_run) total += d + 0.35
  }
  return total
}

type Props = { voices: Voice[]; ready: boolean }

export default function ShadowPage({ voices, ready }: Props) {
  const [title, setTitle] = useState(SAMPLES[0].title)
  const [text, setText] = useState(SAMPLES[0].text)
  const [source, setSource] = useState<VoiceSource>('native')
  const [english, setEnglish] = useState<EnglishStatus | null>(null)
  const [voice, setVoice] = useState<string | null>(null)
  const [repeats, setRepeats] = useState(1)
  const [slowSpeed, setSlowSpeed] = useState(0.8)
  const [gapFactor, setGapFactor] = useState(1.3)
  const [fullRun, setFullRun] = useState(true)
  const [aspect, setAspect] = useState<ShadowRequest['aspect']>('16:9')
  const [busy, setBusy] = useState(false)
  const [progress, setProgress] = useState(0)
  const [stage, setStage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [lessons, setLessons] = useState<ShadowLesson[]>([])
  const [current, setCurrent] = useState<ShadowLesson | null>(null)
  const [publishing, setPublishing] = useState(false)

  const list = source === 'native' ? (english?.voices ?? []) : voices
  const selectedVoice = list.find((v) => v.id === voice) ?? list.find((v) => v.id === DEFAULT_VOICE[source]) ?? list[0]
  const lines = useMemo(() => lessonLines(text), [text])
  const settings = { repeats, slow_speed: slowSpeed, gap_factor: gapFactor, full_run: fullRun }
  const seconds = lines.length ? estimate(lines, settings) : 0

  useEffect(() => {
    api.shadowLessons().then(setLessons).catch(() => {})
    api.english().then(setEnglish).catch(() => {})
  }, [])

  async function generate() {
    if (!selectedVoice || !lines.length || busy) return
    setBusy(true)
    setError(null)
    setProgress(0)
    setStage(null)
    try {
      const { job_id } = await api.shadow({ text, title, voice: selectedVoice.id, aspect, ...settings })
      const lesson = await waitForJob<ShadowLesson>(job_id, (j) => {
        setProgress(j.progress)
        setStage(j.stage)
      })
      setLessons((l) => [lesson, ...l])
      open(lesson)
      if (source === 'native' && !english?.installed) api.english().then(setEnglish).catch(() => {})
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  function open(lesson: ShadowLesson) {
    setCurrent(lesson)
    setPublishing(false)
  }

  function published(id: string, url: string) {
    setLessons((l) => l.map((x) => (x.id === id ? { ...x, youtube_url: url } : x)))
    setCurrent((c) => (c?.id === id ? { ...c, youtube_url: url } : c))
  }

  async function remove(id: string) {
    if (!confirm('Xoá bài luyện này? Video, MP3 và phụ đề cũng bị xoá.')) return
    await api.deleteShadow(id)
    setLessons((l) => l.filter((x) => x.id !== id))
    if (current?.id === id) setCurrent(null)
  }

  const phase =
    stage ??
    (progress < 0.85
      ? `Đang đọc câu ${Math.min(lines.length, Math.floor((progress / 0.85) * lines.length) + 1)}/${lines.length}…`
      : 'Đang dựng video…')

  return (
    <div className="mx-auto grid h-full max-w-[1400px] grid-cols-1 gap-5 p-5 lg:grid-cols-[minmax(0,1fr)_400px]">
      {/* Bài luyện + cách luyện */}
      <section className="flex min-h-[520px] flex-col overflow-hidden rounded-3xl border border-line bg-white shadow-[0_1px_2px_rgb(0_0_0/0.03)]">
        <div className="flex items-center justify-between gap-3 border-b border-line px-6 py-3.5">
          <div className="flex items-center gap-2 text-sm text-muted">
            <span className="font-medium text-ink">Bài luyện</span>
            <span>·</span>
            <span>Mỗi dòng một câu, thêm nghĩa sau dấu |</span>
          </div>
          <button
            onClick={() => setText('')}
            className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-sm text-muted hover:bg-canvas hover:text-ink"
          >
            <Eraser size={15} /> Xoá
          </button>
        </div>

        <div className="flex flex-1 flex-col gap-3 px-6 py-5">
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            maxLength={80}
            placeholder="Tên bài (tuỳ chọn)"
            className="w-full rounded-xl border border-line bg-canvas px-3 py-2 text-sm font-medium outline-none placeholder:text-zinc-400 focus:border-brand-400 focus:bg-white"
          />
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            spellCheck={false}
            placeholder={'Good morning! How are you? | Chào buổi sáng! Bạn khoẻ không?\nI usually take the bus to work.'}
            className="min-h-[260px] w-full flex-1 resize-none bg-transparent text-[16px] leading-8 outline-none placeholder:text-zinc-400"
          />
        </div>

        <div className="grid gap-4 border-t border-line px-6 py-4 sm:grid-cols-2">
          <Field label="Lặp mỗi câu">
            <Segmented options={REPEATS.map((r) => ({ value: r, label: `${r} lần` }))} value={repeats} onChange={setRepeats} />
          </Field>
          <Field label="Nghe chậm sau mỗi lượt">
            <Segmented options={SLOW} value={slowSpeed} onChange={setSlowSpeed} />
          </Field>
          <Field
            label="Thời gian để bạn nói"
            hint={
              <button onClick={() => setGapFactor(1.3)} className="rounded-md bg-canvas px-2 py-0.5 text-xs font-semibold tabular-nums text-ink" title="Về ×1.3">
                ×{gapFactor.toFixed(1)} độ dài câu
              </button>
            }
          >
            <input
              type="range"
              min={0.8}
              max={2.5}
              step={0.1}
              value={gapFactor}
              onChange={(e) => setGapFactor(Number(e.target.value))}
              className="speed w-full"
              aria-label="Thời gian để bạn nói"
            />
          </Field>
          <Field label="Khung hình">
            <Segmented options={ASPECTS} value={aspect} onChange={setAspect} />
          </Field>
          <label className="flex cursor-pointer items-center gap-2.5 text-sm sm:col-span-2">
            <input
              type="checkbox"
              checked={fullRun}
              onChange={(e) => setFullRun(e.target.checked)}
              className="size-4 accent-[var(--color-brand-500)]"
            />
            <span>
              <span className="font-medium">Lượt shadowing liền mạch cuối bài</span>
              <span className="text-muted"> · đọc cả bài không nghỉ để bạn nói cùng lúc</span>
            </span>
          </label>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line bg-canvas/60 px-6 py-3">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="mr-1 text-xs text-muted">Mẫu:</span>
            {SAMPLES.map((s) => (
              <button
                key={s.label}
                onClick={() => {
                  setText(s.text)
                  setTitle(s.title)
                }}
                className="rounded-full border border-line bg-white px-3 py-1 text-xs font-medium text-ink hover:border-zinc-300"
              >
                {s.label}
              </button>
            ))}
          </div>
          <span className="text-xs tabular-nums text-muted">
            {lines.length} câu · video ~{formatTime(seconds)}
          </span>
        </div>
      </section>

      {/* Cột phải: giọng + nút tạo */}
      <aside className="flex min-h-[520px] flex-col overflow-hidden rounded-3xl border border-line bg-white lg:max-h-[calc(100vh-170px)]">
        <div className="flex items-center justify-between px-5 pt-5 pb-3">
          <h2 className="text-base font-semibold">Giọng đọc mẫu</h2>
          <span className="rounded-full bg-canvas px-2 py-0.5 text-xs text-muted">{list.length} giọng</span>
        </div>
        <div className="px-5 pb-3">
          <Segmented options={SOURCES} value={source} onChange={setSource} />
          <p className="mt-2 text-xs leading-relaxed text-muted">
            {source === 'native'
              ? english && !english.installed
                ? `Giọng người bản xứ, tô sáng đúng từng từ. Lần đầu dùng sẽ tải khoảng ${english.download_mb} MB.`
                : 'Giọng người bản xứ, tô sáng đúng từng từ đang đọc.'
              : 'Giọng tiếng Việt đọc tiếng Anh, có thể đọc sai câu khó. Hợp để nghe giọng Việt quen thuộc.'}
          </p>
        </div>
        <VoiceLibrary key={source} voices={list} selected={selectedVoice?.id ?? null} onSelect={setVoice} />

        <div className="space-y-3 border-t border-line p-5">
          <button
            onClick={generate}
            disabled={!ready || busy || !lines.length || !selectedVoice}
            className="btn-brand relative flex w-full items-center justify-center gap-2 overflow-hidden rounded-2xl py-3.5 font-semibold text-white transition hover:brightness-105 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {busy && (
              <span
                className="absolute inset-y-0 left-0 bg-white/20 transition-[width] duration-500"
                style={{ width: `${Math.round(progress * 100)}%` }}
              />
            )}
            {busy ? <Loader2 size={18} className="animate-spin" /> : <Clapperboard size={18} />}
            <span className="relative">
              {busy ? `${phase} ${Math.round(progress * 100)}%` : ready ? 'Tạo video luyện' : 'Đang nạp mô hình…'}
            </span>
          </button>
          {selectedVoice && (
            <div className="flex items-center justify-center gap-2 text-xs text-muted">
              <VoiceAvatar name={selectedVoice.name} size={18} /> Giọng {selectedVoice.name}
              {selectedVoice.accent ? ` · tiếng Anh-${selectedVoice.accent === 'us' ? 'Mỹ' : 'Anh'}` : ' đọc tiếng Anh'}
            </div>
          )}
          {error && <p className="rounded-xl bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
        </div>
      </aside>

      {(current || lessons.length > 0) && (
        <section className="space-y-4 rounded-3xl border border-line bg-white p-5 lg:col-span-2">
          {current && (
            <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_280px]">
              <video
                key={current.id}
                src={shadowUrl(current.id, 'video')}
                controls
                autoPlay
                className={`w-full rounded-2xl bg-ink ${current.aspect === '9:16' ? 'mx-auto max-h-[70vh] w-auto' : 'aspect-video'}`}
              />
              <div className="space-y-3">
                <div>
                  <h2 className="text-lg font-semibold">{current.title}</h2>
                  <p className="mt-1 text-sm text-muted">{lessonMeta(current)}</p>
                </div>
                <div className="flex flex-col gap-2">
                  <DownloadLink href={shadowUrl(current.id, 'video', true)} icon={Film} label="Tải video MP4" primary />
                  <DownloadLink href={shadowUrl(current.id, 'audio', true)} icon={Music} label="Tải MP3 (chỉ tiếng)" />
                  <DownloadLink href={shadowUrl(current.id, 'srt', true)} icon={Captions} label="Tải phụ đề SRT" />
                  <button
                    onClick={() => setPublishing((p) => !p)}
                    className={`inline-flex items-center justify-center gap-2 rounded-xl border px-4 py-2.5 text-sm font-medium transition ${
                      publishing ? 'border-brand-400 bg-brand-50 text-brand-700' : 'border-line text-ink hover:border-zinc-300 hover:bg-canvas'
                    }`}
                  >
                    <Upload size={16} /> Đăng YouTube
                  </button>
                </div>
                <p className="text-xs leading-relaxed text-muted">
                  Video có ghi “Giọng đọc AI”. Khi đăng công khai, hãy giữ dòng này.
                </p>
              </div>
            </div>
          )}

          {current && publishing && (
            <div className="border-t border-line pt-4">
              <YouTubePublish key={current.id} lesson={current} onPublished={(url) => published(current.id, url)} />
            </div>
          )}

          {lessons.length > 0 && (
            <div className={current ? 'border-t border-line pt-4' : ''}>
              <h3 className="mb-2 text-sm font-semibold">Bài đã tạo</h3>
              <div className="divide-y divide-line">
                {lessons.map((l) => (
                  <div key={l.id} className="flex items-center gap-3 py-2.5">
                    <button
                      onClick={() => open(l)}
                      className={`min-w-0 flex-1 text-left ${current?.id === l.id ? 'text-brand-600' : 'hover:text-brand-600'}`}
                    >
                      <div className="truncate text-sm font-medium">{l.title}</div>
                      <div className="text-xs text-muted">
                        {new Date(l.created * 1000).toLocaleString('vi-VN')} · {lessonMeta(l)}
                      </div>
                    </button>
                    {l.youtube_url && (
                      <a
                        href={l.youtube_url}
                        target="_blank"
                        rel="noreferrer"
                        className="rounded-lg p-2 text-muted hover:bg-canvas hover:text-ink"
                        aria-label="Xem trên YouTube"
                        title="Xem trên YouTube"
                      >
                        <ExternalLink size={16} />
                      </a>
                    )}
                    <a
                      href={shadowUrl(l.id, 'video', true)}
                      className="rounded-lg p-2 text-muted hover:bg-canvas hover:text-ink"
                      aria-label="Tải video"
                      title="Tải video"
                    >
                      <Download size={16} />
                    </a>
                    <button
                      onClick={() => remove(l.id)}
                      className="rounded-lg p-2 text-muted hover:bg-red-50 hover:text-red-600"
                      aria-label="Xoá"
                    >
                      <Trash2 size={16} />
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}
        </section>
      )}
    </div>
  )
}

function lessonMeta(l: ShadowLesson) {
  return `${l.voice} · ${l.lines} câu · ${formatTime(l.duration)} · ${l.aspect}`
}

function Field({ label, hint, children }: { label: string; hint?: React.ReactNode; children: React.ReactNode }) {
  return (
    <div>
      <div className="mb-2 flex items-center justify-between text-sm">
        <span className="font-medium">{label}</span>
        {hint}
      </div>
      {children}
    </div>
  )
}

function DownloadLink({ href, icon: Icon, label, primary }: { href: string; icon: typeof Film; label: string; primary?: boolean }) {
  return (
    <a
      href={href}
      className={`inline-flex items-center justify-center gap-2 rounded-xl px-4 py-2.5 text-sm font-medium transition ${
        primary ? 'btn-brand text-white hover:brightness-105' : 'border border-line text-ink hover:border-zinc-300 hover:bg-canvas'
      }`}
    >
      <Icon size={16} /> {label}
    </a>
  )
}
