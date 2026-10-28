import Phaser from "phaser";

import { GameSocket } from "../../network/GameSocket";

const PLAYER_RADIUS = 20;

interface PlayerState {
  id: string;
  x: number;
  y: number;
}

function isPlayerState(value: unknown): value is PlayerState {
  if (typeof value !== "object" || value === null) {
    return false;
  }

  const player = value as Record<string, unknown>;
  return (
    typeof player.id === "string" &&
    typeof player.x === "number" &&
    typeof player.y === "number"
  );
}

export class ArenaScene extends Phaser.Scene {
  private readonly players = new Map<string, Phaser.GameObjects.Arc>();
  private localPlayerId: string | null = null;
  private localPlayer: Phaser.GameObjects.Arc | null = null;
  private aimLine!: Phaser.GameObjects.Graphics;
  private cursors!: Phaser.Types.Input.Keyboard.CursorKeys;
  private movementKeys!: Record<"up" | "down" | "left" | "right", Phaser.Input.Keyboard.Key>;

  constructor(private readonly gameSocket: GameSocket) {
    super("arena");
  }

  create(): void {
    this.drawArena();

    this.aimLine = this.add.graphics();

    this.gameSocket.onMessage((message) => {
      if (message.type === "server_connected" && typeof message.player_id === "string") {
        this.localPlayerId = message.player_id;
      }

      if (message.type === "world_state" && Array.isArray(message.players)) {
        this.syncPlayers(message.players.filter(isPlayerState));
      }
    });

    const keyboard = this.input.keyboard;
    if (!keyboard) {
      throw new Error("Keyboard input is unavailable.");
    }

    this.cursors = keyboard.createCursorKeys();
    this.movementKeys = keyboard.addKeys({
      up: Phaser.Input.Keyboard.KeyCodes.W,
      down: Phaser.Input.Keyboard.KeyCodes.S,
      left: Phaser.Input.Keyboard.KeyCodes.A,
      right: Phaser.Input.Keyboard.KeyCodes.D,
    }) as Record<"up" | "down" | "left" | "right", Phaser.Input.Keyboard.Key>;

    this.add
      .text(640, 650, "Move with WASD or arrow keys - Aim with the pointer", {
        color: "#96a3b6",
        fontFamily: "system-ui, sans-serif",
        fontSize: "18px",
      })
      .setOrigin(0.5);
  }

  update(_time: number, _delta: number): void {
    if (!this.localPlayer) {
      return;
    }

    const direction = new Phaser.Math.Vector2(
      this.getAxis(
        this.movementKeys.left,
        this.cursors.left,
        this.movementKeys.right,
        this.cursors.right,
      ),
      this.getAxis(
        this.movementKeys.up,
        this.cursors.up,
        this.movementKeys.down,
        this.cursors.down,
      ),
    );

    if (direction.lengthSq() > 0) {
      direction.normalize();
      this.gameSocket.send({
        type: "move_intent",
        direction_x: direction.x,
        direction_y: direction.y,
      });
    }

    this.drawAimLine();
  }

  private syncPlayers(serverPlayers: PlayerState[]): void {
    const currentPlayerIds = new Set(serverPlayers.map((player) => player.id));

    for (const playerState of serverPlayers) {
      let player = this.players.get(playerState.id);
      if (!player) {
        const isLocalPlayer = playerState.id === this.localPlayerId;
        player = this.add.circle(
          playerState.x,
          playerState.y,
          PLAYER_RADIUS,
          isLocalPlayer ? 0x5bf2bd : 0xf5c55b,
        );
        player.setStrokeStyle(4, isLocalPlayer ? 0xd8fff1 : 0xffe2a1, 0.85);
        this.players.set(playerState.id, player);
      }

      player.setPosition(playerState.x, playerState.y);
      if (playerState.id === this.localPlayerId) {
        this.localPlayer = player;
      }
    }

    for (const [playerId, player] of this.players) {
      if (!currentPlayerIds.has(playerId)) {
        player.destroy();
        this.players.delete(playerId);
        if (playerId === this.localPlayerId) {
          this.localPlayer = null;
        }
      }
    }
  }

  private drawArena(): void {
    const graphics = this.add.graphics();
    graphics.fillStyle(0x0d141e, 1);
    graphics.fillRoundedRect(48, 48, 1184, 584, 22);
    graphics.lineStyle(1, 0x233044, 0.8);

    for (let x = 80; x <= 1200; x += 40) {
      graphics.lineBetween(x, 64, x, 616);
    }

    for (let y = 80; y <= 600; y += 40) {
      graphics.lineBetween(64, y, 1216, y);
    }

    graphics.lineStyle(3, 0x34445b, 1);
    graphics.strokeRoundedRect(48, 48, 1184, 584, 22);
  }

  private drawAimLine(): void {
    const player = this.localPlayer;
    if (!player) {
      return;
    }

    const pointer = this.input.activePointer;
    const angle = Phaser.Math.Angle.Between(
      player.x,
      player.y,
      pointer.worldX,
      pointer.worldY,
    );
    const endX = player.x + Math.cos(angle) * 54;
    const endY = player.y + Math.sin(angle) * 54;

    this.aimLine.clear();
    this.aimLine.lineStyle(5, 0xf5c55b, 1);
    this.aimLine.lineBetween(player.x, player.y, endX, endY);
  }

  private getAxis(
    negativePrimary: Phaser.Input.Keyboard.Key,
    negativeSecondary: Phaser.Input.Keyboard.Key,
    positivePrimary: Phaser.Input.Keyboard.Key,
    positiveSecondary: Phaser.Input.Keyboard.Key,
  ): number {
    const negative = negativePrimary.isDown || negativeSecondary.isDown;
    const positive = positivePrimary.isDown || positiveSecondary.isDown;
    return Number(positive) - Number(negative);
  }
}

