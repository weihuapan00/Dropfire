import "./style.css";

import { createGame } from "./game/createGame";
import { ConnectionState, GameSocket } from "./network/GameSocket";
import { soundscape } from "./audio/Soundscape";

const MAX_ROOM_PLAYERS = 8;

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
      <input class="test-select name-input" id="player-name-input" maxlength="16" placeholder="YOUR NAME (optional)" autocomplete="off" />
      <button class="test-button primary-action" id="create-room" type="button">Create a room <span>→</span></button>
      <div class="join-code"><input class="test-select" id="room-code-input" maxlength="6" placeholder="ENTER CODE" autocomplete="off" /><button class="test-button" id="join-room" type="button">Join</button></div>
    </div>
    <p id="lobby-message"></p>
    <div class="room-heading"><h2>Open rooms</h2><span>LIVE</span></div>
    <div id="room-list"></div>
  </section>
  <section class="room-lobby" id="room-lobby" hidden>
    <div class="lobby-brand"><span class="brand-mark">DF</span><span>DROP<span>FIRE</span></span></div>
    <button class="audio-toggle leave-button" id="leave-waiting-room" type="button">← Leave room</button>
    <p class="eyebrow">PRIVATE MATCH</p>
    <h1>Room <em id="waiting-room-code">------</em></h1>
    <p class="lobby-intro">Wait for real players, add up to three AI opponents, then start when you are ready.</p>
    <div class="room-heading"><h2>Players</h2><span id="waiting-player-count">0 / 8</span></div>
    <ul class="waiting-player-list" id="waiting-player-list"></ul>
    <button class="test-button primary-action" id="add-ai-bot" type="button">Add AI bot <span>+</span></button>
    <button class="test-button start-match" id="start-match" type="button" disabled>Start match <span>→</span></button>
    <p id="waiting-message" class="waiting-message">Connecting to room…</p>
    <section class="lobby-rules">
      <h2>How to play</h2>
      <p><strong>Desktop:</strong> WASD / arrows move · mouse aims and fires · E picks up · R reloads · G switches weapon.</p>
      <p><strong>Mobile:</strong> left stick moves · right stick aims and holds to fire · use SWITCH / PICK / RELOAD buttons.</p>
      <p><strong>Two weapon slots:</strong> MELEE (fists or knife) and GUN (pistol or rifle). Press G / SWITCH to swap; pick up a gun to fill the empty GUN slot.</p>
      <p><strong>Phone tip:</strong> tap <em>Fullscreen</em>, or add Dropfire to your home screen to launch without browser tabs.</p>
      <p>Matches last 3 minutes. Ranking uses kills, then total damage. Everyone starts with fists; scarce one-shot knives, pistols, and rifles must be found.</p>
    </section>
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
      <button class="audio-toggle" id="audio-toggle" type="button" aria-pressed="true">♫ Music: On</button>
      <button class="audio-toggle leave-button" id="leave-room" type="button">← Leave</button>
    </header>

    <section class="layout">
      <div class="game-frame">
        <div id="game-root"></div>
        <button class="mobile-fullscreen" id="mobile-fullscreen" type="button" hidden>⛶ Fullscreen</button>
        <button class="mobile-fullscreen mobile-leave" id="mobile-leave" type="button" hidden>← Leave</button>
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
      </aside>
    </section>
    <div class="match-end-overlay" id="match-end-overlay" hidden>
      <div class="match-end-card">
        <p class="eyebrow">ROUND OVER</p>
        <h2 id="match-end-title">MATCH OVER</h2>
        <ol id="match-end-top" class="match-end-top"></ol>
        <p id="match-end-your-stats" class="match-end-stats"></p>
        <p id="match-end-countdown" class="match-end-countdown"></p>
        <button class="test-button primary-action" id="match-end-next" type="button">Play again →</button>
      </div>
    </div>
  </main>
