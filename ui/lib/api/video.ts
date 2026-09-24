import { api } from "@/lib/api/client";
import type { UploadPartResult, UploadResponse, Video } from "@/lib/types";

export async function getVideo(id: string): Promise<Video> {
  return api.get<Video>(`/api/video/${id}`);
}

export async function createUpload(body: {
  filename: string;
  content_type: string;
  file_size: number;
}): Promise<UploadResponse> {
  return api.post<UploadResponse>("/api/video/upload", body);
}

export async function completeMultipart(
  videoId: string,
  uploadId: string,
  parts: UploadPartResult[],
): Promise<{ status: string }> {
  return api.post(`/api/video/${videoId}/upload/complete`, {
    upload_id: uploadId,
    parts,
  });
}

export async function abortMultipart(
  videoId: string,
  uploadId: string,
): Promise<{ status: string }> {
  return api.post(`/api/video/${videoId}/upload/abort`, { upload_id: uploadId });
}

export async function retryVideo(videoId: string): Promise<Video> {
  return api.post<Video>(`/api/video/${videoId}/retry`);
}
