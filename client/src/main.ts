import "./style.css";

import { createGame } from "./game/createGame";
import { ConnectionState, GameSocket } from "./network/GameSocket";

const app = document.querySelector<HTMLDivElement>("#app");

if (!app) {
  throw new Error("The app root element was not found.");
}

app.innerHTML = `
  <section class="lobby" id="lobby">
    <div class="lobby-brand"><span class="brand-mark">DF</span><span>DROP<span>FIRE</span></span></div>
    <p class="eyebrow">REAL-TIME MULTIPLAYER ARENA</p>
    <h1>Drop in.<br /><em>Own the arena.</em></h1>
    <p class="lobby-intro">Create a private match for your squad, or enter a six-character invite code to join the fight.</p>
    <div class="lobby-actions">
      <button class="test-button primary-action" id="create-room" type="button">Create a room <span>→</span></button>
      <div class="join-code"><input class="test-select" id="room-code-input" maxlength="6" placeholder="ENTER CODE" autocomplete="off" /><button class="test-button" id="join-room" type="button">Join</button></div>
    </div>
    <p id="lobby-message"></p>
    <div class="room-heading"><h2>Open rooms</h2><span>LIVE</span></div>
    <div id="room-list"></div>
  </section>
  <main class="shell" id="game-shell" hidden>
    <header class="topbar">
      <div class="brand">
        <div class="brand-mark">DF</div>
        <div>
          <h1>Dropfire</h1>
          <p>Multiplayer arena prototype - Milestone 1</p>
          <p class="player-id" id="player-id">You: waiting for player ID</p>
          <p class="player-id">Room: <span id="room-code"></span> <button id="copy-room-code" type="button">Copy room code</button></p>
        </div>
      </div>
      <div class="status" id="server-status" data-state="connecting">
        <span class="status-dot"></span>
        <span id="server-status-text">Connecting to server</span>
      </div>
    </header>

    <section class="layout">
      <div class="game-frame">
        <span class="stage-label">Weapon pickup arena</span>
        <div id="game-root"></div>
        <button class="mobile-fullscreen" id="mobile-fullscreen" type="button" hidden>⛶ Full screen</button>
      </div>

      <aside class="panel">
        <h2>Find a weapon</h2>
        <p>Everyone starts with fists. Stand near a knife, pistol, or rifle pickup and press E to equip it before another player does.</p>

        <div class="key-grid" aria-label="WASD movement keys">
          <span class="key">W</span>
          <span class="key">A</span>
          <span class="key">S</span>
          <span class="key">D</span>
        </div>

        <div class="lesson">
          <h2>Shared loot</h2>
          <p>The server removes a collected pickup and broadcasts the updated world to every player.</p>
        </div>

        <div class="test-panel">
          <h2>Test panel</h2>
          <p>Create a server-side test player, then send it to an available pickup without opening another browser.</p>
          <button class="test-button" id="spawn-test-bot" type="button">Add test player</button>
          <button class="test-button" id="respawn-test-bot" type="button">Respawn selected test player</button>
          <button class="test-button" id="reset-test-round" type="button">Reset test round</button>
          <button class="test-button" id="refill-weapons" type="button">Refill weapons</button>
          <label class="test-label" for="test-bot-select">Control</label>
          <select class="test-select" id="test-bot-select" disabled>
            <option value="">Add a test player first</option>
          </select>
          <div class="bot-dpad" aria-label="Move selected test player">
            <button class="test-button" data-bot-x="0" data-bot-y="-1" type="button">↑</button>
            <button class="test-button" data-bot-x="-1" data-bot-y="0" type="button">←</button>
            <button class="test-button" data-bot-x="0" data-bot-y="1" type="button">↓</button>
            <button class="test-button" data-bot-x="1" data-bot-y="0" type="button">→</button>
          </div>
          <div class="pickup-actions">
            <button class="test-button" data-pickup-id="knife-1" type="button">Get knife</button>
            <button class="test-button" data-pickup-id="pistol-1" type="button">Get pistol</button>
            <button class="test-button" data-pickup-id="rifle-1" type="button">Get rifle</button>
          </div>
        </div>
      </aside>
    </section>
  </main>
`;

