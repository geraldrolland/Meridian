"""Tests for the pure server-side ABR recommendation policy.

Ladder under test (defaults from app/config.py):
    360p=800kbps, 480p=1.4Mbps, 720p=2.5Mbps, 1080p=4.5Mbps
    safety=0.75, buffer_low=9s, buffer_high=10s,
    up_margin=1.10, down_margin=0.85, max_latency=0.6s
"""

import pytest
from pydantic import ValidationError

from app.abr import (
    REASON_BUFFER_LOW,
    REASON_HEADROOM,
    REASON_INSUFFICIENT_BANDWIDTH,
    REASON_MAX_LATENCY,
    REASON_NO_HEADROOM,
    REASON_UNKNOWN_RENDITION,
    AbrRecommendation,
    SegmentReport,
    recommend_rendition,
)


def _report(**overrides) -> SegmentReport:
    base = {
        "video_id": "v-1",
        "seq": 3,
        "bandwidth": 5_000_000,
        "latency": 0.05,
        "seg_download_time": 1.2,
        "current_buffer_duration": 20.0,
        "current_rendition": "360p",
    }
    base.update(overrides)
    return SegmentReport(**base)


class TestSegmentReportModel:
    def test_accepts_valid_report(self):
        report = _report()
        assert report.type == "segment_report"
        assert report.seq == 3

    def test_rejects_negative_seq(self):
        with pytest.raises(ValidationError):
            _report(seq=-1)

    def test_rejects_negative_bandwidth(self):
        with pytest.raises(ValidationError):
            _report(bandwidth=-1)

    def test_rejects_missing_video_id(self):
        with pytest.raises(ValidationError):
            SegmentReport(
                type="segment_report",
                seq=1,
                bandwidth=1,
                latency=0.1,
                seg_download_time=1,
                current_buffer_duration=5,
                current_rendition="720p",
            )


class TestUpswitch:
    def test_single_step_with_headroom(self):
        result = recommend_rendition(_report())
        assert isinstance(result, AbrRecommendation)
        assert result.recommended_rendition == "480p"  # one step, not straight to 720p
        assert result.reason == REASON_HEADROOM
        assert result.seq == 3
        assert result.current_rendition == "360p"

    def test_blocked_by_low_buffer(self):
        # 9.5s sits in the dead zone (buffer_low=9 <= b < buffer_high=10) while
        # bandwidth alone would allow the upswitch: only the buffer gate blocks.
        result = recommend_rendition(
            _report(
                current_buffer_duration=9.5,
                current_rendition="720p",
                bandwidth=8_000_000,
            )
        )
        assert result.recommended_rendition == "720p"
        assert result.reason == REASON_NO_HEADROOM

    def test_blocked_by_high_latency(self):
        result = recommend_rendition(_report(latency=0.9))
        assert result.recommended_rendition == "360p"
        assert result.reason == REASON_MAX_LATENCY

    def test_blocked_by_insufficient_bandwidth(self):
        # safe bw = 3M < 1080p*1.10 = 4.95M
        result = recommend_rendition(
            _report(
                current_rendition="720p",
                bandwidth=4_000_000,
                current_buffer_duration=20.0,
            )
        )
        assert result.recommended_rendition == "720p"
        assert result.reason == REASON_NO_HEADROOM

    def test_holds_at_top_of_ladder(self):
        result = recommend_rendition(
            _report(current_rendition="1080p", bandwidth=50_000_000)
        )
        assert result.recommended_rendition == "1080p"
        assert result.reason == "hold"


class TestDownswitch:
    def test_single_step_on_bandwidth_drop(self):
        # safe bw = 1.65M < 720p*0.85 = 2.125M; 480p still affordable
        result = recommend_rendition(
            _report(current_rendition="720p", bandwidth=2_200_000)
        )
        assert result.recommended_rendition == "480p"
        assert result.reason == REASON_INSUFFICIENT_BANDWIDTH

    def test_multi_step_on_collapse(self):
        # safe bw = 900k -> only 360p affordable from 1080p
        result = recommend_rendition(
            _report(current_rendition="1080p", bandwidth=1_200_000)
        )
        assert result.recommended_rendition == "360p"
        assert result.reason == REASON_INSUFFICIENT_BANDWIDTH

    def test_starving_steps_down_even_if_affordable(self):
        # plenty of bandwidth but only 5s of buffer left
        result = recommend_rendition(
            _report(current_rendition="720p", current_buffer_duration=5.0)
        )
        assert result.recommended_rendition == "480p"
        assert result.reason == REASON_BUFFER_LOW

    def test_starving_at_lowest_holds(self):
        result = recommend_rendition(
            _report(current_rendition="360p", current_buffer_duration=3.0)
        )
        assert result.recommended_rendition == "360p"
        assert result.reason == REASON_BUFFER_LOW

    def test_holds_at_lowest_when_nothing_is_affordable(self):
        # safe bw = 375k: even 360p (800k) is out of reach while starving
        result = recommend_rendition(
            _report(current_rendition="360p", bandwidth=500_000,
                    current_buffer_duration=4.0)
        )
        assert result.recommended_rendition == "360p"
        assert result.reason == REASON_INSUFFICIENT_BANDWIDTH


class TestHold:
    def test_deadzone_holds(self):
        # buffer between buffer_low (9s) and buffer_high (10s), bandwidth ample:
        # safe 6M >= 720p*1.10 = 2.75M, but the buffer gate holds the rung.
        result = recommend_rendition(
            _report(current_rendition="480p", bandwidth=8_000_000,
                    current_buffer_duration=9.5)
        )
        assert result.recommended_rendition == "480p"
        assert result.reason == REASON_NO_HEADROOM

    def test_unknown_rendition_holds(self):
        result = recommend_rendition(_report(current_rendition="144p"))
        assert result.recommended_rendition == "144p"
        assert result.reason == REASON_UNKNOWN_RENDITION

    def test_reply_is_json_serializable_with_correct_type(self):
        payload = recommend_rendition(_report()).model_dump()
        assert payload["type"] == "abr_recommendation"
        assert payload["video_id"] == "v-1"
        assert set(payload) == {
            "type",
            "video_id",
            "seq",
            "current_rendition",
            "recommended_rendition",
            "reason",
        }
