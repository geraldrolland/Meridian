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
}

export function isMultipartUpload(upload: UploadPlan): upload is MultipartUpload {
  return upload.mode === "multipart";
}
