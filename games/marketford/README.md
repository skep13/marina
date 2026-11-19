# Marketford

A medieval market town simulation about coin, power, and the cost of getting through the year.

Watch 100 townsfolk work, pay rent, steal, and invest in livestock and tools while two rival guilds, the lord's estate, and the town guard compete for control. Change conditions and observe the consequences.

## Project status

Initial design. No application code or dependencies yet.

## First playable milestone

A town map with cottages and workplaces, 100 townsfolk, pause and speed controls, and a daily economy. Selecting a townsperson shows their coin, employment, and recent history. A fixed seed makes runs reproducible.

## Scope

- Small 2D grid with abstract travel between buildings.
- Two rival guilds, the lord's estate, and the town guard.
- Jobs, wages, rent, essentials, guild membership, and control of market streets.
- Livestock and tools that raise earnings but carry recurring feed and repair costs.
- Inspection panels, statistics, and an explanatory event feed.
- Four interventions: mill closure, plague quarantine, harvest failure, and guard sweep.

Detailed pathfinding, animated combat, dialogue, multiplayer, and external AI services are outside the initial version.

## Design principles

- Every major outcome should be explainable through rules and recorded events.
- Keep simulation state independent of rendering and interface code.
- Advance the simulation in discrete ticks; rendering speed must not change outcomes.
- Use seeded randomness and stable entity ordering for repeatable experiments.
- Prioritise a working economy before adding guild behaviour.

See [the development plan](docs/PLAN.md) and [initial design](docs/DESIGN.md).
