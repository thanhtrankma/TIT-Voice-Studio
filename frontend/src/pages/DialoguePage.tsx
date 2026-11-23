import { Clapperboard, Eraser, Loader2 } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { api, waitForJob, type DialogueRequest, type EnglishStatus, type ShadowLesson, type Voice } from '../api'
import { formatTime } from '../components/AudioPlayer'
import LessonLibrary, { Field } from '../components/LessonLibrary'
import MusicPicker from '../components/MusicPicker'
import Segmented from '../components/Segmented'
import VoiceLibrary, { VoiceAvatar } from '../components/VoiceLibrary'

const SAMPLES: { label: string; title: string; text: string }[] = [
  {
    label: 'Làm quen',
    title: 'Chào hỏi và làm quen',
    text: [
      '你好！我叫小明，你叫什么名字？ | Xin chào! Mình tên Tiểu Minh, bạn tên gì? | Hi! I’m Xiaoming. What’s your name?',
      '我叫阿兰，*很高兴认识你*。 | Mình tên Lan, *rất vui được làm quen* với bạn. | I’m Lan. Nice to meet you.',
      '',
      '你是*哪国人*？ | Bạn là *người nước nào*? | Where are you from?',
      '我是越南人，我在河内工作。 | Mình là người Việt Nam, mình làm việc ở Hà Nội. | I’m Vietnamese. I work in Hanoi.',
      '',
      '你*会说*中文吗？ | Bạn *biết nói* tiếng Trung không? | Can you speak Chinese?',
      '会一点儿，我还在学习。 | Biết một chút, mình vẫn đang học. | A little. I’m still learning.',
    ].join('\n'),
  },
  {
    label: 'Mua sắm',
    title: 'Đi mua quần áo',
    text: [
      '这件衣服*多少钱*？ | Bộ quần áo này *bao nhiêu tiền*? | How much is this?',
      '两百块，现在*打八折*。 | Hai trăm tệ, bây giờ đang *giảm 20%*. | 200 yuan, 20% off right now.',
      '',
      '我可以*试试*吗？ | Tôi *thử* được không? | Can I try it on?',
      '当然可以，试衣间在那边。 | Tất nhiên rồi, phòng thử đồ ở đằng kia. | Of course, the fitting room is over there.',
      '',
      '有没有*大一点儿*的？ | Có cái nào *lớn hơn một chút* không? | Do you have a bigger one?',
      '有，我给你拿一件。 | Có, để tôi lấy cho bạn một cái. | Yes, let me get one for you.',
    ].join('\n'),
  },
  {
    label: 'Nhà hàng',
    title: 'Gọi món ở nhà hàng',
    text: [
      '你们*几位*？ | Các bạn *mấy người*? | How many people?',
      '两位，有*靠窗*的位子吗？ | Hai người, có chỗ *cạnh cửa sổ* không? | Two. Is there a window seat?',
      '',
      '你们想*吃点儿什么*？ | Các bạn muốn *ăn gì*? | What would you like to eat?',
      '来一碗牛肉面，*不要太辣*。 | Cho tôi một bát mì bò, *đừng cay quá*. | A bowl of beef noodles, not too spicy.',
      '',
      '服务员，*买单*！ | Phục vụ ơi, *tính tiền*! | Waiter, the check please!',
      '好的，一共五十八块。 | Vâng, tổng cộng năm mươi tám tệ. | Sure, 58 yuan in total.',
    ].join('\n'),
  },
]

const REPEATS = [1, 2, 3].map((r) => ({ value: r, label: `${r} lần` }))
const SPEEDS = [
  { value: 0.8, label: 'Chậm 0.8x' },
  { value: 0.9, label: '0.9x' },
  { value: 1, label: 'Thường 1x' },
]
// Lần đọc thứ 2: 0 = như lần 1 (Segmented cần giá trị số, gửi lên backend là null)
const SPEEDS_2 = [
  { value: 0, label: 'Như lần 1' },
  { value: 0.6, label: '0.6x' },
  { value: 0.7, label: '0.7x' },
  { value: 0.8, label: '0.8x' },
  { value: 0.9, label: '0.9x' },
]
const MAX_LOOPS = 60
const MAX_TOTAL = 11.5 * 3600   // backend tự giảm số lượt để video không quá giới hạn 12 giờ của YouTube
type Slot = 'a' | 'b'
const DEFAULT_VOICE: Record<Slot, string> = { a: 'kokoro:zf_xiaoxiao', b: 'kokoro:zm_yunxi' }

type Parsed = { zh: string; vi: string; block: number }

// thẻ [nghỉ 500ms], [cười], [laugh]… không hiện trên video (app/dialogue.py: strip_tags)
const TAG = /\[[^\]]{1,30}\]/g

