---
name: flight-search
description: "Use when searching for award flight availability, booking flights with points/miles, or finding best redemption options using the Seats.Aero CLI. MANDATORY for multi-city trips, batch award seat discovery, or searching multiple destinations."
version: 1.0.0
author: Dev-Time
license: MIT
metadata:
  hermes:
    tags: [Flights, Travel, Award Travel, Points, Seats.Aero, CLI]
    homepage: https://seats.aero
prerequisites:
  commands: [seats-aero]
---

# Flight Search via Seats.Aero CLI

This skill ensures you use the Seats.Aero CLI tool efficiently for award flight discovery.

## Core Directives

- Always return the taxes and points
- Verify airport codes with a web search
- Some cities have more than one airport. If the user only specifies a city, search all airports for that city
- If a user-specified city doesn't have its own airport, use a web search to find the closest commercial airport

## STEP 1: The Single-Search Rule (MANDATORY)

The Seats.Aero API is optimized for batched requests. **NEVER loop over destinations or origins in separate CLI calls.**

### Multi-City Batching

If searching from one origin to multiple destinations, you MUST perform **exactly ONE** CLI call per direction:

- **Outbound:** `poetry run seats-aero search -o BOS -d LHR,CDG,AMS,FCO`
- **Return:** `poetry run seats-aero search -o LHR,CDG,AMS,FCO -d BOS`

**NEVER loop.** Combining destinations into a single comma-separated list is significantly faster and preserves API capacity.

## STEP 2: Execute the Search

Use the `search` command to fetch availability. The tool outputs a JSON array to stdout.

```bash
poetry run seats-aero search -o BOS -d LHR,CDG --start-date 2026-05-01 --end-date 2026-05-04 --max-items 0
```

- `--max-items 0`: Fetches the complete result set (overriding the default limit of 1000)
- `--cabins`: Optional. Filter by cabin type (e.g., `economy`, `premium`, `business`, `first`)

## STEP 3: Process Results with JQ

Since the CLI outputs JSON to stdout, pipe the result to `jq` for filtering and formatting.

### Schema Verification

To inspect the available fields in a result:

```bash
poetry run seats-aero search -o BOS -d LHR --max-items 1 | jq '.[0]'
```

Look for fields like `JAvailable` (Business), `JMileageCost`, and `JTotalTaxesRaw`.

### Business Class Filtering Template

```bash
poetry run seats-aero search -o BOS -d LHR,CDG --max-items 0 | jq -c '.[] | select(.JAvailable == true) | {Date, Origin: .Route.OriginAirport, Dest: .Route.DestinationAirport, Miles: .JMileageCost, Tax: (.JTotalTaxesRaw/100), Carriers: .JAirlines}'
```

### Bulk Availability

For broad discovery across a whole program (e.g., "Show me all Emirates business class flights"):

```bash
poetry run seats-aero bulk -s emirates --cabin business --max-items 0 | jq -c '.[] | {Date, Origin: .Route.OriginAirport, Dest: .Route.DestinationAirport, Miles: .JMileageCost}'
```

## Checklist Before Search

- [ ] Have I combined all destinations into a single comma-separated list for the `-d` flag?
- [ ] Am I using `poetry run seats-aero search` with `--max-items 0`?
- [ ] Have I prepared a `jq` command to filter the stdout for the specific cabins requested?
