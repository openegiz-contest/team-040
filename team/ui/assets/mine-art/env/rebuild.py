"""Rebuild the environment end to end (system Python, stdlib only).

    python rebuild.py [--samples 768] [--blender "C:\\Program Files\\Blender Foundation\\Blender 5.1\\blender.exe"]

1. dump_topology.py           -> build/topology.json (team.sim.topology.build_attributes)
2. Blender build_env.py       -> build/env_scene.blend, public/models/mine-art/env.glb,
                                 env_far.jpg, env_near.jpg, previews/*.png
3. Blender check_unlit.py     -> previews/unlit_*.png (GLB re-imported, emission only, no lights):
                                 overview, zone A/B at 3x, and the 1x overview on a 21:9 and a 4:3 stage
4. check_env.py               -> prints the contract and budget numbers, exit code 1 on failure
Blender always runs as a separate background process with --factory-startup.
"""

import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_BLENDER = r"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe"


def run(cmd):
    print(">", " ".join(cmd), flush=True)
    r = subprocess.run(cmd, cwd=HERE)
    if r.returncode:
        sys.exit(r.returncode)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", type=int, default=256)
    ap.add_argument("--blender", default=DEFAULT_BLENDER)
    a = ap.parse_args()
    run([sys.executable, os.path.join(HERE, "dump_topology.py")])
    run([a.blender, "--background", "--factory-startup", "--python", os.path.join(HERE, "build_env.py"),
         "--", "--stage", "full", "--samples", str(a.samples)])
    run([a.blender, "--background", "--factory-startup", "--python", os.path.join(HERE, "check_unlit.py")])
    run([sys.executable, os.path.join(HERE, "check_env.py")])


if __name__ == "__main__":
    main()