const HANZI = /[㐀-鿿豈-﫿]/g

/** Tách câu giống backend (app/dialogue.py: parse_dialogue) để đếm và ước lượng trước khi tạo. */
function parse(text: string): Parsed[] {
  const out: Parsed[] = []
  let block = 0
  let open = false
  for (const raw of text.split('\n')) {
    if (!raw.trim()) {
      if (open) block++
      open = false
      continue
    }
    const [zh = '', vi = ''] = raw.replace(/^\s*[ABab]\s*[:：]\s*/, '').split('|').map((p) => p.replace(/[*＊]/g, '').replace(TAG, ' ').trim())
    if (!zh) continue
    out.push({ zh, vi, block })
    open = true
  }
  return out
}

/** Một lượt dài bao lâu: Kokoro đọc khoảng 4,5 chữ Hán mỗi giây, VieNeu khoảng 14 ký tự mỗi giây. */
function loopSeconds(
  lines: Parsed[],
  s: { repeats: number; speed: number; speed2: number; pause: number; readVi: boolean },
) {
  let total = 0.8 + 1.5
  lines.forEach((l, i) => {
    const base = Math.max(0.6, (l.zh.match(HANZI)?.length ?? 0) / 4.5 + 0.3)
    for (let r = 0; r < s.repeats; r++) total += base / (r === 1 && s.speed2 ? s.speed2 : s.speed) + s.pause
    if (s.readVi && l.vi) total += Math.max(0.8, l.vi.length / 14) + s.pause
    if (lines[i + 1] && lines[i + 1].block !== l.block) total += s.pause * 1.5
  })
  return total
}

function hours(seconds: number) {
  return seconds >= 3600 ? `${(seconds / 3600).toFixed(1).replace('.', ',')} giờ` : formatTime(seconds)
}

type Props = { voices: Voice[]; ready: boolean }

