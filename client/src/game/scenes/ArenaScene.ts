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
const MOBILE_JOYSTICK_X = 126;
const MOBILE_JOYSTICK_Y = 592;
const MOBILE_JOYSTICK_RADIUS = 70;
const MOBILE_ACTION_Y = 628;
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
  connected: boolean;
  damage_dealt: number;
  kills: number;
  respawn_ends_in_seconds: number;
  spawn_protection_ends_in_seconds: number;
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
    typeof player.alive === "boolean" &&
    typeof player.connected === "boolean" &&
    typeof player.damage_dealt === "number" &&
    typeof player.kills === "number" &&
    typeof player.respawn_ends_in_seconds === "number" &&
    typeof player.spawn_protection_ends_in_seconds === "number"
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
  private readonly playerAliveStates = new Map<string, boolean>();
  private hasSyncedCovers = false;
  private lastRoundHudText = "";
  private lastScoreboardText = "";
  private livingSpectatorIds: string[] = [];
  private spectatorTargetId: string | null = null;
  private cameraIsFollowingLocalPlayer = false;
  private automaticFireIsHeld = false;
  private nextAutomaticFireAt = 0;
  private lastSentMoveDirection = new Phaser.Math.Vector2();
  private readonly pointerWorldPosition = new Phaser.Math.Vector2();
  private readonly touchMoveDirection = new Phaser.Math.Vector2();
  private touchMovePointerId: number | null = null;
  private touchAimPointer: Phaser.Input.Pointer | null = null;
  private isTouchControlScheme = false;
  private mobileControls!: Phaser.GameObjects.Graphics;
  private aimLine!: Phaser.GameObjects.Graphics;
  private ammoHud!: Phaser.GameObjects.Text;
  private roundHud!: Phaser.GameObjects.Text;
  private scoreboardHud!: Phaser.GameObjects.Text;
  private spectatorHud!: Phaser.GameObjects.Text;
  private performanceHud!: Phaser.GameObjects.Text;
  private pingMs: number | null = null;
  private nextPingAt = 0;
  private nextPerformanceHudUpdateAt = 0;
  private cursors!: Phaser.Types.Input.Keyboard.CursorKeys;
  private movementKeys!: Record<"up" | "down" | "left" | "right", Phaser.Input.Keyboard.Key>;
  private reloadKey!: Phaser.Input.Keyboard.Key;
  private pickupKey!: Phaser.Input.Keyboard.Key;
  private spectateKey!: Phaser.Input.Keyboard.Key;

  constructor(private readonly gameSocket: GameSocket) {
    super("arena");
  }

  create(): void {
    this.drawArena();
    this.cameras.main.setBounds(0, 0, WORLD_WIDTH, WORLD_HEIGHT);
    this.isTouchControlScheme = navigator.maxTouchPoints > 0;
    if (this.isTouchControlScheme) {
      this.input.addPointer(2);
    }

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
      .text(640, 18, "DEATHMATCH · 3:00", {
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
    this.scoreboardHud = this.add
      .text(18, 110, "LEADERBOARD", {
        backgroundColor: "#111a27",
        color: "#f4f7fb",
        fontFamily: "system-ui, sans-serif",
        fontSize: "14px",
        padding: { x: 8, y: 6 },
      })
      .setScrollFactor(0)
      .setDepth(100);
    this.spectatorHud = this.add
      .text(640, 58, "", {
        color: "#d5dff0",
        fontFamily: "system-ui, sans-serif",
        fontSize: "15px",
        fontStyle: "bold",
      })
      .setOrigin(0.5, 0)
      .setScrollFactor(0)
      .setDepth(100);
    this.performanceHud = this.add
      .text(1262, 102, "FPS: --\nPING: --", {
        backgroundColor: "#111a27",
        color: "#b8c7d9",
        fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
        fontSize: "13px",
        padding: { x: 7, y: 5 },
      })
      .setOrigin(1, 0)
      .setScrollFactor(0)
      .setDepth(100);

    this.gameSocket.onMessage((message) => {
      if (message.type === "server_connected" && typeof message.player_id === "string") {
        this.localPlayerId = message.player_id;
      }

      if (message.type === "pong" && typeof message.client_sent_at === "number") {
        this.pingMs = Math.round(performance.now() - message.client_sent_at);
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
        if (!this.hasSyncedCovers) {
          this.syncCovers(message.covers.filter(isCoverState));
          this.hasSyncedCovers = true;
        }
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
    this.spectateKey = keyboard.addKey(Phaser.Input.Keyboard.KeyCodes.P);

    this.input.on("pointerdown", (pointer: Phaser.Input.Pointer) => this.handlePointerDown(pointer));
    this.input.on("pointermove", (pointer: Phaser.Input.Pointer) => this.handlePointerMove(pointer));
    this.input.on("pointerup", (pointer: Phaser.Input.Pointer) => this.handlePointerUp(pointer));

    if (this.isTouchControlScheme) {
      this.mobileControls = this.add.graphics().setScrollFactor(0).setDepth(110);
      this.add.text(985, MOBILE_ACTION_Y, "PICK", {
        color: "#f4f7fb",
        fontFamily: "system-ui, sans-serif",
        fontSize: "15px",
        fontStyle: "bold",
      }).setOrigin(0.5).setScrollFactor(0).setDepth(111);
      this.add.text(1135, MOBILE_ACTION_Y, "RELOAD", {
        color: "#f4f7fb",
        fontFamily: "system-ui, sans-serif",
        fontSize: "13px",
        fontStyle: "bold",
      }).setOrigin(0.5).setScrollFactor(0).setDepth(111);
      this.drawMobileControls();
    }

    this.add
      .text(
        640,
        680,
        this.isTouchControlScheme
          ? "Left stick: move  •  Right side: aim & fire  •  PICK UP / RELOAD buttons"
          : "Move: WASD / arrows  •  E: pick up  •  R: reload  •  P: spectate next  •  Knife: click  •  Pistol: click  •  Rifle: hold left click",
        {
        color: "#96a3b6",
        fontFamily: "system-ui, sans-serif",
        fontSize: this.isTouchControlScheme ? "15px" : "18px",
        },
      )
      .setOrigin(0.5)
      .setScrollFactor(0)
      .setDepth(100);
  }

  update(time: number, delta: number): void {
    this.interpolatePlayers(delta);
    this.interpolateBullets(delta);
    this.updatePerformanceHud(time);

    if (!this.localPlayerIsAlive && Phaser.Input.Keyboard.JustDown(this.spectateKey)) {
      this.followNextSpectator();
    }

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

    const keyboardDirection = new Phaser.Math.Vector2(
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

    if (keyboardDirection.lengthSq() > 0) {
      keyboardDirection.normalize();
    }

    const direction = this.touchMovePointerId === null ? keyboardDirection : this.touchMoveDirection;

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
    this.livingSpectatorIds = serverPlayers
      .filter((player) => player.alive && player.id !== this.localPlayerId)
      .map((player) => player.id);

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
      const respawnedThisUpdate = this.playerAliveStates.get(playerState.id) === false && playerState.alive;
      if (!playerState.connected) {
        player.setFillStyle(0x4c5566);
        player.setStrokeStyle(4, 0xb9c4d4, 0.5);
        player.setAlpha(0.45);
      } else if (playerState.alive) {
        player.setFillStyle(isLocalPlayer ? 0x5bf2bd : 0xf5c55b);
        player.setStrokeStyle(4, isLocalPlayer ? 0xd8fff1 : 0xffe2a1, 0.85);
        player.setAlpha(1);
      } else {
        player.setFillStyle(0x667085);
        player.setStrokeStyle(4, 0xaab2c0, 0.65);
        player.setAlpha(0.6);
      }

      const target = this.playerRenderTargets.get(playerState.id);
      if (respawnedThisUpdate) {
        // Respawn locations are server-only until this update; never interpolate from the corpse.
        player.setPosition(playerState.x, playerState.y);
        this.playerRenderTargets.set(
          playerState.id,
          new Phaser.Math.Vector2(playerState.x, playerState.y),
        );
      } else if (target) {
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
      this.playerAliveStates.set(playerState.id, playerState.alive);
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

    if (this.localPlayerIsAlive && this.localPlayer) {
      this.spectatorTargetId = null;
      this.spectatorHud.setText("");
      if (!this.cameraIsFollowingLocalPlayer) {
        this.cameras.main.startFollow(this.localPlayer, true, 0.14, 0.14);
        this.cameraIsFollowingLocalPlayer = true;
      }
    } else {
      this.followNextSpectator(false);
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
        this.playerAliveStates.delete(playerId);
        if (playerId === this.localPlayerId) {
          this.localPlayer = null;
        }
      }
    }

    this.syncScoreboard(serverPlayers);
  }

  private syncRound(round: RoundState): void {
    this.roundPhase = round.phase;
    if (round.phase === "waiting") {
      this.setRoundHudText("WAITING FOR 2 PLAYERS");
      return;
    }

    if (round.phase === "active") {
      const seconds = Math.ceil(round.ends_in_seconds);
      const minutes = Math.floor(seconds / 60);
      const remainingSeconds = String(seconds % 60).padStart(2, "0");
      this.setRoundHudText(`DEATHMATCH ${round.number} · ${minutes}:${remainingSeconds}`);
      return;
    }

    const winnerLabel = round.winner_id === this.localPlayerId
      ? "YOU WIN"
      : round.winner_id
        ? `PLAYER ${round.winner_id.slice(0, 6)} WINS`
        : "NO WINNER";
    this.setRoundHudText(`${winnerLabel} · NEXT ROUND ${Math.ceil(round.ends_in_seconds)}s`);
  }

  private setRoundHudText(text: string): void {
    if (text === this.lastRoundHudText) return;
    this.lastRoundHudText = text;
    this.roundHud.setText(text);
  }

  private syncScoreboard(serverPlayers: PlayerState[]): void {
    const rankedPlayers = [...serverPlayers].sort(
      (left, right) => right.kills - left.kills || right.damage_dealt - left.damage_dealt,
    );
    const lines = rankedPlayers.map((player, index) => {
      const name = player.id === this.localPlayerId ? "YOU" : `P${player.id.slice(0, 4)}`;
      return `${index + 1}. ${name}  ${player.kills} K · ${Math.round(player.damage_dealt)} DMG`;
    });
    const text = ["LEADERBOARD", ...lines].join("\n");
    if (text === this.lastScoreboardText) return;
    this.lastScoreboardText = text;
    this.scoreboardHud.setText(text);
  }

  private followNextSpectator(advance = true): void {
    if (this.livingSpectatorIds.length === 0) {
      this.spectatorTargetId = null;
      this.spectatorHud.setText("ELIMINATED · WAITING FOR NEXT ROUND");
      return;
    }

    const currentIndex = this.spectatorTargetId
      ? this.livingSpectatorIds.indexOf(this.spectatorTargetId)
      : -1;
    const nextIndex = advance || currentIndex === -1
      ? (currentIndex + 1) % this.livingSpectatorIds.length
      : currentIndex;
    const nextTargetId = this.livingSpectatorIds[nextIndex];
    const nextTarget = this.players.get(nextTargetId);
    if (!nextTarget) {
      return;
    }

    this.spectatorTargetId = nextTargetId;
    this.cameras.main.startFollow(nextTarget, true, 0.14, 0.14);
    this.cameraIsFollowingLocalPlayer = false;
    this.spectatorHud.setText(`SPECTATING ${nextTargetId.slice(0, 6)} · P: NEXT PLAYER`);
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
    const shieldStatus = playerState.spawn_protection_ends_in_seconds > 0
      ? `SHIELDED ${playerState.spawn_protection_ends_in_seconds.toFixed(1)}s`
      : "";
    const combatStatus = !playerState.connected
      ? "DISCONNECTED"
      : playerState.alive
        ? shieldStatus || `HP ${playerState.hp}`
        : `RESPAWN ${Math.ceil(playerState.respawn_ends_in_seconds)}s`;
    const reloadStatus = playerState.reload_progress > 0 ? "\nRELOADING" : "";
    label.setText(`${owner}${WEAPON_LABELS[playerState.weapon]}${ammo}\n${combatStatus}${reloadStatus}`);
    if (playerState.id === this.localPlayerId) {
      const ammoHudValue = playerState.magazine_capacity > 0
        ? `${playerState.ammo_in_mag} / ${playerState.magazine_capacity}`
        : "--";
      const hpHudValue = playerState.alive
        ? shieldStatus || `${playerState.hp}`
        : `RESPAWN ${Math.ceil(playerState.respawn_ends_in_seconds)}s`;
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
    graphics.fillStyle(0x08111c, 1);
    graphics.fillRoundedRect(48, 48, WORLD_WIDTH - 96, WORLD_HEIGHT - 96, 22);
    graphics.fillStyle(0x0c1928, 0.52);
    for (let x = 120; x < WORLD_WIDTH - 96; x += 240) {
      for (let y = 120; y < WORLD_HEIGHT - 96; y += 240) {
        graphics.fillCircle(x, y, 92);
      }
    }
    graphics.lineStyle(1, 0x29415a, 0.62);

    for (let x = 80; x <= WORLD_WIDTH - 80; x += 40) {
      graphics.lineBetween(x, 64, x, WORLD_HEIGHT - 64);
    }

    for (let y = 80; y <= WORLD_HEIGHT - 80; y += 40) {
      graphics.lineBetween(64, y, WORLD_WIDTH - 64, y);
    }

    graphics.lineStyle(3, 0x4b6d88, 0.95);
    graphics.strokeRoundedRect(48, 48, WORLD_WIDTH - 96, WORLD_HEIGHT - 96, 22);
    graphics.lineStyle(1, 0x69f4c1, 0.3);
    graphics.strokeRoundedRect(58, 58, WORLD_WIDTH - 116, WORLD_HEIGHT - 116, 16);
  }

  private drawAimLine(): void {
    const player = this.localPlayer;
    if (!player) {
      return;
    }

    const pointer = this.touchAimPointer ?? this.input.activePointer;
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

  private updatePerformanceHud(time: number): void {
    if (time >= this.nextPingAt) {
      this.gameSocket.send({ type: "ping", client_sent_at: performance.now() });
      this.nextPingAt = time + 1000;
    }

    if (time < this.nextPerformanceHudUpdateAt) {
      return;
    }
    this.nextPerformanceHudUpdateAt = time + 250;
    const fps = Math.round(this.game.loop.actualFps);
    const ping = this.pingMs === null ? "--" : `${this.pingMs} ms`;
    this.performanceHud.setText(`FPS: ${fps}\nPING: ${ping}`);
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

  private handlePointerDown(pointer: Phaser.Input.Pointer): void {
    if (!this.isTouchPointer(pointer)) {
      this.startFiringAt(pointer);
      return;
    }

    if (this.isMobileAction(pointer)) {
      if (pointer.x < 1080) {
        this.gameSocket.send({ type: "pickup_intent" });
      } else {
        this.gameSocket.send({ type: "reload_intent" });
      }
      return;
    }

    if (pointer.x < 640 && this.touchMovePointerId === null) {
      this.touchMovePointerId = pointer.id;
      this.updateTouchMoveDirection(pointer);
      return;
    }

    if (this.touchAimPointer === null) {
      this.touchAimPointer = pointer;
      this.startFiringAt(pointer);
    }
  }

  private handlePointerMove(pointer: Phaser.Input.Pointer): void {
    if (pointer.id === this.touchMovePointerId) {
      this.updateTouchMoveDirection(pointer);
    }
  }

  private handlePointerUp(pointer: Phaser.Input.Pointer): void {
    if (pointer.id === this.touchMovePointerId) {
      this.touchMovePointerId = null;
      this.touchMoveDirection.set(0, 0);
    }
    if (pointer.id === this.touchAimPointer?.id) {
      this.touchAimPointer = null;
      this.automaticFireIsHeld = false;
    }
    if (!this.isTouchPointer(pointer)) {
      this.automaticFireIsHeld = false;
    }
  }

  private startFiringAt(pointer: Phaser.Input.Pointer): void {
    this.fireTowardPointer(pointer);
    if (FIRE_MODES[this.localWeapon] === "automatic") {
      this.automaticFireIsHeld = true;
      this.nextAutomaticFireAt = this.time.now + AUTOMATIC_FIRE_INTENT_INTERVAL_MS;
    }
  }

  private updateTouchMoveDirection(pointer: Phaser.Input.Pointer): void {
    this.touchMoveDirection.set(pointer.x - MOBILE_JOYSTICK_X, pointer.y - MOBILE_JOYSTICK_Y);
    if (this.touchMoveDirection.lengthSq() > MOBILE_JOYSTICK_RADIUS * MOBILE_JOYSTICK_RADIUS) {
      this.touchMoveDirection.setLength(MOBILE_JOYSTICK_RADIUS);
    }
    if (this.touchMoveDirection.lengthSq() > 0) {
      this.touchMoveDirection.normalize();
    }
    this.drawMobileControls();
  }

  private isMobileAction(pointer: Phaser.Input.Pointer): boolean {
    return pointer.y > 574 && pointer.x > 900;
  }

  private isTouchPointer(pointer: Phaser.Input.Pointer): boolean {
    return pointer.wasTouch;
  }

  private drawMobileControls(): void {
    this.mobileControls.clear();
    this.mobileControls.fillStyle(0x111a27, 0.62);
    this.mobileControls.fillCircle(MOBILE_JOYSTICK_X, MOBILE_JOYSTICK_Y, MOBILE_JOYSTICK_RADIUS);
    this.mobileControls.lineStyle(3, 0x7ed7ff, 0.75);
    this.mobileControls.strokeCircle(MOBILE_JOYSTICK_X, MOBILE_JOYSTICK_Y, MOBILE_JOYSTICK_RADIUS);
    this.mobileControls.fillStyle(0x7ed7ff, 0.75);
    this.mobileControls.fillCircle(
      MOBILE_JOYSTICK_X + this.touchMoveDirection.x * 38,
      MOBILE_JOYSTICK_Y + this.touchMoveDirection.y * 38,
      25,
    );

    for (const x of [985, 1135]) {
      this.mobileControls.fillStyle(0x111a27, 0.78);
      this.mobileControls.fillCircle(x, MOBILE_ACTION_Y, 51);
      this.mobileControls.lineStyle(3, 0xf5c55b, 0.85);
      this.mobileControls.strokeCircle(x, MOBILE_ACTION_Y, 51);
    }
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

