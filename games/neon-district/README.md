# Neon District

A cyberpunk neighbourhood simulation about money, power, and the cost of survival.

Watch 100 residents navigate jobs, rent, crime, and cybernetic upgrades while gangs, a corporation, and police compete for control. Change conditions and observe the consequences.

## Project status

Initial design. No application code or dependencies yet.

## First playable milestone

A district map with homes and workplaces, 100 residents, pause and speed controls, and a daily economy. Selecting a resident shows their money, employment, and recent history. A fixed seed makes runs reproducible.

## Scope

- Small 2D grid with abstract travel between buildings.
- Two gangs, one corporation, and one police force.
- Jobs, wages, rent, essentials, faction membership, and territory.
- Cybernetic upgrades with benefits and recurring maintenance costs.
- Inspection panels, statistics, and an explanatory event feed.
- Four interventions: factory closure, blackout, implant shortage, and security sweep.

Detailed pathfinding, animated combat, dialogue, multiplayer, and external AI services are outside the initial version.

## Design principles

- Every major outcome should be explainable through rules and recorded events.
- Keep simulation state independent of rendering and interface code.
- Advance the simulation in discrete ticks; rendering speed must not change outcomes.
- Use seeded randomness and stable entity ordering for repeatable experiments.
- Prioritise a working economy before adding faction behaviour.

See [the development plan](docs/PLAN.md) and [initial design](docs/DESIGN.md).
