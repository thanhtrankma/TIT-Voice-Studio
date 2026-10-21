import type { Voice } from '../api'

const GRADIENTS = [
  'from-rose-400 to-orange-300',
  'from-sky-400 to-indigo-400',
  'from-emerald-400 to-teal-300',
  'from-amber-400 to-pink-400',
  'from-violet-400 to-fuchsia-400',
  'from-cyan-400 to-blue-500',
  'from-lime-400 to-emerald-500',
  'from-orange-400 to-red-400',
]

export function avatarGradient(name: string) {
  let h = 0
  for (const c of name) h = (h * 31 + c.charCodeAt(0)) >>> 0
  return GRADIENTS[h % GRADIENTS.length]
}

export function initials(name: string) {
  const words = name.trim().split(/\s+/)
  return (words.length > 1 ? words[0][0] + words[words.length - 1][0] : words[0].slice(0, 2)).toUpperCase()
}

export const REGION_LABEL: Record<string, string> = { north: 'Bắc', central: 'Trung', south: 'Nam' }
export const GENDER_LABEL: Record<string, string> = { male: 'Nam', female: 'Nữ' }

export function voiceTags(v: Voice): string[] {
  const tags = [GENDER_LABEL[v.gender] ?? 'Khác']
  if (v.region) tags.push(`Giọng ${REGION_LABEL[v.region]}`)
  if (v.custom) tags.push('Nhân bản')
  else if (v.style) tags.push(v.style.replace(/^Phong cách /, '').replace(/^Giọng đọc /, ''))
  return tags
}
