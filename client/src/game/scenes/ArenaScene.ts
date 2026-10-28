import Phaser from "phaser";

import { GameSocket } from "../../network/GameSocket";

const PLAYER_RADIUS = 20;
const WEAPON_TYPES = ["fists", "knife", "pistol", "rifle"] as const;

type WeaponType = (typeof WEAPON_TYPES)[number];

const WEAPON_LABELS: Record<WeaponType, string> = {
  fists: "FISTS",
  knife: "KNIFE",
  pistol: "PISTOL",
  rifle: "RIFLE",
};

const WEAPON_COLORS: Record<WeaponType, number> = {
  fists: 0x5bf2bd,
  knife: 0xf15d58,
  pistol: 0xf15d58,
  rifle: 0xf15d58,
};

interface PlayerState {
  id: string;
  x: number;
  y: number;
  weapon: WeaponType;
}

interface PickupState {
  id: string;
  x: number;
  y: number;
  weapon: WeaponType;
}

function isWeaponType(value: unknown): value is WeaponType {
  return typeof value === "string" && WEAPON_TYPES.some((weapon) => weapon === value);
}

function isPlayerState(value: unknown): value is PlayerState {
  if (typeof value !== "object" || value === null) {
    return false;
  }

  const player = value as Record<string, unknown>;
  return (
    typeof player.id === "string" &&
    typeof player.x === "number" &&
    typeof player.y === "number" &&
    isWeaponType(player.weapon)
  );
}

function isPickupState(value: unknown): value is PickupState {
  if (typeof value !== "object" || value === null) {
    return false;
  }

  const pickup = value as Record<string, unknown>;
  return (
    typeof pickup.id === "string" &&
    typeof pickup.x === "number" &&
    typeof pickup.y === "number" &&
    isWeaponType(pickup.weapon) &&
    pickup.weapon !== "fists"
  );
}

export class ArenaScene extends Phaser.Scene {
  private readonly players = new Map<string, Phaser.GameObjects.Arc>();
  private readonly weaponLabels = new Map<string, Phaser.GameObjects.Text>();
  private readonly pickups = new Map<string, Phaser.GameObjects.Container>();
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

      if (
        message.type === "world_state" &&
        Array.isArray(message.players) &&
        Array.isArray(message.pickups)
      ) {
        this.syncPlayers(message.players.filter(isPlayerState));
        this.syncPickups(message.pickups.filter(isPickupState));
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
      .text(640, 650, "Move: WASD / arrows  •  Walk into a weapon pickup to equip it", {
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
        this.weaponLabels.set(
          playerState.id,
          this.add
            .text(playerState.x, playerState.y - 42, "", {
              color: isLocalPlayer ? "#d8fff1" : "#ffe2a1",
              fontFamily: "system-ui, sans-serif",
              fontSize: "14px",
              fontStyle: "bold",
            })
            .setOrigin(0.5),
        );
      }

      player.setPosition(playerState.x, playerState.y);
      this.updateWeaponLabel(playerState);
      if (playerState.id === this.localPlayerId) {
        this.localPlayer = player;
      }
    }

    for (const [playerId, player] of this.players) {
      if (!currentPlayerIds.has(playerId)) {
        player.destroy();
        this.players.delete(playerId);
        this.weaponLabels.get(playerId)?.destroy();
        this.weaponLabels.delete(playerId);
        if (playerId === this.localPlayerId) {
          this.localPlayer = null;
        }
      }
    }
  }

  private updateWeaponLabel(playerState: PlayerState): void {
    const label = this.weaponLabels.get(playerState.id);
    if (!label) {
      return;
    }

    const owner = playerState.id === this.localPlayerId ? "YOU · " : "";
    label.setText(`${owner}${WEAPON_LABELS[playerState.weapon]}`);
    label.setPosition(playerState.x, playerState.y - 42);
  }

  private syncPickups(serverPickups: PickupState[]): void {
    const currentPickupIds = new Set(serverPickups.map((pickup) => pickup.id));

    for (const pickupState of serverPickups) {
      let pickup = this.pickups.get(pickupState.id);
      if (!pickup) {
        const marker = this.add.circle(0, 0, 24, WEAPON_COLORS[pickupState.weapon], 0.9);
        marker.setStrokeStyle(3, 0xffffff, 0.7);
        const label = this.add
          .text(0, 0, WEAPON_LABELS[pickupState.weapon], {
            color: "#081018",
            fontFamily: "system-ui, sans-serif",
            fontSize: "11px",
            fontStyle: "bold",
          })
          .setOrigin(0.5);
        pickup = this.add.container(pickupState.x, pickupState.y, [marker, label]);
        this.pickups.set(pickupState.id, pickup);
      }

      pickup.setPosition(pickupState.x, pickupState.y);
    }

    for (const [pickupId, pickup] of this.pickups) {
      if (!currentPickupIds.has(pickupId)) {
        pickup.destroy();
        this.pickups.delete(pickupId);
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

