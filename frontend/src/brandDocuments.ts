import { apiBase } from './serverApi'

export type BrandDocument = { id: string; title: string; category: string; version: string; is_active: boolean; source_filename?: string | null; created_at?: string; chunks_count?: number }

export async function listBrandDocuments(): Promise<BrandDocument[]> {
  const response = await fetch(`${apiBase}/brand-docs`)
  if (!response.ok) throw new Error(`Server returned ${response.status}`)
  const data: unknown = await response.json()
  if (!data || typeof data !== 'object' || !('documents' in data) || !Array.isArray(data.documents)) throw new Error('Unexpected document list response.')
  return data.documents as BrandDocument[]
}