`;

const statusElement = document.querySelector<HTMLElement>("#server-status");
const statusText = document.querySelector<HTMLElement>("#server-status-text");
const playerIdElement = document.querySelector<HTMLElement>("#player-id");
const lobby = document.querySelector<HTMLElement>("#lobby");
const roomLobby = document.querySelector<HTMLElement>("#room-lobby");
const gameShell = document.querySelector<HTMLElement>("#game-shell");
const createRoomButton = document.querySelector<HTMLButtonElement>("#create-room");
const joinRoomButton = document.querySelector<HTMLButtonElement>("#join-room");
const playerNameInput = document.querySelector<HTMLInputElement>("#player-name-input");
const roomCodeInput = document.querySelector<HTMLInputElement>("#room-code-input");
const lobbyMessage = document.querySelector<HTMLElement>("#lobby-message");
const roomList = document.querySelector<HTMLElement>("#room-list");
const roomCodeElement = document.querySelector<HTMLElement>("#room-code");
const copyRoomCodeButton = document.querySelector<HTMLButtonElement>("#copy-room-code");
const gameFrame = document.querySelector<HTMLElement>(".game-frame");
const mobileFullscreenButton = document.querySelector<HTMLButtonElement>("#mobile-fullscreen");
const mobileLeaveButton = document.querySelector<HTMLButtonElement>("#mobile-leave");
const audioToggleButton = document.querySelector<HTMLButtonElement>("#audio-toggle");
const leaveRoomButton = document.querySelector<HTMLButtonElement>("#leave-room");
const leaveWaitingRoomButton = document.querySelector<HTMLButtonElement>("#leave-waiting-room");
const waitingRoomCode = document.querySelector<HTMLElement>("#waiting-room-code");
const waitingPlayerCount = document.querySelector<HTMLElement>("#waiting-player-count");
const waitingPlayerList = document.querySelector<HTMLUListElement>("#waiting-player-list");
const waitingMessage = document.querySelector<HTMLElement>("#waiting-message");
const addAiBotButton = document.querySelector<HTMLButtonElement>("#add-ai-bot");
const startMatchButton = document.querySelector<HTMLButtonElement>("#start-match");
const matchEndOverlay = document.querySelector<HTMLElement>("#match-end-overlay");
const matchEndTitle = document.querySelector<HTMLElement>("#match-end-title");
const matchEndTop = document.querySelector<HTMLElement>("#match-end-top");
const matchEndYourStats = document.querySelector<HTMLElement>("#match-end-your-stats");
const matchEndCountdown = document.querySelector<HTMLElement>("#match-end-countdown");
const matchEndNextButton = document.querySelector<HTMLButtonElement>("#match-end-next");

interface WaitingPlayerState {
  id: string;
  name: string | null;
  is_bot: boolean;
  connected: boolean;
  is_host: boolean;
}

interface WaitingRoundState {
  phase: "waiting" | "active" | "ending";
  number: number;
  winner_id: string | null;
  ends_in_seconds: number;
}

interface MatchResultPlayer {
  id: string;
  name: string | null;
  is_bot: boolean;
  kills: number;
  damage_dealt: number;
  is_host: boolean;
}

let localPlayerId: string | null = null;
let currentRoomCode: string | null = null;
let gameSocket: GameSocket | null = null;
let phaserGame: ReturnType<typeof createGame> | null = null;

function renderMusicToggle(): void {
  if (!audioToggleButton) return;
  const enabled = soundscape.isMusicEnabled();
  audioToggleButton.textContent = enabled ? "♫ Music: On" : "♫ Music: Off";
  audioToggleButton.setAttribute("aria-pressed", String(enabled));
}
let arenaStarted = false;
const LAST_ROOM_STORAGE_KEY = "dropfire-last-room-code";
const PLAYER_NAME_STORAGE_KEY = "dropfire-player-name";

function getPlayerName(): string {
  return playerNameInput?.value.trim() ?? "";
}

function usesMobileBattlefield(): boolean {
  return (
    navigator.maxTouchPoints > 0 &&
    window.matchMedia("(max-width: 820px)").matches
  );
}

function isFullscreen(): boolean {
  return document.fullscreenElement !== null;
}

function renderFullscreenButton(): void {
  if (!mobileFullscreenButton) return;
  mobileFullscreenButton.textContent = isFullscreen() ? "⛶ Exit fullscreen" : "⛶ Fullscreen";
}

async function toggleMobileFullscreen(): Promise<void> {
  if (!gameFrame) return;

  try {
    if (isFullscreen()) {
      await document.exitFullscreen();
      return;
    }
    await gameFrame.requestFullscreen();
    const orientation = screen.orientation as ScreenOrientation & {
      lock?: (orientation: "landscape") => Promise<void>;
    };
    await orientation.lock?.("landscape");
  } catch {
    // Some mobile browsers do not allow element fullscreen. The mobile layout still fills the viewport.
  } finally {
    renderFullscreenButton();
  }
}

function isWaitingPlayerState(value: unknown): value is WaitingPlayerState {
  if (typeof value !== "object" || value === null) {
    return false;
  }

  const player = value as Record<string, unknown>;
  return (
    typeof player.id === "string" &&
    (typeof player.name === "string" || player.name === null) &&
    typeof player.is_bot === "boolean" &&
    typeof player.connected === "boolean" &&
    typeof player.is_host === "boolean"
  );
}

function isWaitingRoundState(value: unknown): value is WaitingRoundState {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const round = value as Record<string, unknown>;
  return (
    ["waiting", "active", "ending"].includes(round.phase as string)
    && typeof round.number === "number"
    && (round.winner_id === null || typeof round.winner_id === "string")
    && typeof round.ends_in_seconds === "number"
  );
}

function isMatchResultPlayer(value: unknown): value is MatchResultPlayer {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const player = value as Record<string, unknown>;
  return (
    typeof player.id === "string"
    && (typeof player.name === "string" || player.name === null)
    && typeof player.is_bot === "boolean"
    && typeof player.kills === "number"
    && typeof player.damage_dealt === "number"
    && typeof player.is_host === "boolean"
  );
}

function renderWaitingRoom(players: WaitingPlayerState[], round: WaitingRoundState): void {
  if (!waitingPlayerList || !waitingPlayerCount) {
    return;
  }
  waitingPlayerCount.textContent = `${players.length} / ${MAX_ROOM_PLAYERS}`;
  waitingPlayerList.innerHTML = "";
  for (const player of players) {
    const item = document.createElement("li");
    const identity = player.is_bot ? "AI BOT" : player.name ?? `HUMAN P-${player.id.slice(0, 6)}`;
    const self = player.id === localPlayerId ? " · YOU" : "";
    const host = player.is_host ? " · HOST" : "";
    const connection = player.connected ? "READY" : "RECONNECTING";
    item.textContent = `${identity}${self}${host} · ${connection}`;
    item.dataset.kind = player.is_bot ? "bot" : "human";
    waitingPlayerList.append(item);
  }
  const localPlayerIsHost = players.some(
    (player) => player.id === localPlayerId && player.is_host,
  );
  if (addAiBotButton) {
    addAiBotButton.disabled = !localPlayerIsHost || players.length >= MAX_ROOM_PLAYERS || round.phase !== "waiting";
  }
  if (startMatchButton) {
    startMatchButton.disabled = !localPlayerIsHost || players.length < 2 || round.phase !== "waiting";
  }
}

function resultPlayerName(player: MatchResultPlayer): string {
  if (player.name) return player.name;
  if (player.is_bot) return "BOT";
  return `P${player.id.slice(0, 4)}`;
}

function renderMatchEnd(players: MatchResultPlayer[], round: WaitingRoundState): void {
  if (!matchEndOverlay) return;

  const ranked = [...players].sort(
    (left, right) => right.kills - left.kills || right.damage_dealt - left.damage_dealt,
  );

  const winner = round.winner_id
    ? players.find((player) => player.id === round.winner_id)
    : undefined;
  if (matchEndTitle) {
    matchEndTitle.textContent = winner ? `${resultPlayerName(winner)} WINS` : "DRAW";
  }

  if (matchEndTop) {
    matchEndTop.innerHTML = "";
    ranked.slice(0, 3).forEach((player, index) => {
      const item = document.createElement("li");
      const crown = index === 0 ? "🏆 " : "";
      item.textContent = `${crown}${index + 1}. ${resultPlayerName(player)} — ${player.kills} K · ${Math.round(player.damage_dealt)} DMG`;
      matchEndTop.append(item);
    });
  }

  const local = players.find((player) => player.id === localPlayerId);
  if (matchEndYourStats) {
    const rank = ranked.findIndex((player) => player.id === localPlayerId) + 1;
    matchEndYourStats.textContent = local
      ? `Your stats: #${rank} · ${local.kills} kills · ${Math.round(local.damage_dealt)} damage`
      : "Your stats: offline";
  }

  if (matchEndCountdown) {
    matchEndCountdown.textContent = `Next round in ${Math.ceil(round.ends_in_seconds)}s`;
  }

  if (matchEndNextButton) {
    const isHost = local?.is_host ?? false;
    matchEndNextButton.disabled = !isHost;
    matchEndNextButton.textContent = isHost ? "Play again →" : "Waiting for host…";
  }

  matchEndOverlay.hidden = false;
}

