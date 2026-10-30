export const MOBILE_JOYSTICK_X = 126;
export const MOBILE_JOYSTICK_Y = 592;
export const MOBILE_JOYSTICK_RADIUS = 70;
export const MOBILE_AIM_JOYSTICK_X = 1154;
export const MOBILE_AIM_JOYSTICK_Y = 592;
export const MOBILE_SWITCH_X = 834;
export const MOBILE_PICKUP_X = 1004;
export const MOBILE_RELOAD_X = 1174;
export const MOBILE_ACTION_Y = 462;
export const MOBILE_ACTION_DRAW_RADIUS = 54;
const MOBILE_ACTION_HIT_RADIUS = 62;
const MOBILE_MOVE_DEAD_ZONE = 0.16;
const MOBILE_AIM_DEAD_ZONE = 0.08;

type Point = { x: number; y: number };
type TouchPointer = Point & { id: number };
export type MobileAction = "switch" | "pickup" | "reload";

/** Touch state only: the scene still decides how to draw and send game intents. */
export class MobileInput {
  readonly moveDirection: Point = { x: 0, y: 0 };
  readonly aimDirection: Point = { x: 0, y: 0 };
  readonly moveOrigin: Point = { x: MOBILE_JOYSTICK_X, y: MOBILE_JOYSTICK_Y };
  readonly aimOrigin: Point = { x: MOBILE_AIM_JOYSTICK_X, y: MOBILE_AIM_JOYSTICK_Y };
  movePointerId: number | null = null;
  aimPointerId: number | null = null;
  pressedAction: MobileAction | null = null;
  private actionPointerId: number | null = null;
  private aimHasFired = false;

  pointerDown(pointer: TouchPointer, width: number, height: number): MobileAction | null {
    const action = this.actionAt(pointer);
    if (action) {
      this.pressedAction = action;
      this.actionPointerId = pointer.id;
      return action;
    }
    if (pointer.x < width / 2 && this.movePointerId === null) {
      this.movePointerId = pointer.id;
      this.setOrigin(this.moveOrigin, pointer, width, height);
      this.clearDirection(this.moveDirection);
    } else if (this.aimPointerId === null) {
      this.aimPointerId = pointer.id;
      this.aimHasFired = false;
      this.setOrigin(this.aimOrigin, pointer, width, height);
      this.clearDirection(this.aimDirection);
    }
    return null;
  }

  pointerMove(pointer: TouchPointer): void {
    if (pointer.id === this.movePointerId) {
      this.updateDirection(this.moveDirection, this.moveOrigin, pointer, MOBILE_MOVE_DEAD_ZONE);
    }
    if (pointer.id === this.aimPointerId) {
      this.updateDirection(this.aimDirection, this.aimOrigin, pointer, MOBILE_AIM_DEAD_ZONE);
    }
  }

  /** Returns true when the aiming finger is released, so held fire can stop. */
  pointerUp(pointer: TouchPointer): boolean {
    if (pointer.id === this.actionPointerId) {
      this.pressedAction = null;
      this.actionPointerId = null;
    }
    if (pointer.id === this.movePointerId) {
      this.movePointerId = null;
      this.clearDirection(this.moveDirection);
      Object.assign(this.moveOrigin, { x: MOBILE_JOYSTICK_X, y: MOBILE_JOYSTICK_Y });
    }
    if (pointer.id !== this.aimPointerId) return false;
    this.aimPointerId = null;
    this.clearDirection(this.aimDirection);
    this.aimHasFired = false;
    Object.assign(this.aimOrigin, { x: MOBILE_AIM_JOYSTICK_X, y: MOBILE_AIM_JOYSTICK_Y });
    return true;
  }

  consumeAimStart(): boolean {
    if (this.aimHasFired || (this.aimDirection.x === 0 && this.aimDirection.y === 0)) return false;
    this.aimHasFired = true;
    return true;
  }

  reset(): void {
    this.movePointerId = null;
    this.aimPointerId = null;
    this.actionPointerId = null;
    this.pressedAction = null;
    this.aimHasFired = false;
    this.clearDirection(this.moveDirection);
    this.clearDirection(this.aimDirection);
    Object.assign(this.moveOrigin, { x: MOBILE_JOYSTICK_X, y: MOBILE_JOYSTICK_Y });
    Object.assign(this.aimOrigin, { x: MOBILE_AIM_JOYSTICK_X, y: MOBILE_AIM_JOYSTICK_Y });
  }

  private actionAt(pointer: Point): MobileAction | null {
    const withinButton = (x: number) =>
      Math.hypot(pointer.x - x, pointer.y - MOBILE_ACTION_Y) <= MOBILE_ACTION_HIT_RADIUS;
    if (withinButton(MOBILE_SWITCH_X)) return "switch";
    if (withinButton(MOBILE_PICKUP_X)) return "pickup";
    if (withinButton(MOBILE_RELOAD_X)) return "reload";
    return null;
  }

  private setOrigin(origin: Point, pointer: Point, width: number, height: number): void {
    const margin = MOBILE_JOYSTICK_RADIUS + 8;
    origin.x = Math.max(margin, Math.min(width - margin, pointer.x));
    origin.y = Math.max(margin, Math.min(height - margin, pointer.y));
  }

  private updateDirection(direction: Point, origin: Point, pointer: Point, deadZone: number): void {
    const x = pointer.x - origin.x;
    const y = pointer.y - origin.y;
    const length = Math.hypot(x, y);
    if (length < MOBILE_JOYSTICK_RADIUS * deadZone) {
      this.clearDirection(direction);
    } else {
      direction.x = x / length;
      direction.y = y / length;
    }
  }

  private clearDirection(direction: Point): void {
    direction.x = 0;
    direction.y = 0;
  }
}
