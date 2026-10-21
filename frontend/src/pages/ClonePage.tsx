import { Loader2, Mic, RotateCcw, ShieldCheck, Square, Trash2 } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { api, waitForJob, type Voice } from '../api'
import { formatTime } from '../components/AudioPlayer'
import { PreviewButton, VoiceAvatar } from '../components/VoiceLibrary'

const MAX_SECONDS = 15
const MIN_SECONDS = 4

type Props = { voices: Voice[]; consentSentence: string; ready: boolean; onChange: () => void }

export default function ClonePage({ voices, consentSentence, ready, onChange }: Props) {
  const recorder = useRef<MediaRecorder | null>(null)
  const timer = useRef<number | null>(null)
  const [recording, setRecording] = useState(false)
  const [seconds, setSeconds] = useState(0)
  const [blob, setBlob] = useState<Blob | null>(null)
  const [name, setName] = useState('')
  const [gender, setGender] = useState('female')
  const [consent, setConsent] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const custom = voices.filter((v) => v.custom)
  const blobUrl = useMemo(() => (blob ? URL.createObjectURL(blob) : null), [blob])

  useEffect(() => () => {
    if (blobUrl) URL.revokeObjectURL(blobUrl)
  }, [blobUrl])

  useEffect(() => () => stopTimer(), [])

  function stopTimer() {
    if (timer.current) window.clearInterval(timer.current)
    timer.current = null
  }

  async function start() {
    setError(null)
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } })
      const rec = new MediaRecorder(stream)
      const chunks: Blob[] = []
      rec.ondataavailable = (e) => chunks.push(e.data)
      rec.onstop = () => {
        stream.getTracks().forEach((t) => t.stop())
        setBlob(new Blob(chunks, { type: rec.mimeType }))
      }
      rec.start()
      recorder.current = rec
      setBlob(null)
      setSeconds(0)
      setRecording(true)
      const started = Date.now()
      timer.current = window.setInterval(() => {
        const s = (Date.now() - started) / 1000
        setSeconds(s)
        if (s >= MAX_SECONDS) stop()
      }, 100)
    } catch {
      setError('Không mở được micro. Hãy cho phép trình duyệt dùng micro.')
    }
  }

  function stop() {
    stopTimer()
    if (recorder.current?.state === 'recording') recorder.current.stop()
    setRecording(false)
  }

  async function submit() {
    if (!blob) return
    setBusy(true)
    setError(null)
    try {
      const form = new FormData()
      form.append('name', name.trim())
      form.append('gender', gender)
      form.append('consent', String(consent))
      form.append('audio', blob, `recording.${blob.type.includes('mp4') ? 'mp4' : 'webm'}`)
      const { job_id } = await api.cloneVoice(form)
      await waitForJob(job_id)
      setBlob(null)
      setName('')
      setConsent(false)
      onChange()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  async function remove(id: string) {
    if (!confirm(`Xoá giọng "${id}"?`)) return
    await api.deleteVoice(id)
    onChange()
  }

  const canSubmit = ready && blob && seconds >= MIN_SECONDS && name.trim() && consent && !busy

  return (
    <div className="mx-auto grid max-w-5xl gap-5 p-5 lg:grid-cols-[1.3fr_1fr]">
      <section className="space-y-5 rounded-3xl border border-line bg-white p-6">
        <div>
          <h1 className="text-2xl font-semibold">Nhân bản giọng của bạn</h1>
          <p className="mt-1 text-sm text-muted">
            Thu khoảng {MIN_SECONDS}–{MAX_SECONDS} giây ở nơi yên tĩnh, đọc to câu dưới đây bằng giọng bình thường.
          </p>
        </div>

        <blockquote className="rounded-2xl bg-brand-50 px-5 py-4 text-lg leading-relaxed font-medium text-brand-700">
          “{consentSentence}”
        </blockquote>

        <div className="flex flex-col items-center gap-3 py-2">
          <button
            onClick={recording ? stop : start}
            className={`relative grid size-20 place-items-center rounded-full text-white transition ${
              recording ? 'bg-red-500' : 'btn-brand hover:scale-105'
            }`}
            aria-label={recording ? 'Dừng thu' : 'Bắt đầu thu'}
          >
            {recording && <span className="absolute inset-0 animate-ping rounded-full bg-red-400/40" />}
            {recording ? <Square size={24} fill="currentColor" /> : <Mic size={28} />}
          </button>
          <span className="text-sm tabular-nums text-muted">
            {recording ? `Đang thu ${formatTime(seconds)} / ${formatTime(MAX_SECONDS)}` : blob ? `Đã thu ${formatTime(seconds)}` : 'Bấm để thu'}
          </span>
          {blobUrl && !recording && (
            <div className="flex w-full items-center gap-2">
              <audio src={blobUrl} controls className="h-10 flex-1" />
              <button onClick={start} className="rounded-lg p-2 text-muted hover:bg-canvas" title="Thu lại">
                <RotateCcw size={16} />
              </button>
            </div>
          )}
          {blob && seconds < MIN_SECONDS && <p className="text-sm text-amber-700">Bản thu hơi ngắn, hãy thu ít nhất {MIN_SECONDS} giây.</p>}
        </div>

        <div className="grid gap-3 sm:grid-cols-[1fr_auto]">
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={40}
            placeholder="Tên giọng, VD: Giọng của tôi"
            className="rounded-xl border border-line px-3.5 py-2.5 outline-none focus:border-brand-400"
          />
          <div className="flex rounded-xl bg-canvas p-1">
            {[
              ['female', 'Nữ'],
              ['male', 'Nam'],
            ].map(([id, label]) => (
              <button
                key={id}
                onClick={() => setGender(id)}
                className={`rounded-lg px-4 text-sm font-medium ${gender === id ? 'bg-white shadow-sm' : 'text-muted'}`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        <label className="flex items-start gap-3 rounded-2xl border border-line p-4 text-sm">
          <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} className="mt-0.5 size-4 accent-brand-500" />
          <span>
            Tôi xác nhận đây là <b>giọng của chính tôi</b> và sẽ không dùng giọng nhân bản để giả mạo, lừa đảo hay gây hiểu lầm.
          </span>
        </label>

        {error && <p className="rounded-xl bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

        <button
          onClick={submit}
          disabled={!canSubmit}
          className="btn-brand flex w-full items-center justify-center gap-2 rounded-2xl py-3.5 font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50"
        >
          {busy ? <Loader2 size={18} className="animate-spin" /> : <ShieldCheck size={18} />}
          {busy ? 'Đang tạo giọng…' : 'Tạo giọng nhân bản'}
        </button>
      </section>

      <section className="rounded-3xl border border-line bg-white p-6">
        <h2 className="font-semibold">Giọng đã nhân bản</h2>
        <div className="mt-4 space-y-2">
          {!custom.length && <p className="py-8 text-center text-sm text-muted">Chưa có giọng nào.</p>}
          {custom.map((v) => (
            <div key={v.id} className="flex items-center gap-3 rounded-2xl border border-line p-3">
              <VoiceAvatar name={v.name} size={38} />
              <div className="min-w-0 flex-1">
                <p className="truncate font-medium">{v.name}</p>
                <p className="text-xs text-muted">{v.description}</p>
              </div>
              <PreviewButton voice={v.id} />
              <button onClick={() => remove(v.id)} className="rounded-lg p-2 text-muted hover:bg-red-50 hover:text-red-600" aria-label="Xoá giọng">
                <Trash2 size={15} />
              </button>
            </div>
          ))}
        </div>
      </section>
    </div>
  )
}
