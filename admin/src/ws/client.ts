type EventCallback = (data: unknown) => void

export class WebSocketClient {
  private ws: WebSocket | null = null
  private url = ''
  private token = ''
  private listeners = new Map<string, Set<EventCallback>>()
  private reconnectAttempts = 0
  private maxReconnectAttempts = 10
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private _connected = false

  get connected(): boolean {
    return this._connected
  }

  connect(url: string, token: string): void {
    this.url = url
    this.token = token
    this.reconnectAttempts = 0
    this.doConnect()
  }

  private doConnect(): void {
    const separator = this.url.includes('?') ? '&' : '?'
    this.ws = new WebSocket(`${this.url}${separator}token=${this.token}`)

    this.ws.onopen = () => {
      this._connected = true
      this.reconnectAttempts = 0
      this.emit('connected', null)
    }

    this.ws.onmessage = (event: MessageEvent) => {
      try {
        const msg = JSON.parse(event.data as string)
        if (msg.type) {
          this.emit(msg.type, msg.data ?? msg)
        }
        this.emit('message', msg)
      } catch {
        this.emit('message', event.data)
      }
    }

    this.ws.onclose = () => {
      this._connected = false
      this.emit('disconnected', null)
      this.scheduleReconnect()
    }

    this.ws.onerror = () => {
      this.emit('error', null)
    }
  }

  private scheduleReconnect(): void {
    if (this.reconnectAttempts >= this.maxReconnectAttempts) return
    const delay = Math.min(1000 * 2 ** this.reconnectAttempts, 30000)
    this.reconnectAttempts++
    this.reconnectTimer = setTimeout(() => this.doConnect(), delay)
  }

  send(message: object): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(message))
    }
  }

  subscribe(channels: string[]): void {
    this.send({ action: 'subscribe', channels })
  }

  unsubscribe(channels: string[]): void {
    this.send({ action: 'unsubscribe', channels })
  }

  on(eventType: string, callback: EventCallback): void {
    if (!this.listeners.has(eventType)) {
      this.listeners.set(eventType, new Set())
    }
    this.listeners.get(eventType)!.add(callback)
  }

  off(eventType: string, callback: EventCallback): void {
    this.listeners.get(eventType)?.delete(callback)
  }

  private emit(eventType: string, data: unknown): void {
    this.listeners.get(eventType)?.forEach((cb) => cb(data))
  }

  disconnect(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    this.ws?.close()
    this.ws = null
    this._connected = false
  }
}

export const wsClient = new WebSocketClient()
