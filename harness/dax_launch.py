"""Run corpus2.py unchanged against dax, which has no system java.

dax has the same JDK build as spock/data (OpenJDK 21.0.12.1+1-1-24.04.4-Ubuntu), unpacked at JDK below. Every
ssh to dax gets that JDK first on PATH; the detached runner is also pinned to socket 0 (NUMA node 0) with taskset.
The runner records host (dax) and the resolved java path/version/sha256 itself; pinning is noted in the plan's
results folder (DAX-NOTES.txt). Usage: python3 harness/dax_launch.py preflight|launch|status ... --node dax
"""
import subprocess, sys
from pathlib import Path

JDK = "/scratch/kohlbach/jdk21/bin"
CPUS = "0-95,192-287"  # NUMA node 0 = socket 0, both SMT threads

sys.path.insert(0, str(Path(__file__).resolve().parent))
import corpus2 as C  # noqa: E402

_run = subprocess.run


def run(argv, *a, **kw):
    n = len(C.SSH)
    if isinstance(argv, list) and argv[:n] == C.SSH and len(argv) > n + 1 and argv[n] == "dax":
        rest = argv[n + 1:]
        if rest[0] == "python3":                              # remote(): read-only probes
            rest = ["PATH=%s:$PATH" % JDK] + rest
        elif len(rest) == 1 and rest[0].startswith("setsid nohup python3 "):   # launch_detached()
            rest = ["PATH=%s:$PATH setsid nohup taskset -c %s python3 %s"
                    % (JDK, CPUS, rest[0][len("setsid nohup python3 "):])]
        argv = argv[:n + 1] + rest
    return _run(argv, *a, **kw)


subprocess.run = run
if __name__ == "__main__":
    if "dax" not in sys.argv:
        sys.exit("dax_launch.py is for --node dax only")
    sys.argv[0] = str(Path(C.__file__))
    sys.exit(C.main())
