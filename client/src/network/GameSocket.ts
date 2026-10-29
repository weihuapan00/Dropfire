export type ConnectionState = "connecting" | "connected" | "disconnected";

type ConnectionListener = (state: ConnectionState) => void;
type MessageListener = (message: ServerMessage) => void;

interface ServerMessage {
  type: string;
  [key: string]: unknown;
}

export class GameSocket {
  private socket: WebSocket | null = null;
  private reconnectTimer: number | null = null;
  private reconnectAttempts = 0;
  private sessionToken = this.getSessionToken();
  private readonly listeners = new Set<ConnectionListener>();
  private readonly messageListeners = new Set<MessageListener>();

  constructor(private readonly roomCode: string) {}

  connect(): void {
    if (this.socket?.readyState === WebSocket.OPEN) {
      return;
    }

    this.emit("connecting");
    const socket = new WebSocket(this.getWebSocketUrl());
    this.socket = socket;

    socket.addEventListener("open", () => {
      this.reconnectAttempts = 0;
      this.emit("connected");
      this.send({ type: "client_ready" });
    });

    socket.addEventListener("message", (event) => {
      const message = JSON.parse(event.data) as ServerMessage;
      if (message.type === "server_connected" && typeof message.session_token === "string") {
        this.sessionToken = message.session_token;
        sessionStorage.setItem("dropfire-tab-session-token", this.sessionToken);
      }
      console.info("Server message:", message);
      this.emitMessage(message);
    });

    socket.addEventListener("close", () => {
      if (this.socket !== socket) return;
      this.emit("disconnected");
      this.scheduleReconnect();
    });

    socket.addEventListener("error", () => {
      this.emit("disconnected");
    });
  }

  send(message: ServerMessage): void {
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify(message));
    }
  }

  onStateChange(listener: ConnectionListener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  onMessage(listener: MessageListener): () => void {
    this.messageListeners.add(listener);
    return () => this.messageListeners.delete(listener);
  }

  private emit(state: ConnectionState): void {
    for (const listener of this.listeners) {
      listener(state);
    }
  }

  private emitMessage(message: ServerMessage): void {
    for (const listener of this.messageListeners) {
      listener(message);
    }
  }

  private getWebSocketUrl(): string {
    const configuredUrl = import.meta.env.VITE_WS_URL as string | undefined;
    const baseUrl = configuredUrl
      ?? `${window.location.protocol === "https:" ? "wss:" : "ws:"}//${window.location.hostname}:8000/ws`;
    return `${baseUrl.replace(/\/$/, "")}/${encodeURIComponent(this.roomCode)}?session=${encodeURIComponent(this.sessionToken)}`;
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer !== null) return;
    const delay = Math.min(1000 * 2 ** this.reconnectAttempts, 5000);
    this.reconnectAttempts += 1;
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, delay);
  }

  private getSessionToken(): string {
    const storageKey = "dropfire-tab-session-token";
    const existing = sessionStorage.getItem(storageKey);
    if (existing) return existing;
    const token = crypto.randomUUID();
    sessionStorage.setItem(storageKey, token);
    return token;
  }
}

