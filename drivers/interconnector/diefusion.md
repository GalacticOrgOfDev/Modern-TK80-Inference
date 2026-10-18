# DieFusionCore

Goal: present the two independent 12 GB K80 dies as one logical device.

## Why it is hard

The K80 has no unified memory. Each die is a separate GPU. Fusion must be explicit.

## Strategies (planned)

| Strategy | Idea |
|----------|------|
| pipeline | Stage sequential work (e.g. encode on die 0, decode on die 1) |
| layer | Split model layers across dies (experimental) |
| data | Split batch or sequence across dies |

## Current status

Foundation only:
- Detects whether two free dies exist
- Reports aggregate capacity
- Builds a plan without moving data yet
- Can be activated / deactivated

Data movement, scheduling, and transparent model placement come next.
