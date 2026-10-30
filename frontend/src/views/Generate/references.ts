// Референсы новой генерации: загруженные файлы и прошлые работы из галереи.
import { imageUrl } from '@/api/client'

export const MAX_REFS = 10
export const MAX_FILE_BYTES = 20 * 1024 * 1024
export const ACCEPTED_TYPES = ['image/png', 'image/jpeg', 'image/webp']

export type RefItem =
  | { key: string; kind: 'file'; file: File; url: string }
  | { key: string; kind: 'work'; generationId: number; url: string }

let seq = 0
const nextKey = () => `ref-${++seq}`

function objectUrl(file: File): string {
  // в jsdom createObjectURL нет — миниатюра тогда просто пустая
  return typeof URL.createObjectURL === 'function' ? URL.createObjectURL(file) : ''
}

export function fileRef(file: File): RefItem {
  return { key: nextKey(), kind: 'file', file, url: objectUrl(file) }
}

export function workRef(generationId: number): RefItem {
  return { key: nextKey(), kind: 'work', generationId, url: imageUrl(generationId, 'thumb') }
}

export function releaseRef(item: RefItem): void {
  if (item.kind === 'file' && item.url && typeof URL.revokeObjectURL === 'function') {
    URL.revokeObjectURL(item.url)
  }
}

/**
 * Проверяет новые файлы: тип (PNG, JPEG, WebP), размер до 20 МБ и общий лимит в 10 референсов.
 * Возвращает принятые файлы и тексты ошибок для отклонённых.
 */
export function checkFiles(files: readonly File[], already: number): { accepted: File[]; errors: string[] } {
  const accepted: File[] = []
  const errors: string[] = []
  for (const file of files) {
    if (!ACCEPTED_TYPES.includes(file.type)) {
      errors.push(`«${file.name}»: подходят только PNG, JPEG и WebP`)
    } else if (file.size > MAX_FILE_BYTES) {
      errors.push(`«${file.name}» больше 20 МБ`)
    } else if (already + accepted.length >= MAX_REFS) {
      errors.push(`«${file.name}» не добавлен: не больше ${MAX_REFS} референсов`)
    } else {
      accepted.push(file)
    }
  }
  return { accepted, errors }
}
