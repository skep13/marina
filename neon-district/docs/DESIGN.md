# Initial design

These are starting assumptions to refine before implementation.

## Screen layout

- Top bar: simulation day, seed, pause, speed, and reset.
- Centre: district map coloured by building type or controlling faction.
- Right panel: selected resident or building details.
- Bottom panel: statistics and a chronological event feed.

Visual direction: dark charcoal surfaces, restrained neon cyan and magenta accents, readable typography, and simple geometric buildings. Keep labels and status symbols readable without relying on colour alone.

## State model

- World: seed, random generator state, day, policies, and entity collections.
- Resident: ID, home, employer, money, health, faction, and implants.
- Building: ID, grid position, type, owner, capacity, and operating status.
- Faction: ID, treasury, influence, and controlled blocks.
- Event: day, type, affected entity IDs, and explanation.
- Metrics: daily employment, wealth distribution, crime, territory, and implant adoption.

## Daily update order

1. Apply scheduled interventions.
2. Update building availability and employment.
3. Pay wages and transfer rent and essential spending.
4. Apply unmet needs and implant maintenance effects.
5. Evaluate crime, recruitment, policing, and territorial influence.
6. Record events and aggregate metrics.

Money transfers should have explicit counterparties. Any creation or removal of money should be recorded as an external source or sink.

## First vertical slice

Start with homes, a factory, a shop, and 100 residents. Run the economy for 30 days, close the factory, and expose the resulting unemployment and household finances through the map and inspection panel. Add gangs only once this foundation behaves coherently.

## Decisions still open

- Language, framework, and renderer.
- Exact map dimensions and economic parameters.
- Whether the player acts as an observer or has a limited intervention budget.
- How much individual movement is shown on the map.
