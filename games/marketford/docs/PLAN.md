# Development plan

Target: 50 hours of focused development. This is an estimate, not a guarantee.

| Work | Hours |
| --- | ---: |
| Rules, formulas, and interface sketches | 4 |
| Town map, rendering, and clock | 6 |
| Townsfolk, routines, and needs | 7 |
| Jobs, wages, rent, and essentials | 7 |
| Guilds, street control, and the guard | 7 |
| Livestock, tools, and upkeep | 4 |
| Controls, inspection, and statistics | 6 |
| Four events and explanatory feed | 3 |
| Testing, balance, and performance | 4 |
| Visual polish and documentation | 2 |
| **Total** | **50** |

## Build sequence

1. Agree on visual direction and choose the implementation stack.
2. Implement deterministic simulation state and one-day advancement.
3. Render the town and expose pause, speed, reset, and inspection controls.
4. Complete the daily economy and demonstrate job-loss consequences.
5. Add guilds, the guard, and livestock and tools incrementally.
6. Add interventions, comparison metrics, and visual polish.

## Acceptance scenarios

- The same seed and interventions produce the same simulation state after 100 days.
- Pausing prevents simulation time from advancing.
- Changing playback speed does not change the result at a given day.
- A mill closure removes its jobs and records affected townsfolk.
- Townsfolk's spending and income can be traced through recorded transactions.
- Three runs with the same seed compare baseline conditions, heavy guard presence, and mill closure.
