import { apiBase } from './serverApi'

export type ClientMetadata = {
  title: string
  audience: string
  channel: string
  context: string
  guidance: string
}

export const defaultMetadata: ClientMetadata = {
  title: 'Untitled submission',
  audience: '',
  channel: '',
  context: '',
  guidance: 'No brand guidance',
}

const META_KEY = `inkloom-server-metadata:${apiBase}`

export function readAllMetadata(): Record<string, ClientMetadata> {
  try {
    const raw = localStorage.getItem(META_KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw) as Record<string, ClientMetadata>
    return typeof parsed === 'object' && parsed !== null ? parsed : {}
  } catch {
    return {}
  }
}

export function readMetadata(id: string): ClientMetadata {
  const all = readAllMetadata()
  return all[id] || { ...defaultMetadata }
}

export function writeMetadata(id: string, metadata: ClientMetadata): { error: string } {
  try {
    const all = readAllMetadata()
    all[id] = metadata
    localStorage.setItem(META_KEY, JSON.stringify(all))
    return { error: '' }
  } catch {
    return { error: 'Could not save local title and details: browser storage is unavailable or full. These details are stored in this browser only.' }
  }
}

export function deleteMetadata(id: string): { error: string } {
  try {
    const all = readAllMetadata()
    delete all[id]
    localStorage.setItem(META_KEY, JSON.stringify(all))
    return { error: '' }
  } catch {
    return { error: 'Could not update local storage.' }
  }
}
