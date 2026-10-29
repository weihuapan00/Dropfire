import "./style.css";

import { createGame } from "./game/createGame";
import { ConnectionState, GameSocket } from "./network/GameSocket";

const app = document.querySelector<HTMLDivElement>("#app");

if (!app) {
  throw new Error("The app root element was not found.");
}

app.innerHTML = `
  <main class="shell">
    <header class="topbar">
      <div class="brand">
        <div class="brand-mark">DF</div>
        <div>
          <h1>Dropfire</h1>
          <p>Multiplayer arena prototype - Milestone 1</p>
          <p class="player-id" id="player-id">You: waiting for player ID</p>
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
      </div>

      <aside class="panel">
        <h2>Find a weapon</h2>
        <p>Everyone starts with fists. Walk into a knife, pistol, or rifle pickup to equip it before another player does.</p>

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
const refillWeaponsButton = document.querySelector<HTMLButtonElement>("#refill-weapons");
const testBotSelect = document.querySelector<HTMLSelectElement>("#test-bot-select");
const pickupButtons = document.querySelectorAll<HTMLButtonElement>("[data-pickup-id]");
const botMoveButtons = document.querySelectorAll<HTMLButtonElement>("[data-bot-x]");

interface TestPlayerState {
  id: string;
  weapon: string;
  is_bot: boolean;
  owner_id: string | null;
}

let localPlayerId: string | null = null;

function isTestPlayerState(value: unknown): value is TestPlayerState {
  if (typeof value !== "object" || value === null) {
    return false;
  }

  const player = value as Record<string, unknown>;
  return (
    typeof player.id === "string" &&
    typeof player.weapon === "string" &&
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
    testBotSelect.add(new Option(`Test player ${index + 1} · ${bot.weapon}`, bot.id));
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

const gameSocket = new GameSocket();
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
spawnTestBotButton?.addEventListener("click", () => gameSocket.send({ type: "spawn_test_bot" }));
refillWeaponsButton?.addEventListener("click", () =>
  gameSocket.send({ type: "debug_reset_weapon_pickups" }),
);
for (const button of pickupButtons) {
  button.addEventListener("click", () => {
    const playerId = testBotSelect?.value;
    const pickupId = button.dataset.pickupId;
    if (playerId && pickupId) {
      gameSocket.send({ type: "debug_collect_pickup", player_id: playerId, pickup_id: pickupId });
    }
  });
}
for (const button of botMoveButtons) {
  button.addEventListener("click", () => {
    const playerId = testBotSelect?.value;
    const directionX = Number(button.dataset.botX);
    const directionY = Number(button.dataset.botY);
    if (playerId) {
      gameSocket.send({
        type: "debug_move_bot",
        player_id: playerId,
        direction_x: directionX,
        direction_y: directionY,
      });
    }
  });
}
gameSocket.connect();