export default function DialoguePage({ voices, ready }: Props) {
  const [title, setTitle] = useState(SAMPLES[0].title)
  const [text, setText] = useState(SAMPLES[0].text)
  const [chinese, setChinese] = useState<EnglishStatus | null>(null)
  const [slot, setSlot] = useState<Slot>('a')
  const [picked, setPicked] = useState<Record<Slot, string>>(DEFAULT_VOICE)
  const [repeats, setRepeats] = useState(2)
  const [speed, setSpeed] = useState(1)
  const [speed2, setSpeed2] = useState(0)
  const [pause, setPause] = useState(1)
  const [loops, setLoops] = useState(1)
  const [readVi, setReadVi] = useState(true)
  const [viVoice, setViVoice] = useState<string | null>(null)
  const [showEn, setShowEn] = useState(true)
  const [intro, setIntro] = useState(true)
  const [music, setMusic] = useState<string | null>(null)
  const [musicVolume, setMusicVolume] = useState(0.4)
  const [busy, setBusy] = useState(false)
  const [progress, setProgress] = useState(0)
  const [stage, setStage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [lessons, setLessons] = useState<ShadowLesson[]>([])
  const [current, setCurrent] = useState<ShadowLesson | null>(null)

  const zhVoices = chinese?.voices ?? []
  const pick = (s: Slot) => zhVoices.find((v) => v.id === picked[s]) ?? zhVoices[s === 'a' ? 0 : zhVoices.length - 1]
  const voiceA = pick('a')
  const voiceB = pick('b')
  const vi = voices.find((v) => v.id === viVoice) ?? voices.find((v) => v.featured) ?? voices[0]
  const lines = useMemo(() => parse(text), [text])
  const blocks = lines.length ? lines[lines.length - 1].block + 1 : 0
  const perLoop = lines.length ? loopSeconds(lines, { repeats, speed, speed2, pause, readVi }) : 0
  // intro: chuông + (nếu đọc nghĩa) giọng Việt đọc tên bài, ít nhất 4,5 giây
  const introSeconds = intro ? Math.max(4.5, readVi ? 2 + (title.length + 25) / 14 : 0) : 0
  const total = Math.min(introSeconds + perLoop * loops, MAX_TOTAL)

  useEffect(() => {
    api.shadowLessons('dialogue').then(setLessons).catch(() => {})
    api.chinese().then(setChinese).catch(() => {})
  }, [])

  async function generate() {
    if (!voiceA || !voiceB || !lines.length || busy) return
    setBusy(true)
    setError(null)
    setProgress(0)
    setStage(null)
    const body: DialogueRequest = {
      text,
      title,
      voice_a: voiceA.id,
      voice_b: voiceB.id,
      vi_voice: readVi && vi ? vi.id : null,
      repeats,
      speed,
      speed2: repeats > 1 && speed2 ? speed2 : null,
      pause,
      loops,
      show_en: showEn,
      intro,
      music,
      music_volume: musicVolume,
    }
    try {
      const { job_id } = await api.dialogue(body)
      const lesson = await waitForJob<ShadowLesson>(job_id, (j) => {
        setProgress(j.progress)
        setStage(j.stage)
      })
      setLessons((l) => [lesson, ...l])
      setCurrent(lesson)
      if (!chinese?.installed) api.chinese().then(setChinese).catch(() => {})
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const phase =
    stage ??
    (progress < 0.7
      ? `Đang đọc câu ${Math.min(lines.length, Math.floor((progress / 0.7) * lines.length) + 1)}/${lines.length}…`
      : 'Đang dựng video…')

  return (
    <div className="mx-auto grid h-full max-w-[1400px] grid-cols-1 gap-5 p-5 lg:grid-cols-[minmax(0,1fr)_400px]">
      {/* Lời thoại + cách đọc */}
      <section className="flex min-h-[520px] flex-col overflow-hidden rounded-3xl border border-line bg-white shadow-[0_1px_2px_rgb(0_0_0/0.03)]">
        <div className="flex items-center justify-between gap-3 border-b border-line px-6 py-3.5">
          <div className="flex min-w-0 items-center gap-2 text-sm text-muted">
            <span className="font-medium text-ink">Lời thoại</span>
            <span>·</span>
            <span className="truncate">中文 | Tiếng Việt | English, dòng trống mở đoạn mới, *từ khoá* để tô màu</span>
          </div>
          <button
            onClick={() => setText('')}
            className="inline-flex shrink-0 items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-sm text-muted hover:bg-canvas hover:text-ink"
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
            placeholder={'你*抽烟*吗？ | Bạn *hút thuốc* không? | Do you smoke?\n不抽，谢谢。 | Không, cảm ơn. | No, thanks.'}
            className="min-h-[260px] w-full flex-1 resize-none bg-transparent text-[16px] leading-8 outline-none placeholder:text-zinc-400"
          />
          <p className="text-xs leading-relaxed text-muted">
            Trong một đoạn, người nói luân phiên A rồi B. Ghi <code className="rounded bg-canvas px-1">A:</code> hoặc{' '}
            <code className="rounded bg-canvas px-1">B:</code> đầu dòng để chọn người nói. Pinyin được tạo tự động.
          </p>
        </div>

        <div className="grid grid-cols-1 gap-4 border-t border-line px-6 py-4 sm:grid-cols-2 [&>*]:min-w-0">
          <Field label="Đọc mỗi câu tiếng Trung">
            <Segmented options={REPEATS} value={repeats} onChange={setRepeats} />
          </Field>
          <Field label="Tốc độ đọc">
            <Segmented options={SPEEDS} value={speed} onChange={setSpeed} />
          </Field>
          <div className={`sm:col-span-2 ${repeats < 2 ? 'opacity-50' : ''}`}>
            <Field
              label="Tốc độ lần đọc thứ 2"
              hint={
                <span className="text-xs text-muted">
                  {repeats < 2 ? 'Cần đọc mỗi câu từ 2 lần' : repeats > 2 ? 'Lần 3 đọc lại tốc độ thường' : 'Nghe chậm để bắt từng âm'}
                </span>
              }
            >
              <fieldset disabled={repeats < 2}>
                <Segmented options={SPEEDS_2} value={speed2} onChange={setSpeed2} />
              </fieldset>
            </Field>
          </div>
          <Field
            label="Nghỉ sau mỗi lượt đọc"
            hint={<span className="rounded-md bg-canvas px-2 py-0.5 text-xs font-semibold tabular-nums">{pause.toFixed(1)} giây</span>}
          >
            <input
              type="range"
              min={0.3}
              max={3}
              step={0.1}
              value={pause}
              onChange={(e) => setPause(Number(e.target.value))}
              className="speed w-full"
              aria-label="Nghỉ sau mỗi lượt đọc"
            />
          </Field>
          <Field
            label="Lặp cả bài"
            hint={<span className="rounded-md bg-canvas px-2 py-0.5 text-xs font-semibold tabular-nums">{loops} lượt</span>}
          >
            <input
              type="range"
              min={1}
              max={MAX_LOOPS}
              step={1}
              value={loops}
              onChange={(e) => setLoops(Number(e.target.value))}
              className="speed w-full"
              aria-label="Số lượt lặp cả bài"
            />
          </Field>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2 text-sm sm:col-span-2">
            <label className="flex cursor-pointer items-center gap-2.5">
              <input
                type="checkbox"
                checked={readVi}
                onChange={(e) => setReadVi(e.target.checked)}
                className="size-4 accent-[var(--color-brand-500)]"
              />
              <span className="font-medium">Đọc nghĩa tiếng Việt</span>
            </label>
            {readVi && (
              <select
                value={vi?.id ?? ''}
                onChange={(e) => setViVoice(e.target.value)}
                className="min-w-0 max-w-full rounded-lg border border-line bg-canvas px-2 py-1 text-sm outline-none focus:border-brand-400"
                aria-label="Giọng đọc nghĩa tiếng Việt"
              >
                {voices.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.name} · {v.description}
                  </option>
                ))}
              </select>
            )}
            <span className="text-muted">sau lần đọc tiếng Trung đầu tiên</span>
          </div>
          <label className="flex cursor-pointer items-center gap-2.5 text-sm sm:col-span-2">
            <input
              type="checkbox"
              checked={showEn}
              onChange={(e) => setShowEn(e.target.checked)}
              className="size-4 accent-[var(--color-brand-500)]"
            />
            <span>
              <span className="font-medium">Hiện câu tiếng Anh</span>
              <span className="text-muted"> · dòng nhỏ phía trên chữ Hán, nếu có</span>
            </span>
          </label>
          <label className="flex cursor-pointer items-center gap-2.5 text-sm sm:col-span-2">
            <input
              type="checkbox"
              checked={intro}
              onChange={(e) => setIntro(e.target.checked)}
              className="size-4 accent-[var(--color-brand-500)]"
            />
            <span>
              <span className="font-medium">Thêm intro đầu video</span>
              <span className="text-muted">
                {' '}
                · ~{Math.round(introSeconds || 5)} giây: tên bài, hai giọng, số câu
                {readVi ? '; giọng tiếng Việt đọc tên bài' : ''}
              </span>
            </span>
          </label>
          <div className="sm:col-span-2">
            <Field label="Nhạc nền">
              <MusicPicker value={music} onChange={setMusic} volume={musicVolume} onVolume={setMusicVolume} />
            </Field>
          </div>
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
            {lines.length} câu · {blocks} đoạn · mỗi lượt ~{formatTime(perLoop)}
            {(loops > 1 || intro) && ` · cả video ~${hours(total)}`}
          </span>
        </div>
      </section>

      {/* Cột phải: giọng người A, người B + nút tạo */}
      <aside className="flex min-h-[520px] flex-col overflow-hidden rounded-3xl border border-line bg-white lg:max-h-[calc(100vh-170px)]">
        <div className="flex items-center justify-between px-5 pt-5 pb-3">
          <h2 className="text-base font-semibold">Giọng tiếng Trung</h2>
          <span className="rounded-full bg-canvas px-2 py-0.5 text-xs text-muted">{zhVoices.length} giọng</span>
        </div>
        <div className="px-5 pb-3">
          <Segmented
            options={[
              { value: 'a', label: `Người A · ${voiceA?.name ?? '…'}` },
              { value: 'b', label: `Người B · ${voiceB?.name ?? '…'}` },
            ]}
            value={slot}
            onChange={setSlot}
          />
          <p className="mt-2 text-xs leading-relaxed text-muted">
            {chinese && !chinese.installed
              ? `Giọng phổ thông chuẩn, người A bên trái màn hình, người B bên phải. Lần đầu dùng sẽ tải khoảng ${chinese.download_mb} MB.`
              : 'Giọng phổ thông chuẩn. Người A ở bên trái màn hình, người B ở bên phải.'}
          </p>
        </div>
        <VoiceLibrary
          key={slot}
          voices={zhVoices}
          selected={(slot === 'a' ? voiceA : voiceB)?.id ?? null}
          onSelect={(id) => setPicked((p) => ({ ...p, [slot]: id }))}
        />

        <div className="space-y-3 border-t border-line p-5">
          <button
            onClick={generate}
            disabled={!ready || busy || !lines.length || !voiceA || !voiceB}
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
              {busy ? `${phase} ${Math.round(progress * 100)}%` : ready ? 'Tạo video hội thoại' : 'Đang nạp mô hình…'}
            </span>
          </button>
          {voiceA && voiceB && (
            <div className="flex items-center justify-center gap-3 text-xs text-muted">
              <span className="flex items-center gap-1.5">
                <VoiceAvatar name={voiceA.name} size={18} /> A · {voiceA.name}
              </span>
              <span className="flex items-center gap-1.5">
                <VoiceAvatar name={voiceB.name} size={18} /> B · {voiceB.name}
              </span>
            </div>
          )}
          {error && <p className="rounded-xl bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
        </div>
      </aside>

      <LessonLibrary
        lessons={lessons}
        setLessons={setLessons}
        current={current}
        setCurrent={setCurrent}
        meta={(l) => `${l.voice} · ${l.lines} câu · ${hours(l.duration)}`}
        audioLabel="Tải MP3 để nghe"
      />
    </div>
  )
}
