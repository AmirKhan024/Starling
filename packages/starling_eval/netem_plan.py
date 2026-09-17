"""starling_eval/netem_plan.py
--------------------------------
Pure planning logic for turning a `Scenario` into a timeline of shell
commands. No subprocess is ever invoked here — that's deliberate, so
"test the planner, not the execution" (this session's own instruction)
is possible without Docker: tests/test_scenario.py imports this module
directly and asserts on the returned command lists.

deploy/netem/apply.py is the thin executor built on top of this module.

Mechanism choices (recorded here so they're defensible in a viva):
- Hard partitions use iptables DROP rules between container IPs, not
  netem loss=100% — a DROP rule is an unambiguous full cut, whereas
  100% netem loss can still leave some kernels' TCP control-plane
  behaviour murkier to reason about.
- Loss/latency/jitter (a "degrade", not a full partition) use tc netem,
  which iptables cannot express.
"""

from __future__ import annotations

import json

from starling_eval.scenario import (
    DegradeEvent,
    HealEvent,
    KillEvent,
    LieEvent,
    PartitionEvent,
    ReviveEvent,
    Scenario,
)

# Fixed container IPs from deploy/docker-compose.yml (node-NN -> 172.28.0.1N).
NODE_IPS = {n: f"172.28.0.1{n}" for n in range(10)}


def container_name(node: int) -> str:
    return f"starling-node-{node:02d}"


def _docker_exec(container: str, *cmd: str) -> list[str]:
    return ["docker", "exec", container, *cmd]


def plan_partition(event: PartitionEvent) -> list[list[str]]:
    """DROP rules for every cross-group node pair, both directions."""
    group_of = {n: i for i, group in enumerate(event.groups) for n in group}
    all_nodes = sorted(group_of)

    commands: list[list[str]] = []
    for a in all_nodes:
        for b in all_nodes:
            if a >= b or group_of[a] == group_of[b]:
                continue
            container_a = container_name(a)
            ip_b = NODE_IPS[b]
            commands.append(_docker_exec(container_a, "iptables", "-A", "OUTPUT", "-d", ip_b, "-j", "DROP"))
            commands.append(_docker_exec(container_a, "iptables", "-A", "INPUT", "-s", ip_b, "-j", "DROP"))
    return commands


def plan_heal(all_nodes: list[int]) -> list[list[str]]:
    """Flush every iptables rule and remove any netem qdisc, idempotently
    (a missing qdisc is not an error — the caller runs with check=False).
    """
    commands: list[list[str]] = []
    for n in all_nodes:
        container = container_name(n)
        commands.append(_docker_exec(container, "iptables", "-F"))
        commands.append(_docker_exec(container, "tc", "qdisc", "del", "dev", "eth0", "root"))
    return commands


def plan_degrade(event: DegradeEvent) -> list[list[str]]:
    commands: list[list[str]] = []
    for n in event.nodes:
        netem_args = ["tc", "qdisc", "add", "dev", "eth0", "root", "netem"]
        if event.loss_pct:
            netem_args += ["loss", f"{event.loss_pct}%"]
        if event.latency_ms:
            netem_args += ["delay", f"{event.latency_ms}ms"]
            if event.jitter_ms:
                netem_args.append(f"{event.jitter_ms}ms")
        commands.append(_docker_exec(container_name(n), *netem_args))
    return commands


def plan_kill(event: KillEvent) -> list[list[str]]:
    return [["docker", "stop", container_name(event.node)]]


def plan_revive(event: ReviveEvent) -> list[list[str]]:
    return [["docker", "start", container_name(event.node)]]


_BASE_GOSSIP_PORT = 5555  # matches starling_node.config.NodeConfig.write_template's convention
_CONTROL_PORT_OFFSET = 1000  # matches AttackConfig / apps/node.py's ControlServer port


def plan_lie(event: LieEvent) -> list[list[str]]:
    """WP-10 Part 3: POST `{"attack", "intensity"}` to node `event.node`'s
    control endpoint (`starling_consensus.attacks.ControlServer`, started
    by `apps/node.py`), which binds to `127.0.0.1` ONLY inside its own
    container (never exposed beyond localhost). Reaching it therefore
    needs a command run INSIDE the container, exactly like `plan_partition`'s
    own `_docker_exec` iptables calls above — `curl` is not guaranteed to be
    in the node image, but `python3` is (it IS the node image), so this
    uses a one-line `urllib` call instead. This is the scenario-timeline
    counterpart to the demo's "Make node N lie" button.
    """
    port = _BASE_GOSSIP_PORT + event.node + _CONTROL_PORT_OFFSET
    body = json.dumps({"attack": event.attack, "intensity": event.intensity})
    script = (
        "import urllib.request;"
        f"urllib.request.urlopen(urllib.request.Request("
        f"'http://127.0.0.1:{port}/attack', data={body!r}.encode(), "
        f"headers={{'Content-Type': 'application/json'}}))"
    )
    return [_docker_exec(container_name(event.node), "python3", "-c", script)]


def plan_event(event, scenario: Scenario) -> list[list[str]]:
    if isinstance(event, PartitionEvent):
        return plan_partition(event)
    if isinstance(event, HealEvent):
        return plan_heal(scenario.nodes)
    if isinstance(event, DegradeEvent):
        return plan_degrade(event)
    if isinstance(event, KillEvent):
        return plan_kill(event)
    if isinstance(event, ReviveEvent):
        return plan_revive(event)
    if isinstance(event, LieEvent):
        return plan_lie(event)
    raise ValueError(f"Unknown event kind: {event!r}")


def build_timeline(scenario: Scenario) -> list[tuple[float, list[list[str]]]]:
    """`[(t, [cmd, cmd, ...]), ...]`, in the scenario's own (already
    time-sorted) event order.
    """
    return [(event.t, plan_event(event, scenario)) for event in scenario.events]
