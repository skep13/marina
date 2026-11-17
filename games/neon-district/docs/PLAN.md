# Development plan

Target: 50 hours of focused development. This is an estimate, not a guarantee.

| Work | Hours |
| --- | ---: |
| Rules, formulas, and interface sketches | 4 |
| District map, rendering, and clock | 6 |
| Residents, routines, and needs | 7 |
| Jobs, wages, rent, and essentials | 7 |
| Factions, territory, and policing | 7 |
| Cybernetics and maintenance | 4 |
| Controls, inspection, and statistics | 6 |
| Four events and explanatory feed | 3 |
| Testing, balance, and performance | 4 |
| Visual polish and documentation | 2 |
| **Total** | **50** |

## Build sequence

1. Agree on visual direction and choose the implementation stack.
2. Implement deterministic simulation state and one-day advancement.
3. Render a district and expose pause, speed, reset, and inspection controls.
4. Complete the daily economy and demonstrate job-loss consequences.
5. Add factions and cybernetics incrementally.
6. Add interventions, comparison metrics, and visual polish.

## Acceptance scenarios

- The same seed and interventions produce the same simulation state after 100 days.
- Pausing prevents simulation time from advancing.
- Changing playback speed does not change the result at a given day.
- A factory closure removes its jobs and records affected residents.
- Residents' spending and income can be traced through recorded transactions.
- Three runs with the same seed compare baseline conditions, heavy policing, and factory closure.
