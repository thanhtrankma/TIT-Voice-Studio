import { Check, Loader2, Pause, Play, Search, Star } from 'lucide-react'
import { useMemo, useState } from 'react'
import type { Voice } from '../api'
import { avatarGradient, initials, voiceTags } from '../lib/voices'
import { usePreview } from './PreviewPlayer'

type Props = { voices: Voice[]; selected: string | null; onSelect: (id: string) => void }

const GENDERS = [
  { id: 'all', label: 'Tất cả' },
  { id: 'female', label: 'Nữ' },
  { id: 'male', label: 'Nam' },
]
const REGIONS = [
  { id: 'north', label: 'Bắc' },
  { id: 'central', label: 'Trung' },
  { id: 'south', label: 'Nam' },
]

export function VoiceAvatar({ name, size = 44 }: { name: string; size?: number }) {
  return (
    <div
      className={`grid shrink-0 place-items-center rounded-full bg-gradient-to-br ${avatarGradient(name)} font-semibold text-white shadow-inner`}
      style={{ width: size, height: size, fontSize: size * 0.34 }}
    >
      {initials(name)}
    </div>
  )
}

export function PreviewButton({ voice, className = '' }: { voice: string; className?: string }) {
  const preview = usePreview()
  const active = preview.voice === voice
  return (
    <button
      type="button"
      onClick={(e) => {
        e.stopPropagation()
        preview.toggle(voice)
      }}
      className={`grid size-9 shrink-0 place-items-center rounded-full border transition ${
        active ? 'border-brand-500 bg-brand-500 text-white' : 'border-line bg-white text-ink hover:border-brand-400 hover:text-brand-600'
      } ${className}`}
      aria-label={active ? `Dừng nghe ${voice}` : `Nghe thử ${voice}`}
      title={active ? 'Dừng' : 'Nghe thử'}
    >
      {active && preview.loading ? (
        <Loader2 size={15} className="animate-spin" />
      ) : active ? (
        <Pause size={14} fill="currentColor" />
      ) : (
        <Play size={14} fill="currentColor" className="ml-0.5" />
      )}
    </button>
  )
}

export default function VoiceLibrary({ voices, selected, onSelect }: Props) {
  const [query, setQuery] = useState('')
  const [gender, setGender] = useState('all')
  const [region, setRegion] = useState<string | null>(null)

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    return voices.filter(
      (v) =>
        (gender === 'all' || v.gender === gender) &&
        (!region || v.region === region) &&
        (!q || `${v.name} ${v.description}`.toLowerCase().includes(q)),
    )
  }, [voices, query, gender, region])

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="space-y-3 px-5 pb-3">
        <label className="flex items-center gap-2 rounded-xl border border-line bg-canvas px-3 py-2 focus-within:border-brand-400 focus-within:bg-white">
          <Search size={16} className="text-muted" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Tìm giọng theo tên, phong cách…"
            className="w-full bg-transparent text-sm outline-none placeholder:text-zinc-400"
          />
        </label>
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex rounded-full bg-canvas p-1">
            {GENDERS.map((g) => (
              <button
                key={g.id}
                onClick={() => setGender(g.id)}
                className={`rounded-full px-3 py-1 text-xs font-medium transition ${
                  gender === g.id ? 'bg-white text-ink shadow-sm' : 'text-muted hover:text-ink'
                }`}
              >
                {g.label}
              </button>
            ))}
          </div>
          {REGIONS.map((r) => (
            <button
              key={r.id}
              onClick={() => setRegion(region === r.id ? null : r.id)}
              className={`rounded-full border px-3 py-1 text-xs font-medium transition ${
                region === r.id ? 'border-brand-400 bg-brand-50 text-brand-700' : 'border-line text-muted hover:text-ink'
              }`}
            >
              Giọng {r.label}
            </button>
          ))}
        </div>
      </div>

      <div className="max-h-[440px] min-h-0 flex-1 space-y-2 overflow-y-auto px-5 pb-4 lg:max-h-none">
        {filtered.map((v) => {
          const isSelected = v.id === selected
          return (
            <div
              key={v.id}
              role="button"
              tabIndex={0}
              onClick={() => onSelect(v.id)}
              onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && onSelect(v.id)}
              className={`group flex cursor-pointer items-center gap-3 rounded-2xl border p-3 transition ${
                isSelected
                  ? 'border-brand-400 bg-brand-50/60 ring-1 ring-brand-400'
                  : 'border-line bg-white hover:border-zinc-300 hover:shadow-sm'
              }`}
            >
              <div className="relative">
                <VoiceAvatar name={v.name} />
                {isSelected && (
                  <span className="absolute -right-0.5 -bottom-0.5 grid size-4 place-items-center rounded-full bg-brand-500 text-white ring-2 ring-white">
                    <Check size={10} strokeWidth={3.5} />
                  </span>
                )}
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-1.5">
                  <span className="truncate font-semibold">{v.name}</span>
                  {v.featured && <Star size={12} className="shrink-0 fill-amber-400 text-amber-400" />}
                </div>
                <div className="mt-1 flex flex-wrap gap-1">
                  {voiceTags(v).map((t) => (
                    <span key={t} className="rounded-md bg-canvas px-1.5 py-0.5 text-[11px] text-muted">
                      {t}
                    </span>
                  ))}
                </div>
              </div>
              <PreviewButton voice={v.id} />
            </div>
          )
        })}
        {!filtered.length && <p className="py-10 text-center text-sm text-muted">Không có giọng phù hợp.</p>}
      </div>
    </div>
  )
}