const statusElement = document.querySelector<HTMLElement>("#server-status");
const statusText = document.querySelector<HTMLElement>("#server-status-text");
const playerIdElement = document.querySelector<HTMLElement>("#player-id");
const spawnTestBotButton = document.querySelector<HTMLButtonElement>("#spawn-test-bot");
const respawnTestBotButton = document.querySelector<HTMLButtonElement>("#respawn-test-bot");
const resetTestRoundButton = document.querySelector<HTMLButtonElement>("#reset-test-round");
const refillWeaponsButton = document.querySelector<HTMLButtonElement>("#refill-weapons");
const testBotSelect = document.querySelector<HTMLSelectElement>("#test-bot-select");
const pickupButtons = document.querySelectorAll<HTMLButtonElement>("[data-pickup-id]");
const botMoveButtons = document.querySelectorAll<HTMLButtonElement>("[data-bot-x]");
const lobby = document.querySelector<HTMLElement>("#lobby");
const gameShell = document.querySelector<HTMLElement>("#game-shell");
const createRoomButton = document.querySelector<HTMLButtonElement>("#create-room");
const joinRoomButton = document.querySelector<HTMLButtonElement>("#join-room");
const roomCodeInput = document.querySelector<HTMLInputElement>("#room-code-input");
const lobbyMessage = document.querySelector<HTMLElement>("#lobby-message");
const roomList = document.querySelector<HTMLElement>("#room-list");
const roomCodeElement = document.querySelector<HTMLElement>("#room-code");
const copyRoomCodeButton = document.querySelector<HTMLButtonElement>("#copy-room-code");
const gameFrame = document.querySelector<HTMLElement>(".game-frame");
const mobileFullscreenButton = document.querySelector<HTMLButtonElement>("#mobile-fullscreen");

interface TestPlayerState {
  id: string;
  weapon: string;
  alive: boolean;
  is_bot: boolean;
  owner_id: string | null;
}

let localPlayerId: string | null = null;
let currentRoomCode: string | null = null;
let gameSocket: GameSocket | null = null;

function usesMobileBattlefield(): boolean {
  return (
    navigator.maxTouchPoints > 0 &&
    window.matchMedia("(max-width: 820px)").matches
  );
}

async function enterMobileFullscreen(): Promise<void> {
  if (!gameFrame) return;

  try {
    await gameFrame.requestFullscreen();
    const orientation = screen.orientation as ScreenOrientation & {
      lock?: (orientation: "landscape") => Promise<void>;
    };
    await orientation.lock?.("landscape");
  } catch {
    // Some mobile browsers do not allow element fullscreen. The mobile layout still fills the viewport.
  }
}

function isTestPlayerState(value: unknown): value is TestPlayerState {
  if (typeof value !== "object" || value === null) {
    return false;
  }

  const player = value as Record<string, unknown>;
  return (
    typeof player.id === "string" &&
    typeof player.weapon === "string" &&
    typeof player.alive === "boolean" &&
    typeof player.is_bot === "boolean" &&
    (typeof player.owner_id === "string" || player.owner_id === null)
  );
}

function renderTestBots(players: TestPlayerState[]): void {
  if (!testBotSelect || !localPlayerId) {
    return;
  }

  const ownedBots = players.filter(
    (player) => player.is_bot && player.owner_id === localPlayerId,
  );
  const previousSelection = testBotSelect.value;
  testBotSelect.innerHTML = "";

  if (ownedBots.length === 0) {
    testBotSelect.add(new Option("Add a test player first", ""));
    testBotSelect.disabled = true;
    return;
  }

  for (const [index, bot] of ownedBots.entries()) {
    const status = bot.alive ? bot.weapon : "ELIMINATED";
    testBotSelect.add(new Option(`Test player ${index + 1} · ${status}`, bot.id));
  }
  testBotSelect.disabled = false;
  testBotSelect.value = ownedBots.some((bot) => bot.id === previousSelection)
    ? previousSelection
    : ownedBots[0].id;
}

function renderConnectionState(state: ConnectionState): void {
  if (!statusElement || !statusText) {
    return;
  }

  const labels: Record<ConnectionState, string> = {
    connecting: "Connecting to server",
    connected: "Server connected",
    disconnected: "Server disconnected",
  };

  statusElement.dataset.state = state;
  statusText.textContent = labels[state];
}

function renderPlayerId(playerId: string): void {
  if (playerIdElement) {
    playerIdElement.textContent = `You: ${playerId.slice(0, 8)}`;
  }
}

