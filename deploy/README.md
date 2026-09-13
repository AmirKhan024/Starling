# Running Starling nodes under Docker

Four isolated node containers (`node-00`..`node-03`) plus a legacy
dashboard viewer, on a user-defined bridge network (`starling-net`,
`172.28.0.0/24`) with fixed IPs so Prompt 4's partition scripts can address
each node directly.

Each `node-NN` container mounts `./configs` and `./data/videos` read-only,
and **only its own** `./data/nodes/node-NN` directory read-write. No
container can see another node's SQLite replica — that's CLAUDE.md rule 2
made physical, not just conventional. `tests/test_docker_compose.py`
enforces this from the compose file itself.

## Validate the compose file (no build required)

```
docker compose -f deploy/docker-compose.yml config
```

## Build the images

```
docker compose -f deploy/docker-compose.yml build
```

## Bring the network up

```
docker compose -f deploy/docker-compose.yml up -d
```

## Tail one node's logs

```
docker compose -f deploy/docker-compose.yml logs -f node-02
```

## Stop one node (e.g. to demo partition tolerance)

```
docker compose -f deploy/docker-compose.yml stop node-02
```

It stays stopped (`restart: "no"`) — the other three keep running and
producing claims, which is the point.

## Tear the whole network down

```
docker compose -f deploy/docker-compose.yml down
```

## Open the dashboard

<http://localhost:8501> once `dashboard` is up. It currently watches the
frozen `apps/baseline.py`'s centralized `database/identities.db` only — it
has no node-data mount, and does not yet observe node claims (that's
WP-13's job: rebuilding it as a read-only gossip observer).
