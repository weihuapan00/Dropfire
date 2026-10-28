# Dropfire collaboration guide

## Teaching mode

The user is learning TypeScript, Phaser, WebSockets, and multiplayer-game
development while building Dropfire. Work incrementally and keep every change
small, runnable, and easy to inspect.

For each feature:

1. State the player-facing goal.
2. Explain the relevant TypeScript and Phaser/backend concepts in plain Chinese,
   including useful English terms for interviews.
3. Make or guide one focused change.
4. Run a proportionate check and explain what it proves.
5. Ask one or two short questions to confirm understanding before moving on.

Do not skip ahead to a large architecture or hide essential code behind
abstractions. For multiplayer gameplay, make the server the authoritative
source of shared state and rules. Prioritize the required playable milestone:
two remote players, understandable rules, and a public deployment URL.
