// AI 问答接口: 配置查询走 axios, 流式问答走 fetch(axios 不支持读取 SSE 流)
import request from './request'

// 查询 AI 配置(是否启用 + 预设问题)
export const aiConfig = () => request.get('/api/ai/config')

/**
 * 流式提问: 以 SSE 逐帧接收回答
 * @param {Object} payload  { article_id, question, scope }
 * @param {Object} handlers { onSources, onDelta, onDone, onError }
 * @returns {Function} 中断函数, 调用后停止接收
 */
export const askAi = (payload, handlers) => {
  // 中断控制器: 用户离开页面或重新提问时取消旧请求
  const controller = new AbortController()

  const run = async () => {
    const resp = await fetch('/api/ai/ask', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      signal: controller.signal
    })
    // 非流式错误(429 限流 / 503 未启用等), 读取 JSON 中的提示信息
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}))
      throw new Error(err.message || '请求失败')
    }
    // 逐块读取响应流并按 SSE 协议解析
    const reader = resp.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      // SSE 消息以空行分隔, 不完整的尾部留在缓冲中
      const frames = buffer.split('\n\n')
      buffer = frames.pop()
      for (const frame of frames) {
        // 解析每帧的 event 与 data 行
        let event = 'message'
        let data = ''
        for (const line of frame.split('\n')) {
          if (line.startsWith('event: ')) event = line.slice(7)
          else if (line.startsWith('data: ')) data = line.slice(6)
        }
        const parsed = data ? JSON.parse(data) : {}
        // 按事件类型分发给调用方
        if (event === 'sources') handlers.onSources?.(parsed.sources)
        else if (event === 'delta') handlers.onDelta?.(parsed.text)
        else if (event === 'done') handlers.onDone?.()
        else if (event === 'error') throw new Error(parsed.message)
      }
    }
  }

  // 主动中断不算错误, 其余异常交给 onError
  run().catch((e) => {
    if (e.name !== 'AbortError') handlers.onError?.(e.message || '网络异常')
  })

  return () => controller.abort()
}
