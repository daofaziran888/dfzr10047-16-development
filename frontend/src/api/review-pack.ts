/** 结构复核包交接接口：导出下载、回填判读、核验、解析采用、证据与拒绝记录。 */
import { request } from './client'

export type AnyRecord = Record<string, any>

/** 与后端 seed 中第一个待回填旧包保持一致的兜底编号。 */
export const STORY_PACK_FALLBACK = 'SRP-A8-OLD'

export interface ApiResult {
  ok: boolean
  message?: string
  entry?: AnyRecord | null
  [key: string]: any
}

async function postJson(path: string, body: AnyRecord = {}): Promise<ApiResult> {
  const response = await request(path, {
    method: 'POST',
    body: JSON.stringify(body),
  })
  return (await response.json()) as ApiResult
}

async function getJson<T = any>(path: string): Promise<T> {
  const response = await request(path)
  if (!response.ok) throw new Error(`接口返回 ${response.status}`)
  return (await response.json()) as T
}

export async function fetchHandoffStory(): Promise<AnyRecord> {
  return getJson('/api/schema-review-handoff/story')
}

export async function advanceStory(): Promise<ApiResult> {
  return postJson('/api/schema-review-handoff/advance-story', {})
}

export async function fetchPackList(): Promise<{ items: AnyRecord[]; total: number }> {
  return getJson('/api/schema-review-packs')
}

export async function fetchPackDetail(ref: string | number): Promise<AnyRecord> {
  return getJson(`/api/schema-review-packs/${encodeURIComponent(String(ref))}`)
}

export async function createReviewPack(body: AnyRecord): Promise<ApiResult> {
  return postJson('/api/schema-review-packs', body)
}

export async function submitJudgment(ref: string | number, body: AnyRecord): Promise<ApiResult> {
  return postJson(`/api/schema-review-packs/${encodeURIComponent(String(ref))}/backfill`, body)
}

export async function verifyJudgment(ref: string | number, body: AnyRecord): Promise<ApiResult> {
  return postJson(`/api/schema-review-packs/${encodeURIComponent(String(ref))}/verify`, body)
}

export async function parsePack(ref: string | number, body: AnyRecord = {}): Promise<ApiResult> {
  return postJson(`/api/schema-review-packs/${encodeURIComponent(String(ref))}/parse`, body)
}

export async function refreshCurrent(ref: string | number): Promise<ApiResult> {
  return postJson(`/api/schema-review-packs/${encodeURIComponent(String(ref))}/refresh`, {})
}

export async function appendSegment(ref: string | number, body: AnyRecord): Promise<ApiResult> {
  return postJson(`/api/schema-review-packs/${encodeURIComponent(String(ref))}/append-segment`, body)
}

export async function fetchEvidence(ref: string | number, lineNo: number | string): Promise<ApiResult> {
  return getJson(
    `/api/schema-review-packs/${encodeURIComponent(String(ref))}/evidence?line_no=${encodeURIComponent(String(lineNo))}`,
  )
}

export async function fetchCrossBatchRejections(): Promise<{ items: AnyRecord[] }> {
  return getJson('/api/schema-review-rejections?category=cross_batch')
}

export function downloadPackUrl(ref: string | number, format: 'json' | 'csv' = 'json'): string {
  return `/api/schema-review-packs/${encodeURIComponent(String(ref))}/download?format=${format}`
}
