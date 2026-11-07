#!/usr/bin/env python3
"""stacks196.py GDBLOG [SNAPS]: what every thread is doing in each gdb snapshot (stacks196.sh).
Per snapshot: threads by state (omp wait/barrier, lock/futex, allocator, I/O, sleep, compute) and, for compute and
lock threads, the first frame in DIAspeXtract/OpenMS code. SNAPS (snaps.txt) gives the time of each snapshot."""
import sys, re, collections

def classify(frames):
    j = " ".join(frames[:8])
    if re.search(r"gomp_team_barrier_wait|gomp_barrier|GOMP_barrier|gomp_thread_start.*futex|do_wait", j) and not re.search(r"OpenMS|diaspextract|Pick|Trace", " ".join(frames[:3])):
        return "omp barrier/idle"
    if re.search(r"GOMP_critical|gomp_mutex_lock|pthread_mutex_lock|__lll_lock|std::mutex|shared_mutex|pthread_rwlock", j): return "lock wait"
    if re.search(r"malloc|_int_free|free\b|operator new|operator delete|mmap|munmap|madvise|brk", " ".join(frames[:4])): return "allocator"
    if re.search(r"\bread\b|pread|__libc_read|fread|sqlite3|zstd|ZSTD|lzf|decompress", " ".join(frames[:5])): return "read/decode"
    if re.search(r"nanosleep|sleep_for|usleep", " ".join(frames[:3])): return "sleep (driver poll)"
    if re.search(r"futex|pthread_cond_wait|__futex", " ".join(frames[:3])): return "futex/cond wait"
    if re.search(r"GOMP_task|gomp_.*task", " ".join(frames[:4])): return "omp task mgmt"
    return "compute"

def ours(frames):
    for f in frames:
        if re.search(r"OpenMS::|DIAspeXtract|diaspextract|\(anonymous namespace\)", f):
            return re.sub(r"\(.*", "", re.sub(r"^#\d+\s+(0x[0-9a-f]+ in )?", "", f))[:90]
    return re.sub(r"^#\d+\s+(0x[0-9a-f]+ in )?", "", frames[0])[:90] if frames else "?"

def main(log, snaps=None):
    times = [l.split()[1] for l in open(snaps)] if snaps else []
    text = open(log, errors="replace").read().split("=====SNAPSHOT=====")[1:]
    for i, s in enumerate(text):
        threads = re.split(r"\nThread \d+ ", s)[1:]
        st, where = collections.Counter(), collections.Counter()
        for th in threads:
            fr = [l.strip() for l in th.splitlines() if l.strip().startswith("#")]
            c = classify(fr); st[c] += 1
            if c in ("compute", "lock wait", "allocator", "read/decode"): where[f"{c}: {ours(fr)}"] += 1
        t = times[i] if i < len(times) else "?"
        print(f"\n## snapshot {i+1} (t={t} s): {len(threads)} threads  " + ", ".join(f"{k} {v}" for k, v in st.most_common()))
        for k, v in where.most_common(8): print(f"   {v:3d}  {k}")

if __name__ == "__main__":
    main(*sys.argv[1:3])
