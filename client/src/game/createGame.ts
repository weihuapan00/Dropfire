import Phaser from "phaser";

import { ArenaScene } from "./scenes/ArenaScene";
import { GameSocket } from "../network/GameSocket";

export function createGame(
  parent: string,
  gameSocket: GameSocket,
  localPlayerId: string | null,
): Phaser.Game {
  return new Phaser.Game({
    type: Phaser.AUTO,
    parent,
    width: 1280,
    height: 720,
    backgroundColor: "#090d14",
    scene: [new ArenaScene(gameSocket, localPlayerId)],
    scale: {
      mode: Phaser.Scale.FIT,
      autoCenter: Phaser.Scale.CENTER_BOTH,
    },
    render: {
      antialias: true,
      pixelArt: false,
    },
  });
}

