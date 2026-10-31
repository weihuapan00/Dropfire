import Phaser from "phaser";

/** A top-down armoured player. Visual details never change server collision. */
export class PlayerAvatar extends Phaser.GameObjects.Container {
  private readonly armour: Phaser.GameObjects.Graphics;
  private colour = -1;

  constructor(scene: Phaser.Scene, x: number, y: number, colour: number) {
    super(scene, x, y);
    scene.add.existing(this);
    this.setSize(40, 40).setDepth(1);
    this.armour = scene.add.graphics();
    this.add(this.armour);
    this.setFillStyle(colour);
  }

  setFillStyle(colour: number): this {
    if (colour === this.colour) return this;
    this.colour = colour;
    const dark = Phaser.Display.Color.IntegerToColor(colour).darken(48).color;
    const light = Phaser.Display.Color.IntegerToColor(colour).lighten(22).color;
    const g = this.armour;
    g.clear();
    // Faces right at rotation zero; the scene rotates body and gun together.
    g.fillStyle(0x020711, 0.45);
    g.fillEllipse(-2, 5, 48, 43);
    g.fillStyle(0x101c2b);
    g.fillRoundedRect(-15, -18, 15, 13, 5);
    g.fillRoundedRect(-15, 5, 15, 13, 5);
    g.lineStyle(2, 0x08111c);
    g.fillStyle(dark);
    g.fillRoundedRect(-17, -14, 27, 28, 9);
    g.strokeRoundedRect(-17, -14, 27, 28, 9);
    // Shoulder plates and gloved hands frame the held weapon.
    g.fillStyle(colour);
    g.fillRoundedRect(-3, -20, 18, 12, 5);
    g.strokeRoundedRect(-3, -20, 18, 12, 5);
    g.fillRoundedRect(-3, 8, 18, 12, 5);
    g.strokeRoundedRect(-3, 8, 18, 12, 5);
    g.fillStyle(0x192736);
    g.fillCircle(15, -10, 5);
    g.fillCircle(15, 10, 5);
    // Helmet rim, shell, highlight and a dark forward-facing visor.
    g.fillStyle(dark);
    g.fillCircle(-3, 1, 17);
    g.lineStyle(2.5, 0x07131b);
    g.strokeCircle(-3, 1, 17);
    g.fillStyle(colour);
    g.fillCircle(-3, -2, 14);
    g.lineStyle(2, light, 0.8);
    g.beginPath();
    g.arc(-3, -2, 11, Math.PI, Math.PI * 1.6);
    g.strokePath();
    g.fillStyle(0x142b36);
    g.fillRoundedRect(5, -11, 6, 17, 3);
    g.lineStyle(1, light, 0.65);
    g.lineBetween(8, -8, 8, 1);
    return this;
  }
}
