from __future__ import annotations

from pipeline.crop import CropPlan, crop_window, plan_crop, smooth_track


class TestSmoothTrack:
    def test_all_missing_uses_fallback(self):
        assert smooth_track([None, None, None], fallback=640.0) == [640.0] * 3

    def test_fills_gaps_from_neighbours(self):
        out = smooth_track([100.0, None, None, 100.0], fallback=0.0, alpha=1.0)
        assert out == [100.0] * 4

    def test_leading_gap_uses_first_known_value(self):
        out = smooth_track([None, None, 200.0], fallback=0.0, alpha=1.0)
        assert out[0] == 200.0

    def test_smoothing_lags_a_jump(self):
        out = smooth_track([0.0] * 3 + [500.0] * 3, fallback=0.0, alpha=0.2)
        # The step must be eased into, not tracked instantly.
        assert out[3] < 200.0
        assert out[-1] > out[3]

    def test_deadzone_suppresses_micro_movement(self):
        jitter = [100.0, 101.0, 99.5, 100.5, 100.0]
        out = smooth_track(jitter, fallback=0.0, alpha=0.5, deadzone=20.0)
        assert len(set(out)) == 1

    def test_empty_input(self):
        assert smooth_track([], fallback=5.0) == []


class TestCropWindow:
    def test_widescreen_source_crops_horizontally(self):
        crop_w, crop_h, y, max_x = crop_window(1920, 1080)

        assert crop_h == 1080
        assert crop_w < 1920
        assert y == 0
        assert max_x == 1920 - crop_w

    def test_already_vertical_source_has_nowhere_to_pan(self):
        crop_w, crop_h, _, max_x = crop_window(1080, 1920)

        assert (crop_w, crop_h) == (1080, 1920)
        assert max_x == 0

    def test_keeps_target_aspect(self):
        for src in ((1920, 1080), (1280, 720), (3840, 2160)):
            crop_w, crop_h, _, _ = crop_window(*src)
            assert abs(crop_w / crop_h - 1080 / 1920) < 0.01

    def test_dimensions_stay_even(self):
        # h264 with yuv420p cannot encode odd dimensions.
        for src in ((1081, 1921), (1279, 719), (999, 555)):
            crop_w, crop_h, _, _ = crop_window(*src)
            assert crop_w % 2 == 0
            assert crop_h % 2 == 0

    def test_taller_than_target_crops_vertically(self):
        crop_w, crop_h, y, max_x = crop_window(1080, 2400)

        assert crop_w == 1080
        assert crop_h < 2400
        assert y > 0
        assert max_x == 0


class TestPlanCrop:
    def test_vertical_source_returns_without_detection(self, tmp_root):
        # max_x == 0, so it returns before touching ffmpeg or a detector.
        plan = plan_crop(
            tmp_root / "does-not-exist.mp4",
            start=0.0,
            duration=10.0,
            src_width=1080,
            src_height=1920,
        )

        assert plan.is_static
        assert plan.static_x == 0

    def test_unreadable_source_falls_back_to_centre(self, tmp_root):
        # Face tracking is an enhancement; its failure must not kill the clip.
        plan = plan_crop(
            tmp_root / "missing.mp4",
            start=0.0,
            duration=5.0,
            src_width=1920,
            src_height=1080,
        )

        assert plan.is_static
        assert plan.static_x == (1920 - plan.crop_w) // 2


class TestSendcmd:
    def test_writes_one_command_per_keyframe(self, tmp_root):
        plan = CropPlan(
            crop_w=405,
            crop_h=720,
            y=0,
            keyframes=[(0.0, 100), (0.5, 104), (1.0, 110)],
        )
        path = plan.write_sendcmd(tmp_root / "cmds.txt")
        lines = path.read_text().strip().splitlines()

        assert lines == ["0.000 crop x 100;", "0.500 crop x 104;", "1.000 crop x 110;"]

    def test_static_plan_reports_itself(self):
        assert CropPlan(crop_w=1, crop_h=1, y=0, static_x=5).is_static
        assert not CropPlan(crop_w=1, crop_h=1, y=0, keyframes=[(0.0, 1)]).is_static