function apiUrl(path: string): string {
  const configuredUrl = import.meta.env.VITE_API_URL as string | undefined;
  const localDevelopmentUrl = `${window.location.protocol}//${window.location.hostname}:8000`;
  const deployedUrl = window.location.origin;
  const baseUrl = configuredUrl
    ?? (import.meta.env.DEV ? localDevelopmentUrl : deployedUrl);
  return `${baseUrl.replace(/\/$/, "")}${path}`;
}

function startGame(roomCode: string): void {
  currentRoomCode = roomCode;
  const mobileBattlefield = usesMobileBattlefield();
  document.body.classList.toggle("mobile-battlefield", mobileBattlefield);
  if (mobileFullscreenButton) mobileFullscreenButton.hidden = !mobileBattlefield;
  roomCodeElement && (roomCodeElement.textContent = roomCode);
  lobby?.setAttribute("hidden", "");
  gameShell?.removeAttribute("hidden");
  gameSocket = new GameSocket(roomCode);
  createGame("game-root", gameSocket);
  gameSocket.onStateChange(renderConnectionState);
  gameSocket.onMessage((message) => {
  if (message.type === "server_connected" && typeof message.player_id === "string") {
    localPlayerId = message.player_id;
    renderPlayerId(message.player_id);
  }

  if (message.type === "world_state" && Array.isArray(message.players)) {
    renderTestBots(message.players.filter(isTestPlayerState));
  }
  });
  gameSocket.connect();
}

async function refreshRooms(): Promise<void> {
  const response = await fetch(apiUrl("/api/rooms"));
  const rooms = await response.json() as Array<{
    code: string;
    players: number;
    human_players: number;
    max_players: number;
    phase: string;
  }>;
  if (!roomList) return;
  roomList.innerHTML = "";
  for (const room of rooms) {
    const button = document.createElement("button");
    button.className = "test-button";
    button.textContent = `${room.code} · ${room.human_players} human · ${room.players}/${room.max_players} total · ${room.phase}`;
    button.addEventListener("click", () => startGame(room.code));
    roomList.append(button);
  }
}

createRoomButton?.addEventListener("click", async () => {
  const response = await fetch(apiUrl("/api/rooms"), { method: "POST" });
  const room = await response.json() as { code: string };
  startGame(room.code);
});
joinRoomButton?.addEventListener("click", () => {
  const code = roomCodeInput?.value.trim().toUpperCase() ?? "";
  if (/^[A-Z2-9]{6}$/.test(code)) startGame(code);
  else if (lobbyMessage) lobbyMessage.textContent = "Enter a six-character room code.";
});
copyRoomCodeButton?.addEventListener("click", async () => {
  if (currentRoomCode) await navigator.clipboard.writeText(currentRoomCode);
});
mobileFullscreenButton?.addEventListener("click", () => {
  void enterMobileFullscreen();
});
spawnTestBotButton?.addEventListener("click", () => gameSocket?.send({ type: "spawn_test_bot" }));
respawnTestBotButton?.addEventListener("click", () => {
  const playerId = testBotSelect?.value;
  if (playerId) {
    gameSocket?.send({ type: "debug_respawn_bot", player_id: playerId });
  }
});
resetTestRoundButton?.addEventListener("click", () =>
  gameSocket?.send({ type: "debug_reset_test_round" }),
);
refillWeaponsButton?.addEventListener("click", () =>
  gameSocket?.send({ type: "debug_reset_weapon_pickups" }),
);
for (const button of pickupButtons) {
  button.addEventListener("click", () => {
    const playerId = testBotSelect?.value;
    const pickupId = button.dataset.pickupId;
    if (playerId && pickupId) {
      gameSocket?.send({ type: "debug_collect_pickup", player_id: playerId, pickup_id: pickupId });
    }
  });
}
for (const button of botMoveButtons) {
  button.addEventListener("click", () => {
    const playerId = testBotSelect?.value;
    const directionX = Number(button.dataset.botX);
    const directionY = Number(button.dataset.botY);
    if (playerId) {
      gameSocket?.send({
        type: "debug_move_bot",
        player_id: playerId,
        direction_x: directionX,
        direction_y: directionY,
      });
    }
  });
}
void refreshRooms();
window.setInterval(() => {
  if (!lobby?.hasAttribute("hidden")) {
    void refreshRooms();
  }
}, 2000);

