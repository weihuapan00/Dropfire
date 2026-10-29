import Phaser from "phaser";

import { GameSocket } from "../../network/GameSocket";

const PLAYER_RADIUS = 20;
const BULLET_RADIUS = 4;
const WORLD_WIDTH = 2560;
const WORLD_HEIGHT = 1440;
const INTERPOLATION_AT_60_FPS = 0.2;
const BULLET_INTERPOLATION_AT_60_FPS = 0.55;
const AUTOMATIC_FIRE_INTENT_INTERVAL_MS = 120;
const RELOAD_RING_RADIUS = 31;
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

const FIRE_MODES: Record<WeaponType, "none" | "semi" | "automatic"> = {
  fists: "none",
  knife: "none",
  pistol: "semi",
  rifle: "automatic",
};

const BULLET_COLORS: Record<"pistol" | "rifle", number> = {
  pistol: 0xffd166,
  rifle: 0x7ed7ff,
};

interface PlayerState {
  id: string;
  x: number;
  y: number;
  weapon: WeaponType;
  ammo_in_mag: number;
  magazine_capacity: number;
  reload_progress: number;
  melee_progress: number;
  melee_angle: number;
  hp: number;
  alive: boolean;
}

interface PickupState {
  id: string;
  x: number;
  y: number;
  weapon: WeaponType;
}

interface BulletState {
  id: string;
  x: number;
  y: number;
  weapon: "pistol" | "rifle";
}

interface CoverState {
  id: string;
  x: number;
  y: number;
  width: number;
  height: number;
}

interface RoundState {
  phase: "waiting" | "active" | "ending";
  number: number;
  winner_id: string | null;
  ends_in_seconds: number;
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
    isWeaponType(player.weapon) &&
    typeof player.ammo_in_mag === "number" &&
    typeof player.magazine_capacity === "number" &&
    typeof player.reload_progress === "number" &&
    typeof player.melee_progress === "number" &&
    typeof player.melee_angle === "number" &&
    typeof player.hp === "number" &&
    typeof player.alive === "boolean"
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

function isBulletState(value: unknown): value is BulletState {
  if (typeof value !== "object" || value === null) {
    return false;
  }

  const bullet = value as Record<string, unknown>;
  return (
    typeof bullet.id === "string" &&
    typeof bullet.x === "number" &&
    typeof bullet.y === "number" &&
    (bullet.weapon === "pistol" || bullet.weapon === "rifle")
  );
}

function isCoverState(value: unknown): value is CoverState {
  if (typeof value !== "object" || value === null) {
    return false;
  }

  const cover = value as Record<string, unknown>;
  return (
    typeof cover.id === "string" &&
    typeof cover.x === "number" &&
    typeof cover.y === "number" &&
    typeof cover.width === "number" &&
    typeof cover.height === "number"
  );
}

function isRoundState(value: unknown): value is RoundState {
  if (typeof value !== "object" || value === null) {
    return false;
  }

  const round = value as Record<string, unknown>;
  return (
    (round.phase === "waiting" || round.phase === "active" || round.phase === "ending") &&
    typeof round.number === "number" &&
    (typeof round.winner_id === "string" || round.winner_id === null) &&
    typeof round.ends_in_seconds === "number"
  );
}

export class ArenaScene extends Phaser.Scene {
  private readonly players = new Map<string, Phaser.GameObjects.Arc>();
  private readonly playerRenderTargets = new Map<string, Phaser.Math.Vector2>();
  private readonly weaponLabels = new Map<string, Phaser.GameObjects.Text>();
  private readonly reloadIndicators = new Map<string, Phaser.GameObjects.Graphics>();
  private readonly reloadProgress = new Map<string, number>();
  private readonly meleeIndicators = new Map<string, Phaser.GameObjects.Graphics>();
  private readonly meleeProgress = new Map<string, number>();
  private readonly meleeAngles = new Map<string, number>();
  private readonly covers = new Map<string, Phaser.GameObjects.Graphics>();
  private readonly pickups = new Map<string, Phaser.GameObjects.Container>();
  private readonly bullets = new Map<string, Phaser.GameObjects.Arc>();
  private readonly bulletRenderTargets = new Map<string, Phaser.Math.Vector2>();
  private localPlayerId: string | null = null;
  private localPlayer: Phaser.GameObjects.Arc | null = null;
  private localWeapon: WeaponType = "fists";
  private localPlayerIsAlive = true;
  private localPlayerIsReloading = false;
  private roundPhase: RoundState["phase"] = "waiting";
  private cameraIsFollowingLocalPlayer = false;
  private automaticFireIsHeld = false;
  private nextAutomaticFireAt = 0;
  private lastSentMoveDirection = new Phaser.Math.Vector2();
  private readonly pointerWorldPosition = new Phaser.Math.Vector2();
  private aimLine!: Phaser.GameObjects.Graphics;
  private ammoHud!: Phaser.GameObjects.Text;
  private roundHud!: Phaser.GameObjects.Text;
  private cursors!: Phaser.Types.Input.Keyboard.CursorKeys;
  private movementKeys!: Record<"up" | "down" | "left" | "right", Phaser.Input.Keyboard.Key>;
  private reloadKey!: Phaser.Input.Keyboard.Key;
  private pickupKey!: Phaser.Input.Keyboard.Key;

