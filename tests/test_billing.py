from cloud_inference_server.billing import count_asr_point_units, count_tts_point_units, format_points


def test_tts_points_mix_cjk_and_non_cjk():
    units = count_tts_point_units("你好ab!")
    assert units == 245
    assert format_points(units) == 2.45


def test_tts_points_ignore_whitespace():
    units = count_tts_point_units("你 好 a b\n")
    assert units == 230


def test_asr_points_round_up_by_total_duration():
    assert count_asr_point_units(0.01) == 100
    assert count_asr_point_units(1.0) == 100
    assert count_asr_point_units(1.01) == 200