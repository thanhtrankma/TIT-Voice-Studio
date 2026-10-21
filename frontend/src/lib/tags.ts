export type TagKind = 'laugh' | 'sigh' | 'throat' | 'pause'

export type TagStyle = { label: string; emoji: string; className: string }

export const TAG_STYLES: Record<TagKind, TagStyle> = {
  laugh: { label: 'Cười', emoji: '😄', className: 'bg-amber-50 text-amber-700 ring-amber-200' },
  sigh: { label: 'Thở dài', emoji: '😮‍💨', className: 'bg-sky-50 text-sky-700 ring-sky-200' },
  throat: { label: 'Hắng giọng', emoji: '🗣️', className: 'bg-violet-50 text-violet-700 ring-violet-200' },
  pause: { label: 'Nghỉ', emoji: '⏸', className: 'bg-zinc-100 text-zinc-600 ring-zinc-200' },
}

/** Thẻ VieNeu hiểu được, ghi đúng như trong văn bản gửi đi. */
export const EMOTION_VALUES: Record<Exclude<TagKind, 'pause'>, string> = {
  laugh: 'cười',
  sigh: 'thở dài',
  throat: 'hắng giọng',
}

export const TAG_RE = /\[(cười|thở dài|hắng giọng|nghỉ\s+\d+(?:[.,]\d+)?\s*(?:ms|s))\]/gi

export function kindOf(value: string): TagKind {
  const v = value.toLowerCase()
  if (v.startsWith('nghỉ')) return 'pause'
  if (v === 'cười') return 'laugh'
  if (v === 'thở dài') return 'sigh'
  return 'throat'
}

export function tagLabel(value: string): string {
  const kind = kindOf(value)
  if (kind === 'pause') return `Nghỉ ${value.replace(/^nghỉ\s+/i, '')}`
  return TAG_STYLES[kind].label
}

type DocNode = { type: string; text?: string; attrs?: Record<string, string>; content?: DocNode[] }

/** Đổi văn bản thô (có thẻ [..]) thành tài liệu Tiptap với thẻ hiện thành chip. */
export function textToDoc(text: string): DocNode {
  const paragraphs = text.split(/\n/).map((line) => {
    const content: DocNode[] = []
    let pos = 0
    for (const m of line.matchAll(TAG_RE)) {
      if (m.index! > pos) content.push({ type: 'text', text: line.slice(pos, m.index) })
      content.push({ type: 'tag', attrs: { value: m[1].toLowerCase() } })
      pos = m.index! + m[0].length
    }
    if (pos < line.length) content.push({ type: 'text', text: line.slice(pos) })
    return { type: 'paragraph', ...(content.length ? { content } : {}) }
  })
  return { type: 'doc', content: paragraphs }
}