function hideMatchEnd(): void {
  if (matchEndOverlay) matchEndOverlay.hidden = true;
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

function launchArena(): void {
  if (arenaStarted || !gameSocket) return;
  arenaStarted = true;
  const mobileBattlefield = usesMobileBattlefield();
  document.body.classList.toggle("mobile-battlefield", mobileBattlefield);
  if (mobileFullscreenButton) mobileFullscreenButton.hidden = !mobileBattlefield;
  if (mobileLeaveButton) mobileLeaveButton.hidden = !mobileBattlefield;
  renderFullscreenButton();
  roomLobby?.setAttribute("hidden", "");
  gameShell?.removeAttribute("hidden");
  phaserGame = createGame("game-root", gameSocket, localPlayerId);
  gameSocket.onStateChange(renderConnectionState);
}

function enterRoom(roomCode: string): void {
  currentRoomCode = roomCode;
  arenaStarted = false;
  hideMatchEnd();
  sessionStorage.setItem(LAST_ROOM_STORAGE_KEY, roomCode);
  window.history.replaceState(null, "", `?room=${encodeURIComponent(roomCode)}`);
  roomCodeElement && (roomCodeElement.textContent = roomCode);
  waitingRoomCode && (waitingRoomCode.textContent = roomCode);
  waitingMessage && (waitingMessage.textContent = "Connecting to room…");
  lobby?.setAttribute("hidden", "");
  roomLobby?.removeAttribute("hidden");
  gameSocket = new GameSocket(roomCode, getPlayerName());
  gameSocket.onStateChange((state) => {
    renderConnectionState(state);
    if (state === "disconnected" && waitingMessage) {
      waitingMessage.textContent = "Reconnecting to room…";
    }
  });
  gameSocket.onMessage((message) => {
    if (message.type === "room_not_found" || message.type === "room_full") {
      if (lobbyMessage) {
        lobbyMessage.textContent = message.type === "room_not_found"
          ? "Room not found."
          : "Room is full.";
      }
      returnToLobby();
      return;
    }

    if (message.type === "server_connected" && typeof message.player_id === "string") {
      localPlayerId = message.player_id;
      renderPlayerId(message.player_id);
      if (waitingMessage) waitingMessage.textContent = "Waiting for players…";
    }

    if (
      message.type === "world_state" &&
      Array.isArray(message.players) &&
      isWaitingRoundState(message.round)
    ) {
      if (message.round.phase === "ending") {
        renderMatchEnd(message.players.filter(isMatchResultPlayer), message.round);
      } else {
        hideMatchEnd();
        renderWaitingRoom(message.players.filter(isWaitingPlayerState), message.round);
        if (message.round.phase === "active") {
          launchArena();
        }
      }
    }
  });
  gameSocket.connect();
}

function returnToLobby(): void {
  gameSocket?.close();
  gameSocket = null;
  phaserGame?.destroy(true);
  phaserGame = null;
  hideMatchEnd();
  arenaStarted = false;
  currentRoomCode = null;
  sessionStorage.removeItem(LAST_ROOM_STORAGE_KEY);
  window.history.replaceState(null, "", window.location.pathname);
  gameShell?.setAttribute("hidden", "");
  roomLobby?.setAttribute("hidden", "");
  lobby?.removeAttribute("hidden");
  document.body.classList.remove("mobile-battlefield");
  void refreshRooms();
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
    button.addEventListener("click", () => enterRoom(room.code));
    roomList.append(button);
  }
}

