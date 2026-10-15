"""Restart the live team simulator and redeliver an already applied reset command."""

import subprocess

from team.smoke import get, send, values, wait


def main():
    before = values(get("shift"))
    if before["run_state"] != "paused":
        raise RuntimeError("Run the full team smoke first: this check needs a paused completed/decision state")
    ack = next(c for c in reversed(before["commands"])
               if c["type"] == "run.start_preset" and c["status"] == "applied")
    body = dict(command_id=ack["id"], type=ack["type"], target=ack["target"], run=ack["run"])
    subprocess.run(["docker", "compose", "-f", "deploy/compose/docker-compose.yml", "-f", "team/compose.yml",
                    "restart", "team-simulator"], check=True)

    def restored():
        state = values(get("shift"))
        return state if state["publication_seq"] > before["publication_seq"] else None

    after = wait(restored, 30)
    assert after["idSimulationRun"] == before["idSimulationRun"]
    assert after["tick"] == before["tick"]
    send(body["type"], body["target"], body=body)
    wait(lambda: values(get("shift"))["publication_seq"] > after["publication_seq"] + 1)
    assert values(get("shift"))["idSimulationRun"] == before["idSimulationRun"]
    print("PASS: restart preserved run, tick, monotonic heartbeat and reset deduplication", flush=True)


if __name__ == "__main__":
    main()
