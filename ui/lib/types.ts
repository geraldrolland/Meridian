export type VideoStatus =
  | "AWAITING_UPLOAD"
  | "QUEUED"
  | "PROCESSING"
  | "GENERATING_MANIFEST"
  | "COMPLETED"
  | "FAILED"
  | "RETRY";

export interface User {
  id: number;
  email: string;
}

export interface Video {
  id: string;
  filename: string;
  status: VideoStatus;
  user_id: number;
  published: boolean;
  num_of_retries: number;
  notif_reference_id: string | null;
  thumbnail_url: string | null;
  manifest_url: string | null;
  created_at: string;
}

export interface PresignedPostUpload {
  mode: "presigned_post";
  url: string;
  fields: Record<string, string>;
}

export interface UploadPartUrl {
  part_number: number;
  url: string;
}

export interface MultipartUpload {
  mode: "multipart";
  video_id: string;
  upload_id: string;
  part_size: number;
  total_parts: number;
  parts: UploadPartUrl[];
}

export type UploadPlan = PresignedPostUpload | MultipartUpload;

export interface UploadResponse extends Video {
  upload: UploadPlan;
}

export interface UploadPartResult {
  part_number: number;
  etag: string;
}

export interface WsNotification {
  video_id: string;
  status: VideoStatus;
  user_id: number;
  /** Populated on GENERATING_MANIFEST (also persisted server-side). */
  thumbnail_url?: string | null;
  /** Populated on COMPLETED. */
  manifest_url?: string | null;
}

/** Client -> server: per-segment playback metrics (adaptive bitrate loop). */
export interface WsSegmentReport {
  type: "segment_report";
  video_id: string;
  seq: number;
  bandwidth: number; // bps achieved over the segment download
  latency: number; // seconds to first byte
  seg_download_time: number; // seconds for the full segment download
  current_buffer_duration: number; // seconds buffered ahead of playhead
  current_rendition: string; // e.g. "720p"
}

/** Server -> client: rendition to use for the next segment download. */
export interface WsAbrRecommendation {
  type: "abr_recommendation";
  video_id: string;
  seq: number;
  current_rendition: string;
  recommended_rendition: string;
  reason: string;
}

export function isMultipartUpload(upload: UploadPlan): upload is MultipartUpload {
  return upload.mode === "multipart";
}
