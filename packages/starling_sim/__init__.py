"""starling_sim — a simulated warehouse standing in for the physical world
and the cameras, for the sim-driven demo (STATUS.md Step 3).

Special status (see the task brief this package was built from, and
STATUS.md section 4): the simulator is allowed to know ground truth — the
real world "knows" where people are — but it must only ever hand a given
node the observations that node's own camera zone would produce. It never
touches a node's database, config, or in-memory state (CLAUDE.md rule 2
applies to this package exactly as it does to a real camera). Nothing in
this package imports torch/ultralytics — see requirements-sim.txt.
"""
