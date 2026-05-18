/**
 * tokenUsageApi — 개발용 LLM 비용 누적 조회 / 리셋.
 *
 * Python backend (port 8000) 에 직통 fetch.
 * Java 경유 시 라우팅 미구현 → 401/500 + Java GlobalExceptionHandler 가 NoResourceFoundException
 * 로깅하므로 일부러 axiosClient 우회.
 *
 * dev 환경 전용. 실패 시 UI 가 자동 hide (TokenUsageBadge.fetchData catch).
 *
 * 환경변수: VITE_DIRECT_URL (없으면 localhost:8000 fallback).
 */

const DIRECT_URL: string = import.meta.env.VITE_DIRECT_URL || 'http://localhost:8000'

export interface BucketStats {
  input: number
  output: number
  cache_read: number
  cache_creation: number
  cost_usd: number
  calls: number
}

export interface TokenCumulative {
  total_calls: number
  total_input_tokens: number
  total_output_tokens: number
  total_cache_read_tokens: number
  total_cache_creation_tokens: number
  total_tokens: number
  total_cost_usd: number
  total_cost_krw: number
  usd_to_krw: number
  by_model: Record<string, BucketStats>
  by_node: Record<string, BucketStats>
  started_at: string | null
  updated_at: string | null
}

export async function getTokenCumulative(): Promise<TokenCumulative> {
  const res = await fetch(`${DIRECT_URL}/api/token_usage/cumulative`)
  if (!res.ok) throw new Error(`token_usage cumulative ${res.status}`)
  return res.json()
}

export async function resetTokenUsage(): Promise<{ ok: boolean; reset_at?: string; error?: string }> {
  const res = await fetch(`${DIRECT_URL}/api/token_usage/reset`, { method: 'POST' })
  if (!res.ok) throw new Error(`token_usage reset ${res.status}`)
  return res.json()
}
