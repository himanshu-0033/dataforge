from pickmate.observability.report import audio_summary, nearest_rank


def test_waiting_trials_and_different_clocks_cannot_be_zero_latency_successes():
    base = {
        "outcome": "success",
        "old_speech_playing": True,
        "clock_domain": "client1",
        "onset_clock": "client1",
        "output_clock": "client1",
        "measurement": "rendered_loopback_proxy",
        "recording": "actual.webm",
        "onset_ms": 100,
        "last_old_sample_ms": 250,
        "temperature": "warm",
        "cache": "uncached",
    }
    report = audio_summary(
        [
            base | {"trial": 1},
            base | {"trial": 2, "old_speech_playing": False},
            base | {"trial": 3, "output_clock": "server"},
            base | {"trial": 4, "outcome": "timeout"},
        ]
    )
    group = report["groups"]["rendered_loopback_proxy/warm/uncached"]
    assert group["n"] == 1 and group["p95_ms"] == 150
    assert group["target_eligible"] is False
    assert len(report["excluded_trials"]) == 2 and len(report["failed_trials"]) == 1


def test_nearest_rank_small_sample_is_stated_without_interpolation():
    assert nearest_rank([100, 200, 300, 400], 0.95) == 400
    assert nearest_rank([], 0.95) is None
