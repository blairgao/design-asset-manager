from dam.enrichment.video import select_timestamps


def test_scene_changes_are_spaced_and_capped():
    scenes = [0.5, 1.0, 6.2, 6.9, 12.0, 30.0]
    picked = select_timestamps(scenes, 40.0, min_interval=5.0, max_frames=60)
    assert picked == [0.0, 6.2, 12.0, 30.0]


def test_too_few_scenes_falls_back_to_even_sampling():
    picked = select_timestamps([], 22.0, min_interval=5.0, max_frames=60)
    assert picked == [0.0, 5.0, 10.0, 15.0, 20.0]


def test_cap_subsamples_evenly():
    scenes = [float(i * 5) for i in range(200)]
    picked = select_timestamps(scenes, 1000.0, min_interval=5.0, max_frames=60)
    assert len(picked) == 60
    assert picked[0] == 0.0 and picked == sorted(picked)
