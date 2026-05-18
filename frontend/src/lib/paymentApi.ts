import axiosClient from './axiosClient'

export interface Payment {
  id: number
  userId: number
  orderId: string
  paymentKey: string | null
  amount: number
  status: 'pending' | 'success' | 'failed' | 'cancelled'
  type: 'SUBSCRIPTION' | 'CREDIT'
  description: string
  planKey: string | null
  method: string | null
  nextBillingDate: string | null
  cancelledAt: string | null
  createdAt: string
}

export interface PlanLimitStatus {
  membership: string
  usedProjects: number
  maxProjects: number
  usedRedeploys: number
  maxRedeploys: number
  usedConcurrent: number
  maxConcurrent: number
  creditBalance: number
}

/** 일반결제 승인 */
export async function confirmPayment(params: {
  paymentKey: string
  orderId: string
  amount: number
  description: string
  planKey: string
}): Promise<Payment> {
  const res = await axiosClient.post('/payments/pay/confirm', params)
  return res.data
}

/** 현재 활성 구독 조회 (없으면 null) */
export async function getCurrentSubscription(): Promise<Payment | null> {
  const res = await axiosClient.get('/payments/current')
  return res.status === 204 ? null : res.data
}

/** 구독 취소 */
export async function cancelSubscription(): Promise<Payment> {
  const res = await axiosClient.post('/payments/subscription/cancel')
  return res.data
}

/** 결제 내역 조회 */
export async function getPaymentHistory(): Promise<Payment[]> {
  const res = await axiosClient.get('/payments/history')
  return res.data
}

export interface CreditTransaction {
  id: number
  userId: number
  amount: number
  type: 'PURCHASE' | 'USE_REDEPLOY' | 'USE_PROJECT'
  projectId: number | null
  projectName: string | null
  createdAt: string
}

/** 크레딧 이력 조회 */
export async function getCreditHistory(): Promise<CreditTransaction[]> {
  const res = await axiosClient.get('/me/credit-history')
  return res.data
}

/** 플랜 한도 현황 조회 */
export async function getPlanLimits(): Promise<PlanLimitStatus> {
  const res = await axiosClient.get('/me/plan-limits')
  return res.data
}

/** 크레딧 팩 구매 */
export async function purchaseCredits(params: {
  paymentKey: string
  orderId: string
  amount: number
  creditAmount: number
}): Promise<Payment> {
  const res = await axiosClient.post('/payments/credits/confirm', params)
  return res.data
}
