import { Captions, Download, ExternalLink, Film, Music, Trash2, Upload } from 'lucide-react'
import { useState, type Dispatch, type SetStateAction } from 'react'
import { api, shadowUrl, type ShadowLesson } from '../api'
import YouTubePublish from './YouTubePublish'

type Props = {
  lessons: ShadowLesson[]
  setLessons: Dispatch<SetStateAction<ShadowLesson[]>>
  current: ShadowLesson | null
  setCurrent: Dispatch<SetStateAction<ShadowLesson | null>>
  /** Dòng mô tả ngắn dưới tên bài. */
  meta: (l: ShadowLesson) => string
  audioLabel?: string
}

/** Video vừa chọn (xem, tải, đăng YouTube) và danh sách bài đã tạo; dùng chung cho Shadowing và hội thoại. */
export default function LessonLibrary({ lessons, setLessons, current, setCurrent, meta, audioLabel = 'Tải MP3 (chỉ tiếng)' }: Props) {
  // nhớ theo id: mở bài khác (kể cả bài vừa tạo) thì khung đăng YouTube tự đóng
  const [publishingId, setPublishingId] = useState<string | null>(null)
  const publishing = !!current && publishingId === current.id

  if (!current && !lessons.length) return null

  function open(lesson: ShadowLesson) {
    setCurrent(lesson)
    setPublishingId(null)
  }

  function published(id: string, url: string) {
    setLessons((l) => l.map((x) => (x.id === id ? { ...x, youtube_url: url } : x)))
    setCurrent((c) => (c?.id === id ? { ...c, youtube_url: url } : c))
  }

  async function remove(id: string) {
    if (!confirm('Xoá bài này? Video, MP3 và phụ đề cũng bị xoá.')) return
    await api.deleteShadow(id)
    setLessons((l) => l.filter((x) => x.id !== id))
    if (current?.id === id) setCurrent(null)
  }

  return (
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
              <p className="mt-1 text-sm text-muted">{meta(current)}</p>
            </div>
            <div className="flex flex-col gap-2">
              <DownloadLink href={shadowUrl(current.id, 'video', true)} icon={Film} label="Tải video MP4" primary />
              <DownloadLink href={shadowUrl(current.id, 'audio', true)} icon={Music} label={audioLabel} />
              <DownloadLink href={shadowUrl(current.id, 'srt', true)} icon={Captions} label="Tải phụ đề SRT" />
              <button
                onClick={() => setPublishingId(publishing ? null : current.id)}
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
                    {new Date(l.created * 1000).toLocaleString('vi-VN')} · {meta(l)}
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
  )
}

export function Field({ label, hint, children }: { label: string; hint?: React.ReactNode; children: React.ReactNode }) {
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
