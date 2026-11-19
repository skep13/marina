# Initial design

These are starting assumptions to refine before implementation.

## Screen layout

- Top bar: simulation day, seed, pause, speed, and reset.
- Centre: town map coloured by building type or controlling guild.
- Right panel: selected townsperson or building details.
- Bottom panel: statistics and a chronological event feed.

Visual direction: parchment and ink surfaces, muted earth tones with a deep red and a forest green for the two guilds, readable typography, and simple woodcut-style buildings. Keep labels and status symbols readable without relying on colour alone.

## State model

- World: seed, random generator state, day, season, policies, and entity collections.
- Townsperson: ID, home, employer, coin, health, guild, and livestock and tools.
- Building: ID, grid position, type, owner (estate, guild, or townsperson), capacity, and operating status.
- Faction (guild, estate, or guard): ID, treasury, influence, and controlled streets.
- Event: day, type, affected entity IDs, and explanation.
- Metrics: daily employment, wealth distribution, crime, street control, and livestock and tool ownership.

## Daily update order

1. Apply scheduled interventions.
2. Update building availability and employment.
3. Pay wages and transfer rent, the lord's tithe, and essential spending.
4. Apply unmet needs and feed and repair costs for livestock and tools.
5. Evaluate theft, guild recruitment, guard patrols, and control of market streets.
6. Record events and aggregate metrics.

Money transfers should have explicit counterparties. Any creation or removal of money should be recorded as an external source or sink.

## First vertical slice

Start with cottages, a mill, a market stall, and 100 townsfolk. Run the economy for 30 days, close the mill, and expose the resulting unemployment and household finances through the map and inspection panel. Add guilds only once this foundation behaves coherently.

## Decisions still open

- Language, framework, and renderer.
- Exact map dimensions and economic parameters.
- Whether the player acts as an observer or has a limited intervention budget.
- How much individual movement is shown on the map.
