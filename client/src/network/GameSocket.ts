export type ConnectionState = "connecting" | "connected" | "disconnected";

type ConnectionListener = (state: ConnectionState) => void;

interface ServerMessage {
  type: string;
  [key: string]: unknown;
}

export class GameSocket {
  private socket: WebSocket | null = null;
  private readonly listeners = new Set<ConnectionListener>();

  connect(): void {
    if (this.socket?.readyState === WebSocket.OPEN) {
      return;
    }

    this.emit("connecting");
    this.socket = new WebSocket(this.getWebSocketUrl());

    this.socket.addEventListener("open", () => {
      this.emit("connected");
      this.send({ type: "client_ready" });
    });

    this.socket.addEventListener("message", (event) => {
      const message = JSON.parse(event.data) as ServerMessage;
      console.info("Server message:", message);
    });

    this.socket.addEventListener("close", () => {
      this.emit("disconnected");
    });

    this.socket.addEventListener("error", () => {
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

  private emit(state: ConnectionState): void {
    for (const listener of this.listeners) {
      listener(state);
    }
  }

  private getWebSocketUrl(): string {
    const configuredUrl = import.meta.env.VITE_WS_URL as string | undefined;
    if (configuredUrl) {
      return configuredUrl;
    }

    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${protocol}//${window.location.hostname}:8000/ws`;
  }
}

