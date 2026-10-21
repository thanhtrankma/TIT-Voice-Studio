import { Check, Plus, Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { api } from '../api'

type Row = { word: string; reading: string }

export default function DictionaryPage() {
  const [rows, setRows] = useState<Row[]>([])
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    api.dictionary().then((d) => {
      const list = Object.entries(d).map(([word, reading]) => ({ word, reading }))
      setRows(list.length ? list : [{ word: 'KTX', reading: 'ký túc xá' }])
    })
  }, [])

  const update = (i: number, patch: Partial<Row>) => {
    setSaved(false)
    setRows((r) => r.map((row, j) => (j === i ? { ...row, ...patch } : row)))
  }

  async function save() {
    const entries = Object.fromEntries(rows.filter((r) => r.word.trim()).map((r) => [r.word, r.reading]))
    const clean = await api.saveDictionary(entries)
    setRows(Object.entries(clean).map(([word, reading]) => ({ word, reading })))
    setSaved(true)
  }

  return (
    <div className="mx-auto max-w-3xl space-y-4 p-5">
      <div>
        <h1 className="text-2xl font-semibold">Từ điển phát âm</h1>
        <p className="mt-1 text-sm text-muted">
          Đặt cách đọc cho từ viết tắt hoặc tên riêng. Áp dụng cho mọi lần tạo giọng, phân biệt chữ hoa thường.
        </p>
      </div>
      <div className="overflow-hidden rounded-3xl border border-line bg-white">
        <div className="grid grid-cols-[1fr_1.4fr_44px] gap-3 border-b border-line bg-canvas/60 px-5 py-2.5 text-xs font-medium text-muted">
          <span>Từ trong văn bản</span>
          <span>Đọc thành</span>
          <span />
        </div>
        {rows.map((row, i) => (
          <div key={i} className="grid grid-cols-[1fr_1.4fr_44px] items-center gap-3 border-b border-line px-5 py-2 last:border-0">
            <input
              value={row.word}
              onChange={(e) => update(i, { word: e.target.value })}
              placeholder="VD: SGK"
              className="rounded-lg border border-transparent px-2 py-1.5 font-medium outline-none hover:border-line focus:border-brand-400"
            />
            <input
              value={row.reading}
              onChange={(e) => update(i, { reading: e.target.value })}
              placeholder="VD: sách giáo khoa"
              className="rounded-lg border border-transparent px-2 py-1.5 outline-none hover:border-line focus:border-brand-400"
            />
            <button
              onClick={() => {
                setSaved(false)
                setRows((r) => r.filter((_, j) => j !== i))
              }}
              className="grid size-9 place-items-center rounded-lg text-muted hover:bg-red-50 hover:text-red-600"
              aria-label="Xoá dòng"
            >
              <Trash2 size={15} />
            </button>
          </div>
        ))}
      </div>
      <div className="flex items-center justify-between">
        <button
          onClick={() => setRows((r) => [...r, { word: '', reading: '' }])}
          className="inline-flex items-center gap-1.5 rounded-xl border border-line bg-white px-3.5 py-2 text-sm font-medium hover:border-zinc-300"
        >
          <Plus size={15} /> Thêm từ
        </button>
        <button onClick={save} className="btn-brand inline-flex items-center gap-1.5 rounded-xl px-5 py-2 text-sm font-semibold text-white">
          {saved && <Check size={15} />} {saved ? 'Đã lưu' : 'Lưu từ điển'}
        </button>
      </div>
    </div>
  )
}
