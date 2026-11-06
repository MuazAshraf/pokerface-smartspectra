from app.signals import Baseline, Sample, read_reaction

CALM = [Sample(70 + (i % 3), 14 + (i % 2) * 0.5, "Neutral") for i in range(20)]


def test_baseline_uses_floors_for_very_steady_players():
    steady = Baseline.from_samples([Sample(70, 14, "Neutral")] * 10)
    assert steady.pulse_std == 3.0 and steady.breath_std == 1.5
    assert steady.stress_share == 0


def test_calm_window_scores_low_with_no_reasons():
    b = Baseline.from_samples(CALM)
    r = read_reaction(b, CALM[:8], 1)
    assert r.score < 0.1
    assert r.reasons == []


def test_stressed_window_scores_high_and_explains_why():
    b = Baseline.from_samples(CALM)
    stressed = [Sample(84, 20, "Fear")] * 8
    r = read_reaction(b, stressed, 4)
    assert r.score > 0.8
    assert "Pulse rose +13 BPM after Question 4" in r.reasons
    assert "Breathing sped up after Question 4" in r.reasons
    assert "Fear expression showed after Question 4" in r.reasons


def test_held_breath_counts_but_lower_pulse_does_not():
    b = Baseline.from_samples(CALM)
    r = read_reaction(b, [Sample(60, 8, "Neutral")] * 8, 2)
    assert r.reasons == ["Breathing slowed after Question 2"]


def test_too_few_samples_returns_none():
    b = Baseline.from_samples(CALM)
    assert read_reaction(b, CALM[:2], 1) is None


def test_breathing_is_optional_and_pulse_alone_can_still_score_high():
    b = Baseline.from_samples([Sample(70 + (i % 3), None, "Neutral") for i in range(20)])
    assert b.breath_mean is None
    r = read_reaction(b, [Sample(84, None, "Fear")] * 8, 1)
    assert r.score > 0.8  # weights renormalise over the signals that exist
    assert "Pulse rose +13 BPM after Question 1" in r.reasons
    assert not any("Breathing" in s for s in r.reasons)