createRoomButton?.addEventListener("click", async () => {
  const response = await fetch(apiUrl("/api/rooms"), { method: "POST" });
  if (!response.ok) {
    if (lobbyMessage) {
      lobbyMessage.textContent = response.status === 503
        ? "Server is at room capacity — try again in a minute."
        : "Could not create a room — try again.";
    }
    return;
  }
  const room = await response.json() as { code: string };
  enterRoom(room.code);
});
joinRoomButton?.addEventListener("click", () => {
  const code = roomCodeInput?.value.trim().toUpperCase() ?? "";
  if (/^[A-Z2-9]{6}$/.test(code)) enterRoom(code);
  else if (lobbyMessage) lobbyMessage.textContent = "Enter a six-character room code.";
});
copyRoomCodeButton?.addEventListener("click", async () => {
  if (currentRoomCode) await navigator.clipboard.writeText(currentRoomCode);
});
mobileFullscreenButton?.addEventListener("click", () => {
  void toggleMobileFullscreen();
});
mobileLeaveButton?.addEventListener("click", returnToLobby);
document.addEventListener("fullscreenchange", renderFullscreenButton);
audioToggleButton?.addEventListener("click", () => {
  soundscape.toggleMusic();
  renderMusicToggle();
});
leaveWaitingRoomButton?.addEventListener("click", returnToLobby);
leaveRoomButton?.addEventListener("click", returnToLobby);
matchEndNextButton?.addEventListener("click", () => gameSocket?.send({ type: "next_round" }));
renderMusicToggle();
if (import.meta.env.PROD && "serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    void navigator.serviceWorker.register("/sw.js");
  });
}
if (playerNameInput) {
  playerNameInput.value = localStorage.getItem(PLAYER_NAME_STORAGE_KEY) ?? "";
}
playerNameInput?.addEventListener("input", () => {
  localStorage.setItem(PLAYER_NAME_STORAGE_KEY, playerNameInput.value);
});
addAiBotButton?.addEventListener("click", () => gameSocket?.send({ type: "add_ai_bot" }));
startMatchButton?.addEventListener("click", () => gameSocket?.send({ type: "start_match" }));
void refreshRooms();
window.setInterval(() => {
  if (!lobby?.hasAttribute("hidden")) {
    void refreshRooms();
  }
}, 2000);

function getSavedRoomCode(): string | null {
  const fromUrl = new URLSearchParams(window.location.search).get("room");
  const candidate = fromUrl ?? sessionStorage.getItem(LAST_ROOM_STORAGE_KEY);
  return candidate && /^[A-Z2-9]{6}$/.test(candidate.toUpperCase())
    ? candidate.toUpperCase()
    : null;
}

const savedRoomCode = getSavedRoomCode();
if (savedRoomCode) {
  enterRoom(savedRoomCode);
}