  constructor(private readonly gameSocket: GameSocket) {
    super("arena");
  }

  create(): void {
    this.drawArena();
    this.cameras.main.setBounds(0, 0, WORLD_WIDTH, WORLD_HEIGHT);

    this.aimLine = this.add.graphics();
    this.ammoHud = this.add
      .text(18, 18, "Weapon: FISTS\nAmmo: --\nHP: 100", {
        backgroundColor: "#111a27",
        color: "#f4f7fb",
        fontFamily: "system-ui, sans-serif",
        fontSize: "16px",
        fontStyle: "bold",
        padding: { x: 8, y: 6 },
      })
      .setScrollFactor(0)
      .setDepth(100);
    this.roundHud = this.add
      .text(640, 18, "WAITING FOR 2 PLAYERS", {
        backgroundColor: "#111a27",
        color: "#f4f7fb",
        fontFamily: "system-ui, sans-serif",
        fontSize: "18px",
        fontStyle: "bold",
        padding: { x: 10, y: 6 },
      })
      .setOrigin(0.5, 0)
      .setScrollFactor(0)
      .setDepth(100);

    this.gameSocket.onMessage((message) => {
      if (message.type === "server_connected" && typeof message.player_id === "string") {
        this.localPlayerId = message.player_id;
      }

      if (
        message.type === "world_state" &&
        isRoundState(message.round) &&
        Array.isArray(message.players) &&
        Array.isArray(message.covers) &&
        Array.isArray(message.pickups) &&
        Array.isArray(message.bullets)
      ) {
        this.syncRound(message.round);
        this.syncPlayers(message.players.filter(isPlayerState));
        this.syncCovers(message.covers.filter(isCoverState));
        this.syncPickups(message.pickups.filter(isPickupState));
        this.syncBullets(message.bullets.filter(isBulletState));
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
    this.reloadKey = keyboard.addKey(Phaser.Input.Keyboard.KeyCodes.R);
    this.pickupKey = keyboard.addKey(Phaser.Input.Keyboard.KeyCodes.E);

    this.input.on("pointerdown", (pointer: Phaser.Input.Pointer) => {
      this.fireTowardPointer(pointer);
      if (FIRE_MODES[this.localWeapon] === "automatic") {
        this.automaticFireIsHeld = true;
        this.nextAutomaticFireAt = this.time.now + AUTOMATIC_FIRE_INTENT_INTERVAL_MS;
      }
    });
    this.input.on("pointerup", () => {
      this.automaticFireIsHeld = false;
    });

    this.add
      .text(640, 680, "Move: WASD / arrows  •  E: pick up  •  R: reload  •  Knife: click  •  Pistol: click  •  Rifle: hold left click", {
        color: "#96a3b6",
        fontFamily: "system-ui, sans-serif",
        fontSize: "18px",
      })
      .setOrigin(0.5)
      .setScrollFactor(0)
      .setDepth(100);
  }

  update(time: number, delta: number): void {
    this.interpolatePlayers(delta);
    this.interpolateBullets(delta);

    if (!this.localPlayer || !this.localPlayerIsAlive || this.roundPhase !== "active") {
      this.automaticFireIsHeld = false;
      this.aimLine.clear();
      return;
    }

    if (Phaser.Input.Keyboard.JustDown(this.reloadKey)) {
      this.gameSocket.send({ type: "reload_intent" });
    }

    if (Phaser.Input.Keyboard.JustDown(this.pickupKey)) {
      this.gameSocket.send({ type: "pickup_intent" });
    }

    if (
      this.automaticFireIsHeld &&
      FIRE_MODES[this.localWeapon] === "automatic" &&
      time >= this.nextAutomaticFireAt
    ) {
      this.fireTowardPointer(this.input.activePointer);
      this.nextAutomaticFireAt = time + AUTOMATIC_FIRE_INTENT_INTERVAL_MS;
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
    }

    if (
      direction.x !== this.lastSentMoveDirection.x ||
      direction.y !== this.lastSentMoveDirection.y
    ) {
      this.gameSocket.send({
        type: "move_intent",
        direction_x: direction.x,
        direction_y: direction.y,
      });
      this.lastSentMoveDirection.copy(direction);
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
            .text(playerState.x, playerState.y - 54, "", {
              color: isLocalPlayer ? "#d8fff1" : "#ffe2a1",
              fontFamily: "system-ui, sans-serif",
              fontSize: "14px",
              fontStyle: "bold",
            })
            .setOrigin(0.5),
        );
      }

      const isLocalPlayer = playerState.id === this.localPlayerId;
      if (playerState.alive) {
        player.setFillStyle(isLocalPlayer ? 0x5bf2bd : 0xf5c55b);
        player.setStrokeStyle(4, isLocalPlayer ? 0xd8fff1 : 0xffe2a1, 0.85);
        player.setAlpha(1);
      } else {
        player.setFillStyle(0x667085);
        player.setStrokeStyle(4, 0xaab2c0, 0.65);
        player.setAlpha(0.6);
      }

      const target = this.playerRenderTargets.get(playerState.id);
      if (target) {
        target.set(playerState.x, playerState.y);
      } else {
        this.playerRenderTargets.set(
          playerState.id,
          new Phaser.Math.Vector2(playerState.x, playerState.y),
        );
      }
      this.updateWeaponLabel(playerState);
      this.reloadProgress.set(playerState.id, playerState.reload_progress);
      this.meleeProgress.set(playerState.id, playerState.melee_progress);
      this.meleeAngles.set(playerState.id, playerState.melee_angle);
      if (playerState.id === this.localPlayerId) {
        this.localPlayer = player;
        this.localWeapon = playerState.weapon;
        this.localPlayerIsAlive = playerState.alive;
        this.localPlayerIsReloading = playerState.reload_progress > 0;
        if (this.localPlayerIsReloading) {
          this.automaticFireIsHeld = false;
        }
        if (FIRE_MODES[this.localWeapon] !== "automatic") {
          this.automaticFireIsHeld = false;
        }
        if (!this.cameraIsFollowingLocalPlayer) {
          this.cameras.main.startFollow(player, true, 0.14, 0.14);
          this.cameraIsFollowingLocalPlayer = true;
        }
      }
    }

    for (const [playerId, player] of this.players) {
      if (!currentPlayerIds.has(playerId)) {
        player.destroy();
        this.players.delete(playerId);
        this.playerRenderTargets.delete(playerId);
        this.weaponLabels.get(playerId)?.destroy();
        this.weaponLabels.delete(playerId);
        this.reloadIndicators.get(playerId)?.destroy();
        this.reloadIndicators.delete(playerId);
        this.reloadProgress.delete(playerId);
        this.meleeIndicators.get(playerId)?.destroy();
        this.meleeIndicators.delete(playerId);
        this.meleeProgress.delete(playerId);
        this.meleeAngles.delete(playerId);
        if (playerId === this.localPlayerId) {
          this.localPlayer = null;
        }
      }
    }
  }

  private syncRound(round: RoundState): void {
    this.roundPhase = round.phase;
    if (round.phase === "waiting") {
      this.roundHud.setText("WAITING FOR 2 PLAYERS");
      return;
    }

    if (round.phase === "active") {
      this.roundHud.setText(`ROUND ${round.number}`);
      return;
    }

    const winnerLabel = round.winner_id === this.localPlayerId
      ? "YOU WIN"
      : round.winner_id
        ? `PLAYER ${round.winner_id.slice(0, 6)} WINS`
        : "NO WINNER";
    this.roundHud.setText(`${winnerLabel} · NEXT ROUND ${Math.ceil(round.ends_in_seconds)}s`);
  }

  private updateWeaponLabel(playerState: PlayerState): void {
    const label = this.weaponLabels.get(playerState.id);
    if (!label) {
      return;
    }

    const owner = playerState.id === this.localPlayerId ? "YOU · " : "";
    const ammo = playerState.magazine_capacity > 0
      ? ` · ${playerState.ammo_in_mag}/${playerState.magazine_capacity}`
      : "";
    const combatStatus = playerState.alive ? `HP ${playerState.hp}` : "ELIMINATED";
    const reloadStatus = playerState.reload_progress > 0 ? "\nRELOADING" : "";
    label.setText(`${owner}${WEAPON_LABELS[playerState.weapon]}${ammo}\n${combatStatus}${reloadStatus}`);
    if (playerState.id === this.localPlayerId) {
      const ammoHudValue = playerState.magazine_capacity > 0
        ? `${playerState.ammo_in_mag} / ${playerState.magazine_capacity}`
        : "--";
      const hpHudValue = playerState.alive ? `${playerState.hp}` : "ELIMINATED";
      this.ammoHud.setText(
        `Weapon: ${WEAPON_LABELS[playerState.weapon]}\nAmmo: ${ammoHudValue}\nHP: ${hpHudValue}${reloadStatus}`,
      );
    }
  }

  private interpolatePlayers(delta: number): void {
    const interpolationFactor = Math.min(
      1,
      INTERPOLATION_AT_60_FPS * (delta / (1000 / 60)),
    );

    for (const [playerId, player] of this.players) {
      const target = this.playerRenderTargets.get(playerId);
      if (!target) {
        continue;
      }

      player.x = Phaser.Math.Linear(player.x, target.x, interpolationFactor);
      player.y = Phaser.Math.Linear(player.y, target.y, interpolationFactor);
      this.weaponLabels.get(playerId)?.setPosition(player.x, player.y - 54);
      this.drawReloadIndicator(playerId, player);
      this.drawMeleeIndicator(playerId, player);
    }
  }

  private drawReloadIndicator(playerId: string, player: Phaser.GameObjects.Arc): void {
    const progress = this.reloadProgress.get(playerId) ?? 0;
    let indicator = this.reloadIndicators.get(playerId);
    if (progress <= 0) {
      indicator?.clear();
      return;
    }

    if (!indicator) {
      indicator = this.add.graphics().setDepth(2);
      this.reloadIndicators.set(playerId, indicator);
    }

    indicator.clear();
    indicator.lineStyle(4, 0x7ed7ff, 0.95);
    indicator.beginPath();
    indicator.arc(
      player.x,
      player.y,
      RELOAD_RING_RADIUS,
      -Math.PI / 2,
      -Math.PI / 2 + Math.PI * 2 * progress,
      false,
    );
    indicator.strokePath();
  }

  private drawMeleeIndicator(playerId: string, player: Phaser.GameObjects.Arc): void {
    const progress = this.meleeProgress.get(playerId) ?? 0;
    let indicator = this.meleeIndicators.get(playerId);
    if (progress <= 0) {
      indicator?.clear();
      return;
    }

    if (!indicator) {
      indicator = this.add.graphics().setDepth(3);
      this.meleeIndicators.set(playerId, indicator);
    }

    const angle = this.meleeAngles.get(playerId) ?? 0;
    const arcStart = angle - 1.1 + progress * 1.2;
    indicator.clear();
    indicator.lineStyle(7, 0xf8f1d2, 0.9);
    indicator.beginPath();
    indicator.arc(player.x, player.y, 56, arcStart, arcStart + 1.15, false);
    indicator.strokePath();
  }

  private syncPickups(serverPickups: PickupState[]): void {
    const currentPickupIds = new Set(serverPickups.map((pickup) => pickup.id));

    for (const pickupState of serverPickups) {
      let pickup = this.pickups.get(pickupState.id);
      if (!pickup) {
        const marker = this.add.triangle(
          0,
          0,
          0,
          -28,
          26,
          22,
          -26,
          22,
          WEAPON_COLORS[pickupState.weapon],
          0.9,
        );
        marker.setStrokeStyle(3, 0xffffff, 0.7);
        const label = this.add
          .text(0, 40, WEAPON_LABELS[pickupState.weapon], {
            backgroundColor: "#111a27",
            color: "#f4f7fb",
            fontFamily: "system-ui, sans-serif",
            fontSize: "18px",
            fontStyle: "bold",
            padding: { x: 4, y: 2 },
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

  private syncCovers(serverCovers: CoverState[]): void {
    const currentCoverIds = new Set(serverCovers.map((cover) => cover.id));

    for (const coverState of serverCovers) {
      let cover = this.covers.get(coverState.id);
      if (!cover) {
        cover = this.add.graphics().setDepth(2);
        this.covers.set(coverState.id, cover);
      }

      cover.clear();
      cover.fillStyle(0x34445b, 1);
      cover.fillRoundedRect(
        coverState.x - coverState.width / 2,
        coverState.y - coverState.height / 2,
        coverState.width,
        coverState.height,
        10,
      );
      cover.lineStyle(4, 0x8da2bd, 0.9);
      cover.strokeRoundedRect(
        coverState.x - coverState.width / 2,
        coverState.y - coverState.height / 2,
        coverState.width,
        coverState.height,
        10,
      );
    }

    for (const [coverId, cover] of this.covers) {
      if (!currentCoverIds.has(coverId)) {
        cover.destroy();
        this.covers.delete(coverId);
      }
    }
  }

  private syncBullets(serverBullets: BulletState[]): void {
    const currentBulletIds = new Set(serverBullets.map((bullet) => bullet.id));

    for (const bulletState of serverBullets) {
      let bullet = this.bullets.get(bulletState.id);
      if (!bullet) {
        bullet = this.add.circle(
          bulletState.x,
          bulletState.y,
          BULLET_RADIUS,
          BULLET_COLORS[bulletState.weapon],
        );
        bullet.setStrokeStyle(2, 0xffffff, 0.8);
        bullet.setDepth(3);
        this.bullets.set(bulletState.id, bullet);
      }

      const target = this.bulletRenderTargets.get(bulletState.id);
      if (target) {
        target.set(bulletState.x, bulletState.y);
      } else {
        this.bulletRenderTargets.set(
          bulletState.id,
          new Phaser.Math.Vector2(bulletState.x, bulletState.y),
        );
      }
    }

    for (const [bulletId, bullet] of this.bullets) {
      if (!currentBulletIds.has(bulletId)) {
        bullet.destroy();
        this.bullets.delete(bulletId);
        this.bulletRenderTargets.delete(bulletId);
      }
    }
  }

  private interpolateBullets(delta: number): void {
    const interpolationFactor = Math.min(
      1,
      BULLET_INTERPOLATION_AT_60_FPS * (delta / (1000 / 60)),
    );

    for (const [bulletId, bullet] of this.bullets) {
      const target = this.bulletRenderTargets.get(bulletId);
      if (!target) {
        continue;
      }

      bullet.x = Phaser.Math.Linear(bullet.x, target.x, interpolationFactor);
      bullet.y = Phaser.Math.Linear(bullet.y, target.y, interpolationFactor);
    }
  }

  private drawArena(): void {
    const graphics = this.add.graphics();
    graphics.fillStyle(0x0d141e, 1);
    graphics.fillRoundedRect(48, 48, WORLD_WIDTH - 96, WORLD_HEIGHT - 96, 22);
    graphics.lineStyle(1, 0x233044, 0.8);

    for (let x = 80; x <= WORLD_WIDTH - 80; x += 40) {
      graphics.lineBetween(x, 64, x, WORLD_HEIGHT - 64);
    }

    for (let y = 80; y <= WORLD_HEIGHT - 80; y += 40) {
      graphics.lineBetween(64, y, WORLD_WIDTH - 64, y);
    }

    graphics.lineStyle(3, 0x34445b, 1);
    graphics.strokeRoundedRect(48, 48, WORLD_WIDTH - 96, WORLD_HEIGHT - 96, 22);
  }

  private drawAimLine(): void {
    const player = this.localPlayer;
    if (!player) {
      return;
    }

    const pointer = this.input.activePointer;
    pointer.positionToCamera(this.cameras.main, this.pointerWorldPosition);
    const angle = Phaser.Math.Angle.Between(
      player.x,
      player.y,
      this.pointerWorldPosition.x,
      this.pointerWorldPosition.y,
    );
    const endX = player.x + Math.cos(angle) * 54;
    const endY = player.y + Math.sin(angle) * 54;

    this.aimLine.clear();
    this.aimLine.lineStyle(5, 0xf5c55b, 1);
    this.aimLine.lineBetween(player.x, player.y, endX, endY);
  }

  private fireTowardPointer(pointer: Phaser.Input.Pointer): void {
    const player = this.localPlayer;
    if (
      !player ||
      !this.localPlayerIsAlive ||
      this.localPlayerIsReloading ||
      this.roundPhase !== "active"
    ) {
      return;
    }

    pointer.positionToCamera(this.cameras.main, this.pointerWorldPosition);
    const directionX = this.pointerWorldPosition.x - player.x;
    const directionY = this.pointerWorldPosition.y - player.y;
    if (directionX === 0 && directionY === 0) {
      return;
    }

    if (this.localWeapon === "knife") {
      this.gameSocket.send({
        type: "melee_intent",
        direction_x: directionX,
        direction_y: directionY,
      });
      return;
    }

    this.gameSocket.send({
      type: "fire_intent",
      direction_x: directionX,
      direction_y: directionY,
    });
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

