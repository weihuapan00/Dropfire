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
        </div>
      </div>
      <div class="status" id="server-status" data-state="connecting">
        <span class="status-dot"></span>
        <span id="server-status-text">Connecting to server</span>
      </div>
    </header>

    <section class="layout">
      <div class="game-frame">
        <span class="stage-label">Local movement sandbox</span>
        <div id="game-root"></div>
      </div>

      <aside class="panel">
        <h2>Movement test</h2>
        <p>This first scene proves that Phaser rendering, input, and the game loop are working.</p>

        <div class="key-grid" aria-label="WASD movement keys">
          <span class="key">W</span>
          <span class="key">A</span>
          <span class="key">S</span>
          <span class="key">D</span>
        </div>

        <div class="lesson">
          <h2>Phaser concepts</h2>
          <p><code>create()</code> builds the scene once. <code>update()</code> runs every frame and moves the player.</p>
        </div>
      </aside>
    </section>
  </main>
`;

const statusElement = document.querySelector<HTMLElement>("#server-status");
const statusText = document.querySelector<HTMLElement>("#server-status-text");

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

createGame("game-root");

const gameSocket = new GameSocket();
gameSocket.onStateChange(renderConnectionState);
gameSocket.connect();

