export type Voice = {
  id: string
  name: string
  gender: 'male' | 'female' | string
  region: 'north' | 'central' | 'south' | null
  /** Chỉ giọng tiếng Anh bản xứ (Kokoro) có: giọng Mỹ hay Anh. */
  accent?: 'us' | 'uk'
  style: string
  description: string
  featured: boolean
  custom: boolean
}

export type Health = {
  status: 'ready' | 'loading' | 'error'
  error: string | null
  engine: string
  precision: string
  sample_rate: number
  emotion_tags: string[]
  consent_sentence: string
}

export type EnglishStatus = {
  installed: boolean
  download_mb: number
  voices: Voice[]
}

export type HistoryItem = {
  id: string
  created: number
  text: string
  voice: string
  speed: number
  duration: number
  chars: number
}

export type ShadowLesson = {
  id: string
  created: number
  title: string
  voice: string
  lines: number
  duration: number
  aspect: '16:9' | '9:16'
  /** Lần đăng YouTube gần nhất, nếu có. */
  youtube_url?: string | null
}

export type YouTubeStatus = {
  client_secret: boolean
  accounts: { id: string; label: string }[]
  active: string
  login: { state: 'idle' | 'waiting' | 'error'; error: string | null }
}

export type YouTubePrivacy = 'private' | 'unlisted' | 'public'

export type YouTubeUpload = {
  video_id: string
  url: string
  title: string
  privacy: YouTubePrivacy
  publish_at: string | null
  account: string
  uploaded: number
  note?: string | null
}

export type YouTubeDraft = { title: string; description: string; tags: string[] }

export type ShadowRequest = {
  text: string
  voice: string
  title: string
  repeats: number
  slow_speed: number
  gap_factor: number
  full_run: boolean
  aspect: '16:9' | '9:16'
}

export type Job<R = unknown> = {
  id: string
  kind: string
  status: 'queued' | 'running' | 'done' | 'error'
  progress: number
  stage: string | null
  error: string | null
  result: R | null
  queue_position: number
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init)
  if (!res.ok) {
    let detail = res.statusText
    try {
      detail = (await res.json()).detail ?? detail
    } catch {
      /* phản hồi không phải JSON */
    }
    throw new Error(detail)
  }
  return res.json()
}

const json = (body: unknown, method = 'POST'): RequestInit => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

export const api = {
  health: () => request<Health>('/api/health'),
  voices: () => request<Voice[]>('/api/voices'),
  tts: (body: { text: string; voice: string; speed: number }) =>
    request<{ job_id: string }>('/api/tts', json(body)),
  job: <R>(id: string) => request<Job<R>>(`/api/jobs/${id}`),
  history: () => request<HistoryItem[]>('/api/history'),
  deleteHistory: (id: string) => request(`/api/history/${id}`, { method: 'DELETE' }),
  dictionary: () => request<Record<string, string>>('/api/dictionary'),
  saveDictionary: (entries: Record<string, string>) =>
    request<Record<string, string>>('/api/dictionary', json({ entries }, 'PUT')),
  cloneVoice: (form: FormData) =>
    request<{ job_id: string }>('/api/voices/clone', { method: 'POST', body: form }),
  deleteVoice: (id: string) =>
    request(`/api/voices/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  english: () => request<EnglishStatus>('/api/english'),
  shadow: (body: ShadowRequest) => request<{ job_id: string; lines: number }>('/api/shadow', json(body)),
  shadowLessons: () => request<ShadowLesson[]>('/api/shadow'),
  deleteShadow: (id: string) => request(`/api/shadow/${id}`, { method: 'DELETE' }),
  youtube: () => request<YouTubeStatus>('/api/youtube'),
  youtubeClientSecret: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request<YouTubeStatus>('/api/youtube/client-secret', { method: 'POST', body: form })
  },
  youtubeLogin: () => request<YouTubeStatus>('/api/youtube/login', { method: 'POST' }),
  youtubeSetActive: (id: string) =>
    request<YouTubeStatus>(`/api/youtube/accounts/${encodeURIComponent(id)}/active`, { method: 'PUT' }),
  shadowYoutube: (id: string) =>
    request<{ draft: YouTubeDraft; uploads: YouTubeUpload[] }>(`/api/shadow/${id}/youtube`),
  publishShadow: (
    id: string,
    body: YouTubeDraft & { privacy: YouTubePrivacy; publish_at: string | null; account: string | null },
  ) => request<{ job_id: string }>(`/api/shadow/${id}/youtube`, json(body)),
}

export const shadowUrl = (id: string, kind: 'video' | 'audio' | 'srt' | 'timeline', download = false) =>
  `/api/shadow/${id}/${kind}${download ? '?download=true' : ''}`

export const audioUrl = (id: string, format: 'wav' | 'mp3' = 'wav', download = false) =>
  `/api/history/${id}/audio?format=${format}${download ? '&download=true' : ''}`

export const previewUrl = (voice: string) =>
  `/api/${voice.startsWith('kokoro:') ? 'english/' : ''}voices/${encodeURIComponent(voice)}/preview`

/** Hỏi trạng thái job đến khi xong; gọi onProgress mỗi lần cập nhật. */
export async function waitForJob<R>(id: string, onProgress?: (job: Job<R>) => void): Promise<R> {
  for (;;) {
    const job = await api.job<R>(id)
    onProgress?.(job)
    if (job.status === 'done') return job.result as R
    if (job.status === 'error') throw new Error(job.error ?? 'Có lỗi khi xử lý.')
    await new Promise((r) => setTimeout(r, 600))
  }
}

/** Nghe thử giọng: file có sẵn thì phát ngay, chưa có thì chờ máy tạo. */
export async function fetchPreview(voice: string): Promise<string> {
  const res = await fetch(previewUrl(voice))
  if (!res.ok) throw new Error('Không nghe thử được giọng này.')
  if (res.headers.get('content-type')?.includes('application/json')) {
    const { job_id } = await res.json()
    await waitForJob(job_id)
  }
  return `${previewUrl(voice)}?t=${Date.now()}`
}
