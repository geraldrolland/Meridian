"""Server-driven adaptive bitrate (ABR) recommendation.

The player reports per-segment download metrics over the video service
notification WebSocket after every media segment. This module turns one report
into the rendition the player should use for its *next* segment download.

Policy (see ``recommend_rendition``):
  * downswitch  -- buffer below ``abr_buffer_low``, or measured (safety-adjusted)
    bandwidth cannot comfortably sustain the current rendition. Multi-step down
    is allowed so a bandwidth collapse recovers in a single round trip.
  * upswitch    -- single step only, and only with enough buffer headroom
    (``abr_buffer_high``), enough bandwidth headroom (``abr_upswitch_margin``)
    and acceptable latency (``abr_max_latency``).
  * hold        -- everything in between, so playback does not oscillate.
"""

from typing import Literal

from pydantic import BaseModel, Field

from app.config import settings

REASON_UNKNOWN_RENDITION = "unknown_rendition"
REASON_BUFFER_LOW = "buffer_low"
REASON_INSUFFICIENT_BANDWIDTH = "insufficient_bandwidth"
REASON_NO_HEADROOM = "no_headroom"
REASON_MAX_LATENCY = "max_latency"
REASON_HEADROOM = "headroom"
REASON_HOLD = "hold"


class SegmentReport(BaseModel):
    """Client -> server metrics for one downloaded media segment."""

    type: Literal["segment_report"] = "segment_report"
    video_id: str
    seq: int = Field(ge=0)
    bandwidth: float = Field(ge=0)  # bps achieved over the segment download
    latency: float = Field(ge=0)  # seconds, time to first byte
    seg_download_time: float = Field(ge=0)  # seconds, full segment download
    current_buffer_duration: float = Field(ge=0)  # seconds of buffer ahead
    current_rendition: str  # e.g. "720p"


class AbrRecommendation(BaseModel):
    """Server -> client recommendation for the next segment."""

    type: Literal["abr_recommendation"] = "abr_recommendation"
    video_id: str
    seq: int
    current_rendition: str
    recommended_rendition: str
    reason: str


def _ordered_ladder() -> tuple[list[str], list[int]]:
    """Ladder as parallel name/bitrate lists ordered lowest -> highest bitrate."""
    pairs = sorted(settings.abr_rendition_ladder.items(), key=lambda kv: kv[1])
    return [name for name, _ in pairs], [bitrate for _, bitrate in pairs]


def recommend_rendition(report: SegmentReport) -> AbrRecommendation:
    """Pure decision function: one segment report -> one recommendation."""
    names, bitrates = _ordered_ladder()

    def reply(recommended: str, reason: str) -> AbrRecommendation:
        return AbrRecommendation(
            video_id=report.video_id,
            seq=report.seq,
            current_rendition=report.current_rendition,
            recommended_rendition=recommended,
            reason=reason,
        )

    current = report.current_rendition
    if current not in names:
        return reply(current, REASON_UNKNOWN_RENDITION)

    idx = names.index(current)
    buffer_ = report.current_buffer_duration
    safe_bw = report.bandwidth * settings.abr_safety_factor
    starving = buffer_ < settings.abr_buffer_low
    unaffordable = safe_bw < bitrates[idx] * settings.abr_downswitch_margin

    # --- downswitch (multi-step allowed) ---
    if starving or unaffordable:
        affordable = [i for i, bitrate in enumerate(bitrates) if safe_bw >= bitrate]
        target = max(affordable) if affordable else 0
        if target < idx:
            reason = REASON_INSUFFICIENT_BANDWIDTH if unaffordable else REASON_BUFFER_LOW
            return reply(names[target], reason)
        if starving and idx > 0:
            # Everything is affordable but the buffer is starving: shed one step.
            return reply(names[idx - 1], REASON_BUFFER_LOW)
        reason = REASON_INSUFFICIENT_BANDWIDTH if unaffordable else REASON_BUFFER_LOW
        return reply(current, reason)  # already at the lowest sustainable step

    # --- upswitch (single step) ---
    if idx >= len(names) - 1:
        return reply(current, REASON_HOLD)
    if buffer_ < settings.abr_buffer_high:
        return reply(current, REASON_NO_HEADROOM)
    if report.latency > settings.abr_max_latency:
        return reply(current, REASON_MAX_LATENCY)
    candidate = idx + 1
    if safe_bw < bitrates[candidate] * settings.abr_upswitch_margin:
        return reply(current, REASON_NO_HEADROOM)
    return reply(names[candidate], REASON_HEADROOM)
