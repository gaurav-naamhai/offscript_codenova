import { serverApi } from './serverApi'
import type { BrandDocument } from './serverApi'

export type { BrandDocument }

export async function listBrandDocuments(includeInactive = false): Promise<BrandDocument[]> {
  return serverApi.listBrandDocs(includeInactive)
}
