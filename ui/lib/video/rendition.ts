/**
 * Shared shape for the "current rendition of the segment being played" readout.
 * Produced by DashPlayer (dash.js events + the server ABR loop) and rendered by
 * RenditionStrip on the video detail page.
 */
export type AbrMode =
  /** Server-driven ABR over the video WebSocket. */
  | "auto"
  /** Server-driven requested, socket closed: dash.js client ABR took over. */
  | "fallback"
  /** Viewer picked a rendition from the player's quality menu. */
  | "manual";

export interface AbrRecommendationState {
  current: string;
  recommended: string;
  reason: string;
}

export interface StreamRendition {
  mode: AbrMode;
  ladder: { id: string; label: string }[];
  /** e.g. "720p" — the rendition of the segment currently rendered. */
  rendition: string | null;
  segmentIndex: number | null;
  /** Achieved download throughput for the last segment, bps. */
  bandwidthBps: number | null;
  downloadMs: number | null;
  /** Seconds buffered ahead of the playhead. */
  bufferSec: number | null;
  recommendation: AbrRecommendationState | null;
}

export function emptyStreamRendition(ladder: StreamRendition["ladder"] = []): StreamRendition {
  return {
    mode: "auto",
    ladder,
    rendition: null,
    segmentIndex: null,
    bandwidthBps: null,
    downloadMs: null,
    bufferSec: null,
    recommendation: null,
  };
}

export function currentAbrMode(serverDriven: boolean, wsOpen: boolean): AbrMode {
  if (!serverDriven) return "manual";
  return wsOpen ? "auto" : "fallback";
}

/** Backend ABR reasons (video_service/app/abr.py) rendered for humans. */
const REASON_LABELS: Record<string, string> = {
  hold: "Holding",
  headroom: "Headroom",
  buffer_low: "Buffer low",
  insufficient_bandwidth: "Bandwidth",
  no_headroom: "No headroom",
  max_latency: "Latency capped",
  unknown_rendition: "Unknown",
};

export function reasonLabel(reason?: string | null): string {
  if (!reason) return "ABR";
  return REASON_LABELS[reason] ?? reason.replace(/_/g, " ");
}

export function formatBitrate(bps: number | null): string {
  if (bps === null || !Number.isFinite(bps) || bps <= 0) return "—";
  if (bps >= 1_000_000) {
    const mbps = bps / 1_000_000;
    return `${mbps.toFixed(mbps >= 10 ? 0 : 1)} Mbps`;
  }
  return `${Math.round(bps / 1000)} kbps`;
}
