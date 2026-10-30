import assert from "node:assert/strict";
import { createServer as createHttpServer } from "node:http";
import { after, before, beforeEach, test } from "node:test";
import { createServer } from "vite";

let vite;
let GameSocket;

class FakeWebSocket {
  static OPEN = 1;
  static instances = [];
  readyState = 0;
  listeners = new Map();

  constructor() {
    FakeWebSocket.instances.push(this);
  }

  addEventListener(type, listener) {
    this.listeners.set(type, listener);
  }

  receive(message) {
    this.listeners.get("message")({ data: JSON.stringify(message) });
  }
}

before(async () => {
  // Vite transforms TypeScript and import.meta.env exactly as it does for the app.
  vite = await createServer({
    server: { middlewareMode: true, watch: null, hmr: { server: createHttpServer() } },
    appType: "custom",
  });
  ({ GameSocket } = await vite.ssrLoadModule("/src/network/GameSocket.ts"));
});

beforeEach(() => {
  FakeWebSocket.instances = [];
  globalThis.WebSocket = FakeWebSocket;
  globalThis.window = { location: { protocol: "http:", hostname: "localhost" } };
  const storage = new Map();
  globalThis.sessionStorage = {
    getItem: (key) => storage.get(key) ?? null,
    setItem: (key, value) => storage.set(key, value),
  };
});

after(async () => {
  await vite?.close();
});

test("an arena opened after the lobby receives the map immediately", () => {
  const connection = new GameSocket("ABC234");
  connection.connect();
  const socket = FakeWebSocket.instances[0];
  const config = {
    type: "arena_config",
    covers: [{ id: "wall", x: 100, y: 200, width: 80, height: 40 }],
  };
  socket.receive(config);
  socket.receive({ type: "world_state", hits: [{ id: "old-hit" }] });

  const sceneMessages = [];
  connection.onMessage((message) => sceneMessages.push(message));

  assert.deepEqual(sceneMessages, [config]);
});

test("late subscribers receive the latest map, and unsubscribed listeners stay silent", () => {
  const connection = new GameSocket("ABC234");
  connection.connect();
  const socket = FakeWebSocket.instances[0];
  const firstConfig = { type: "arena_config", covers: [{ id: "first" }] };
  const latestConfig = { type: "arena_config", covers: [{ id: "latest" }] };
  const messages = [];
  const unsubscribe = connection.onMessage((message) => messages.push(message));
  socket.receive(firstConfig);
  unsubscribe();
  socket.receive(latestConfig);

  const lateMessages = [];
  connection.onMessage((message) => lateMessages.push(message));
  assert.deepEqual(messages, [firstConfig]);
  assert.deepEqual(lateMessages, [latestConfig]);
});
