export type Voice = {
  id: string
  name: string
  gender: 'male' | 'female' | string
  region: 'north' | 'central' | 'south' | null
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

export type HistoryItem = {
  id: string
  created: number
  text: string
  voice: string
  speed: number
  duration: number
  chars: number
}

export type Job<R = unknown> = {
  id: string
  kind: string
  status: 'queued' | 'running' | 'done' | 'error'
  progress: number
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
}

export const audioUrl = (id: string, format: 'wav' | 'mp3' = 'wav', download = false) =>
  `/api/history/${id}/audio?format=${format}${download ? '&download=true' : ''}`

export const previewUrl = (voice: string) => `/api/voices/${encodeURIComponent(voice)}/preview`

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
