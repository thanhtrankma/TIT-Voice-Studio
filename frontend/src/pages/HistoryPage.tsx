import { History, Trash2 } from 'lucide-react'
import { api, type HistoryItem } from '../api'
import AudioPlayer from '../components/AudioPlayer'

type Props = { items: HistoryItem[]; onChange: () => void }

export default function HistoryPage({ items, onChange }: Props) {
  async function remove(id: string) {
    if (!confirm('Xoá bản này khỏi lịch sử? File audio cũng bị xoá.')) return
    await api.deleteHistory(id)
    onChange()
  }

  return (
    <div className="mx-auto max-w-5xl space-y-4 p-5">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Lịch sử</h1>
          <p className="mt-1 text-sm text-muted">Mọi bản đã tạo được lưu trên máy bạn.</p>
        </div>
        <span className="text-sm text-muted">{items.length} bản</span>
      </div>

      {!items.length && (
        <div className="grid place-items-center gap-3 rounded-3xl border border-dashed border-line bg-white py-20 text-muted">
          <History size={28} />
          <p>Chưa có bản nào. Hãy tạo giọng nói đầu tiên.</p>
        </div>
      )}

      {items.map((item) => (
        <article key={item.id} className="space-y-3 rounded-3xl border border-line bg-white p-5">
          <div className="flex items-start justify-between gap-4">
            <p className="line-clamp-2 text-sm leading-relaxed text-ink">{item.text}</p>
            <button
              onClick={() => remove(item.id)}
              className="shrink-0 rounded-lg p-2 text-muted hover:bg-red-50 hover:text-red-600"
              aria-label="Xoá"
            >
              <Trash2 size={16} />
            </button>
          </div>
          <p className="text-xs text-muted">
            {new Date(item.created * 1000).toLocaleString('vi-VN')} · {item.voice} · {item.speed.toFixed(2)}x ·{' '}
            {item.chars.toLocaleString('vi-VN')} ký tự
          </p>
          <AudioPlayer item={item} />
        </article>
      ))}
    </div>
  )
}
