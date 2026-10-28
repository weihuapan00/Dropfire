import Phaser from "phaser";

const PLAYER_SPEED = 280;
const PLAYER_RADIUS = 20;

export class ArenaScene extends Phaser.Scene {
  private player!: Phaser.GameObjects.Arc;
  private aimLine!: Phaser.GameObjects.Graphics;
  private cursors!: Phaser.Types.Input.Keyboard.CursorKeys;
  private movementKeys!: Record<"up" | "down" | "left" | "right", Phaser.Input.Keyboard.Key>;

  constructor() {
    super("arena");
  }

  create(): void {
    this.drawArena();

    this.player = this.add.circle(640, 360, PLAYER_RADIUS, 0x5bf2bd);
    this.player.setStrokeStyle(4, 0xd8fff1, 0.85);

    this.aimLine = this.add.graphics();

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

  update(_time: number, delta: number): void {
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
      const distance = PLAYER_SPEED * (delta / 1000);
      this.player.x += direction.x * distance;
      this.player.y += direction.y * distance;
    }

    this.player.x = Phaser.Math.Clamp(this.player.x, 72, 1208);
    this.player.y = Phaser.Math.Clamp(this.player.y, 72, 608);
    this.drawAimLine();
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
    const pointer = this.input.activePointer;
    const angle = Phaser.Math.Angle.Between(
      this.player.x,
      this.player.y,
      pointer.worldX,
      pointer.worldY,
    );
    const endX = this.player.x + Math.cos(angle) * 54;
    const endY = this.player.y + Math.sin(angle) * 54;

    this.aimLine.clear();
    this.aimLine.lineStyle(5, 0xf5c55b, 1);
    this.aimLine.lineBetween(this.player.x, this.player.y, endX, endY);
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

