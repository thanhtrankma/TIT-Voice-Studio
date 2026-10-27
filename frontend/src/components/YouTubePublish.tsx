import { CalendarClock, ExternalLink, FileJson, KeyRound, Loader2, Upload, UserPlus } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import {
  api,
  waitForJob,
  type ShadowLesson,
  type YouTubePrivacy,
  type YouTubeStatus,
  type YouTubeUpload,
} from '../api'
import Segmented from './Segmented'

const PRIVACY: { value: YouTubePrivacy; label: string }[] = [
  { value: 'private', label: 'Riêng tư' },
  { value: 'unlisted', label: 'Không công khai' },
  { value: 'public', label: 'Công khai' },
]
const PRIVACY_LABEL = Object.fromEntries(PRIVACY.map((p) => [p.value, p.label])) as Record<YouTubePrivacy, string>

/** "2026-10-28T20:00" cho ô datetime-local, theo giờ máy. */
function localInput(d: Date) {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function tomorrowAt8pm() {
  const d = new Date()
  d.setDate(d.getDate() + 1)
  d.setHours(20, 0, 0, 0)
  return localInput(d)
}

type Props = { lesson: ShadowLesson; onPublished: (url: string) => void }

/** Đăng một bài luyện lên YouTube: kết nối tài khoản (một lần), sửa tiêu đề, mô tả, chọn chế độ hiển thị. */
export default function YouTubePublish({ lesson, onPublished }: Props) {
  const [status, setStatus] = useState<YouTubeStatus | null>(null)
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [tags, setTags] = useState<string[]>([])
  const [privacy, setPrivacy] = useState<YouTubePrivacy>('private')
  const [schedule, setSchedule] = useState(false)
  const [publishAt, setPublishAt] = useState(tomorrowAt8pm)
  const [earliest] = useState(() => localInput(new Date(Date.now() + 20 * 60_000)))   // backend đòi ≥ 15 phút
  const [uploads, setUploads] = useState<YouTubeUpload[]>([])
  const [busy, setBusy] = useState(false)
  const [progress, setProgress] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState<YouTubeUpload | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)

  useEffect(() => {
    api.youtube().then(setStatus).catch((e) => setError(e.message))
    api
      .shadowYoutube(lesson.id)
      .then(({ draft, uploads }) => {
        setTitle(draft.title)
        setDescription(draft.description)
        setTags(draft.tags)
        setUploads(uploads)
      })
      .catch((e) => setError(e.message))
  }, [lesson.id])

  // Đang chờ đăng nhập Google trong trình duyệt: hỏi lại đến khi có tài khoản hoặc báo lỗi.
  const waiting = status?.login.state === 'waiting'
  useEffect(() => {
    if (!waiting) return
    const timer = setInterval(() => api.youtube().then(setStatus).catch(() => {}), 2000)
    return () => clearInterval(timer)
  }, [waiting])

  async function uploadSecret(file: File) {
    setError(null)
    try {
      setStatus(await api.youtubeClientSecret(file))
    } catch (e) {
      setError((e as Error).message)
    }
  }

  async function login() {
    setError(null)
    try {
      setStatus(await api.youtubeLogin())
    } catch (e) {
      setError((e as Error).message)
    }
  }

  async function publish() {
    if (!status || busy || !title.trim()) return
    setBusy(true)
    setError(null)
    setDone(null)
    setProgress(0)
    try {
      const { job_id } = await api.publishShadow(lesson.id, {
        title,
        description,
        tags,
        privacy: schedule ? 'private' : privacy,
        publish_at: schedule ? new Date(publishAt).toISOString() : null,
        account: status.active || null,
      })
      const rec = await waitForJob<YouTubeUpload>(job_id, (j) => setProgress(j.progress))
      setDone(rec)
      setUploads((u) => [rec, ...u])
      onPublished(rec.url)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  if (!status) {
    return (
      <div className="flex items-center gap-2 text-sm text-muted">
        <Loader2 size={16} className="animate-spin" /> Đang kiểm tra kết nối YouTube…
      </div>
    )
  }

  const account = status.accounts.find((a) => a.id === status.active)
  const errorBox = error && <p className="rounded-xl bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>

  if (!status.client_secret) {
    return (
      <div className="space-y-3 text-sm">
        <h3 className="font-semibold">Kết nối YouTube (làm một lần)</h3>
        <ol className="list-decimal space-y-1 pl-5 text-muted">
          <li>
            Vào{' '}
            <a href="https://console.cloud.google.com/" target="_blank" rel="noreferrer" className="text-brand-600 underline">
              Google Cloud Console
            </a>
            , tạo project và bật <b className="text-ink">YouTube Data API v3</b>.
          </li>
          <li>
            <b className="text-ink">OAuth consent screen</b>: chọn External, thêm email của bạn vào Test users, rồi bấm
            Publish app để đăng nhập không hết hạn sau 7 ngày.
          </li>
          <li>
            <b className="text-ink">Credentials → OAuth client ID → Desktop app</b>, tải file JSON về rồi chọn ở đây.
          </li>
        </ol>
        <input
          ref={fileInput}
          type="file"
          accept=".json,application/json"
          className="hidden"
          onChange={(e) => e.target.files?.[0] && uploadSecret(e.target.files[0])}
        />
        <button
          onClick={() => fileInput.current?.click()}
          className="inline-flex items-center gap-2 rounded-xl border border-line px-4 py-2.5 font-medium hover:border-zinc-300 hover:bg-canvas"
        >
          <FileJson size={16} /> Chọn file client_secret.json
        </button>
        {errorBox}
      </div>
    )
  }

  if (!status.accounts.length || waiting) {
    return (
      <div className="space-y-3 text-sm">
        <h3 className="font-semibold">Kết nối tài khoản YouTube</h3>
        <p className="text-muted">
          Trình duyệt sẽ mở trang đăng nhập Google. Chọn kênh muốn đăng và cho phép quyền tải video lên.
        </p>
        <button
          onClick={login}
          disabled={waiting}
          className="btn-brand inline-flex items-center gap-2 rounded-xl px-4 py-2.5 font-medium text-white hover:brightness-105 disabled:opacity-70"
        >
          {waiting ? <Loader2 size={16} className="animate-spin" /> : <KeyRound size={16} />}
          {waiting ? 'Đang chờ bạn đăng nhập trong trình duyệt…' : 'Kết nối tài khoản YouTube'}
        </button>
        {status.login.error && <p className="rounded-xl bg-red-50 px-3 py-2 text-red-700">{status.login.error}</p>}
        {errorBox}
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-semibold">Đăng lên YouTube</h3>
        <div className="flex items-center gap-2 text-sm">
          {status.accounts.length > 1 ? (
            <select
              value={status.active}
              onChange={async (e) => setStatus(await api.youtubeSetActive(e.target.value))}
              className="rounded-lg border border-line bg-white px-2 py-1"
              aria-label="Tài khoản YouTube"
            >
              {status.accounts.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.label}
                </option>
              ))}
            </select>
          ) : (
            <span className="text-muted">{account?.label}</span>
          )}
          <button
            onClick={login}
            className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-muted hover:bg-canvas hover:text-ink"
            title="Thêm tài khoản"
          >
            <UserPlus size={14} /> Thêm
          </button>
        </div>
      </div>

      <label className="block">
        <div className="mb-1 flex justify-between text-sm">
          <span className="font-medium">Tiêu đề</span>
          <span className="tabular-nums text-muted">{title.length}/100</span>
        </div>
        <input
          value={title}
          maxLength={100}
          onChange={(e) => setTitle(e.target.value)}
          className="w-full rounded-xl border border-line bg-canvas px-3 py-2 text-sm outline-none focus:border-brand-400 focus:bg-white"
        />
      </label>
      <label className="block">
        <div className="mb-1 flex justify-between text-sm">
          <span className="font-medium">Mô tả</span>
          <span className="tabular-nums text-muted">{description.length}/5000</span>
        </div>
        <textarea
          value={description}
          maxLength={5000}
          onChange={(e) => setDescription(e.target.value)}
          rows={8}
          className="w-full resize-y rounded-xl border border-line bg-canvas px-3 py-2 text-sm leading-6 outline-none focus:border-brand-400 focus:bg-white"
        />
      </label>

      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <div className="mb-2 text-sm font-medium">Chế độ hiển thị</div>
          <Segmented options={PRIVACY} value={schedule ? 'private' : privacy} onChange={(v) => !schedule && setPrivacy(v)} />
        </div>
        <div>
          <label className="mb-2 flex cursor-pointer items-center gap-2 text-sm font-medium">
            <input
              type="checkbox"
              checked={schedule}
              onChange={(e) => setSchedule(e.target.checked)}
              className="size-4 accent-[var(--color-brand-500)]"
            />
            <CalendarClock size={15} /> Hẹn giờ công khai
          </label>
          <input
            type="datetime-local"
            value={publishAt}
            min={earliest}
            onChange={(e) => setPublishAt(e.target.value)}
            disabled={!schedule}
            className="w-full rounded-xl border border-line bg-canvas px-3 py-1.5 text-sm disabled:opacity-50"
          />
        </div>
      </div>
      <p className="text-xs leading-relaxed text-muted">
        Video được khai báo là có giọng đọc tạo bằng AI. Nếu project Google Cloud chưa qua kiểm duyệt YouTube API, YouTube
        sẽ khoá video ở chế độ Riêng tư dù bạn chọn gì.
      </p>

      <button
        onClick={publish}
        disabled={busy || !title.trim()}
        className="btn-brand relative flex w-full items-center justify-center gap-2 overflow-hidden rounded-2xl py-3 font-semibold text-white hover:brightness-105 disabled:cursor-not-allowed disabled:opacity-60"
      >
        {busy && (
          <span className="absolute inset-y-0 left-0 bg-white/20 transition-[width] duration-500" style={{ width: `${Math.round(progress * 100)}%` }} />
        )}
        {busy ? <Loader2 size={18} className="animate-spin" /> : <Upload size={18} />}
        <span className="relative">
          {busy ? `Đang tải lên YouTube… ${Math.round(progress * 100)}%` : schedule ? 'Tải lên và hẹn giờ' : 'Đăng lên YouTube'}
        </span>
      </button>
      {done && (
        <div className="rounded-xl bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
          Đã tải lên:{' '}
          <a href={done.url} target="_blank" rel="noreferrer" className="font-medium underline">
            {done.url}
          </a>
          {done.publish_at && ` · công khai lúc ${new Date(done.publish_at).toLocaleString('vi-VN')}`}
          {done.note && <div className="mt-1 text-amber-700">{done.note}</div>}
        </div>
      )}
      {errorBox}

      {uploads.length > 0 && (
        <div className="border-t border-line pt-3">
          <h4 className="mb-1 text-sm font-semibold">Đã đăng bài này</h4>
          {uploads.map((u) => (
            <a
              key={u.video_id}
              href={u.url}
              target="_blank"
              rel="noreferrer"
              className="flex items-center gap-2 py-1 text-sm hover:text-brand-600"
            >
              <ExternalLink size={14} className="shrink-0" />
              <span className="truncate">{u.url}</span>
              <span className="shrink-0 text-xs text-muted">
                {PRIVACY_LABEL[u.privacy]}
                {u.publish_at && ` · hẹn ${new Date(u.publish_at).toLocaleString('vi-VN')}`} · {u.account}
              </span>
            </a>
          ))}
        </div>
      )}
    </div>
  )
}
