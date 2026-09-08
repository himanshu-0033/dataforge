"""Evidence aggregation with separate clock domains and explicit missing audio metrics."""

import math


def nearest_rank(values, quantile):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(quantile * len(ordered)) - 1)]


def audio_summary(rows):
    groups = {}
    excluded = []
    failed = []
    for row in rows:
        if row.get("outcome") != "success":
            failed.append({"trial": row.get("trial"), "reason": row.get("outcome", "missing outcome")})
            continue
        reason = None
        if not row.get("old_speech_playing"):
            reason = "old speech was not playing at onset"
        elif not row.get("clock_domain") or row.get("onset_clock") != row.get("output_clock"):
            reason = "clocks not shared"
        elif row.get("measurement") not in ("rendered_loopback_proxy", "acoustic_loopback"):
            reason = "unsupported measurement"
        elif not row.get("recording"):
            reason = "missing recording reference"
        elif any(not isinstance(row.get(k), (float, int)) for k in ("onset_ms", "last_old_sample_ms")):
            reason = "missing sample annotation"
        elif row["last_old_sample_ms"] < row["onset_ms"]:
            reason = "output already silent before onset"
        if reason:
            excluded.append({"trial": row.get("trial"), "reason": reason})
            continue
        key = f"{row['measurement']}/{row.get('temperature', 'unknown')}/{row.get('cache', 'unknown')}"
        groups.setdefault(key, []).append(row["last_old_sample_ms"] - row["onset_ms"])
    return {
        "quantile_method": "nearest-rank",
        "failed_trials": failed,
        "excluded_trials": excluded,
        "groups": {
            k: {
                "n": len(v),
                "p50_ms": nearest_rank(v, 0.5),
                "p95_ms": nearest_rank(v, 0.95),
                "target_eligible": len(v) >= 30 and k.startswith("acoustic_loopback/"),
            }
            for k, v in groups.items()
        },
    }
