/**
 * HTTP 封装：统一 Result<T> 解包、traceId 生成与透传、401 跳登录。
 * 后端返回结构：{ code, message, data, traceId }，code=0 成功。
 */

export class ApiError extends Error {
  constructor(public code: number, message: string, public traceId: string) {
    super(message)
  }
}

function genTraceId(): string {
  return Math.random().toString(16).slice(2, 14)
}

export async function request<T>(method: string, url: string, body?: unknown): Promise<T> {
  const traceId = genTraceId()
  const token = localStorage.getItem('rv_token') ?? ''
  const resp = await fetch(url, {
    method,
    headers: {
      'Content-Type': 'application/json',
      'X-Trace-Id': traceId,
      Authorization: token,
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (resp.status === 401) {
    localStorage.removeItem('rv_token')
    window.location.hash = '#/login'
    throw new ApiError(401, '未登录', traceId)
  }
  const result = (await resp.json()) as { code: number; message: string; data: T; traceId: string }
  if (result.code !== 0) {
    throw new ApiError(result.code, result.message, result.traceId)
  }
  return result.data
}

export const http = {
  get: <T>(url: string) => request<T>('GET', url),
  post: <T>(url: string, body?: unknown) => request<T>('POST', url, body),
}
