/** 统一请求封装：拼后端地址、带操作身份头、抛网络错误、给页脚留一句可读的说明。 */
import { useSessionStore } from '@/stores/session'

const API_BASE = import.meta.env.VITE_API_BASE ?? ''

function buildUrl(path: string): string {
  return path.startsWith('http') ? path : `${API_BASE}${path}`
}

/** 把当前登录角色带到后端（ASCII 登录标识 + 角色编码，规避 HTTP 头只支持 latin-1 的限制）。 */
function identityHeaders(): Record<string, string> {
  const session = useSessionStore()
  if (!session.operatorId) return {}
  return { 'X-Operator-Id': session.operatorId, 'X-Operator-Role': session.roleCode }
}

export function request(path: string, init?: RequestInit): Promise<Response> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json', ...identityHeaders() }
  return fetch(buildUrl(path), {
    ...init,
    headers: { ...headers, ...((init?.headers as Record<string, string>) ?? {}) },
  }).catch((error: unknown) => {
    const detail = error instanceof Error ? error.message : '请求未送达'
    throw new Error(`接口请求失败：${detail}`)
  })
}

export async function fetchJson<T>(path: string): Promise<T> {
  const response = await request(path)
  if (!response.ok) {
    const detail = await safeDetail(response)
    throw new Error(detail || `接口返回 ${response.status}，数据未更新`)
  }
  return (await response.json()) as T
}

/** 动作接口约定 HTTP 200 + ok=false 表达业务驳回；解析出统一结构。 */
export type ActionResponse = {
  ok: boolean
  message: string
  entry?: Record<string, unknown> | null
  role?: string
  missingPermission?: string
}

export async function postAction(path: string, body?: unknown): Promise<ActionResponse> {
  const response = await request(path, {
    method: 'POST',
    body: JSON.stringify(body ?? {}),
  })
  if (!response.ok) {
    const detail = await safeDetail(response)
    return { ok: false, message: detail || `接口返回 ${response.status}，操作未生效` }
  }
  return (await response.json()) as ActionResponse
}

export async function putAction(path: string, body?: unknown): Promise<ActionResponse> {
  const response = await request(path, {
    method: 'PUT',
    body: JSON.stringify(body ?? {}),
  })
  if (!response.ok) {
    const detail = await safeDetail(response)
    return { ok: false, message: detail || `接口返回 ${response.status}，操作未生效` }
  }
  return (await response.json()) as ActionResponse
}

async function safeDetail(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as { detail?: string }
    return payload.detail ?? ''
  } catch {
    return ''
  }
}
