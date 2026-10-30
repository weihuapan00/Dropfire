import assert from "node:assert/strict";
import { createServer as createHttpServer } from "node:http";
import { after, before, test } from "node:test";
import { createServer } from "vite";

let vite;
let MobileInput;

before(async () => {
  vite = await createServer({
    server: { middlewareMode: true, watch: null, hmr: { server: createHttpServer() } },
    appType: "custom",
  });
  ({ MobileInput } = await vite.ssrLoadModule("/src/game/MobileInput.ts"));
});

after(async () => { await vite?.close(); });

test("two fingers move and aim independently; lifting aim does not stop movement", () => {
  const input = new MobileInput();
  input.pointerDown({ id: 1, x: 150, y: 600 }, 1280, 720);
  input.pointerDown({ id: 2, x: 1100, y: 600 }, 1280, 720);
  input.pointerMove({ id: 1, x: 210, y: 600 });
  input.pointerMove({ id: 2, x: 1100, y: 540 });
  assert.deepEqual(input.moveDirection, { x: 1, y: 0 });
  assert.deepEqual(input.aimDirection, { x: 0, y: -1 });
  assert.equal(input.consumeAimStart(), true);
  assert.equal(input.consumeAimStart(), false);

  assert.equal(input.pointerUp({ id: 2, x: 1100, y: 540 }), true);
  assert.deepEqual(input.aimDirection, { x: 0, y: 0 });
  assert.deepEqual(input.moveDirection, { x: 1, y: 0 });
  assert.equal(input.movePointerId, 1);
});

test("small finger jitter stays in the dead zone and a button does not claim a joystick", () => {
  const input = new MobileInput();
  input.pointerDown({ id: 1, x: 150, y: 600 }, 1280, 720);
  input.pointerDown({ id: 2, x: 1100, y: 600 }, 1280, 720);
  input.pointerMove({ id: 1, x: 152, y: 602 });
  input.pointerMove({ id: 2, x: 1102, y: 602 });
  assert.deepEqual(input.moveDirection, { x: 0, y: 0 });
  assert.deepEqual(input.aimDirection, { x: 0, y: 0 });
  assert.equal(input.consumeAimStart(), false);
  assert.equal(input.pointerDown({ id: 3, x: 1004, y: 462 }, 1280, 720), "pickup");
  assert.equal(input.movePointerId, 1);
  assert.equal(input.aimPointerId, 2);
  assert.equal(input.pressedAction, "pickup");
});

test("reset clears held directions, buttons and fingers so new touches can start", () => {
  const input = new MobileInput();
  input.pointerDown({ id: 1, x: 150, y: 600 }, 1280, 720);
  input.pointerDown({ id: 2, x: 1100, y: 600 }, 1280, 720);
  input.pointerMove({ id: 1, x: 210, y: 600 });
  input.pointerMove({ id: 2, x: 1100, y: 540 });
  input.consumeAimStart();
  input.pointerDown({ id: 3, x: 1174, y: 462 }, 1280, 720);
  input.reset();

  assert.equal(input.movePointerId, null);
  assert.equal(input.aimPointerId, null);
  assert.equal(input.pressedAction, null);
  assert.deepEqual(input.moveDirection, { x: 0, y: 0 });
  assert.deepEqual(input.aimDirection, { x: 0, y: 0 });
  // A delayed event from the old finger must not reactivate movement.
  input.pointerMove({ id: 1, x: 300, y: 600 });
  assert.deepEqual(input.moveDirection, { x: 0, y: 0 });
  input.pointerDown({ id: 4, x: 1100, y: 600 }, 1280, 720);
  input.pointerMove({ id: 4, x: 1160, y: 600 });
  assert.equal(input.consumeAimStart(), true);
});
