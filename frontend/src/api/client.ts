/** 统一请求封装：拼后端地址、抛网络错误、给页脚留一句可读的说明。 */
const API_BASE = import.meta.env.VITE_API_BASE ?? ''

/**
 * 当前操作人身份（模拟登录态）：由会话 store 写入，所有请求自动带 X-Operator-Id。
 * 归属判定以服务端按此身份做出的结果为准，页面里手填的"填报人"一律无效。
 */
let operatorId = localStorage.getItem('pollutant-operator-id') || ''

export function setOperatorId(id: string) {
  operatorId = id
  if (id) {
    localStorage.setItem('pollutant-operator-id', id)
  } else {
    localStorage.removeItem('pollutant-operator-id')
  }
}

export function getOperatorId() {
  return operatorId
}

export function request(path: string, init?: RequestInit): Promise<Response> {
  const url = path.startsWith('http') ? path : `${API_BASE}${path}`
  const headers = new Headers(init?.headers ?? { 'Content-Type': 'application/json' })
  if (operatorId) {
    headers.set('X-Operator-Id', operatorId)
  }
  return fetch(url, { ...init, headers }).catch((error: unknown) => {
    const detail = error instanceof Error ? error.message : '请求未送达'
    throw new Error(`接口请求失败：${detail}`)
  })
}

export async function fetchJson<T>(path: string): Promise<T> {
  const response = await request(path)
  if (!response.ok) {
    throw new Error(`接口返回 ${response.status}，数据未更新`)
  }
  return (await response.json()) as T
}

/** 把 403 越权响应解析成可读文案（含当前角色与缺失权限点）。 */
export async function parseError(response: Response): Promise<string> {
  try {
    const payload = await response.json()
    const detail = payload.detail
    if (typeof detail === 'string') {
      return detail
    }
    if (detail?.message) {
      return detail.message
    }
  } catch {
    /* 非 JSON 响应时退回通用文案 */
  }
  return `接口返回 ${response.status}，操作未生效`
}
