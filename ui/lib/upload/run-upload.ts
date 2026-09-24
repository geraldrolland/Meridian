import { createUpload } from "@/lib/api/video";
import { isMultipartUpload, type UploadPartResult, type UploadResponse } from "@/lib/types";
import { trackVideoId } from "@/lib/video/library";

export interface UploadProgress {
  phase: "preparing" | "uploading" | "finalizing" | "done";
  percent: number;
  message: string;
}

export type ProgressFn = (p: UploadProgress) => void;

const ALLOWED_EXT = ["mp4", "mov", "avi", "mkv", "webm", "flv", "wmv"];

export function validateVideoFile(file: File): string | null {
  const ext = file.name.split(".").pop()?.toLowerCase() ?? "";
  if (!ALLOWED_EXT.includes(ext)) {
    return `File extension '${ext}' is not allowed. Allowed: ${ALLOWED_EXT.join(", ")}`;
  }
  if (file.size <= 0) return "File is empty";
  return null;
}

async function uploadPresigned(
  file: File,
  upload: { url: string; fields: Record<string, string> },
  onProgress: ProgressFn,
): Promise<void> {
  const form = new FormData();
  for (const [key, value] of Object.entries(upload.fields)) {
    form.append(key, value);
  }
  form.append("file", file);

  await new Promise<void>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", upload.url, true);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) {
        const percent = Math.round((e.loaded / e.total) * 100);
        onProgress({
          phase: "uploading",
          percent,
          message: `Uploading… ${percent}%`,
        });
      }
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve();
      else reject(new Error(`Storage upload failed (${xhr.status})`));
    };
    xhr.onerror = () => reject(new Error("Network error during upload"));
    xhr.send(form);
  });
}

async function uploadMultipart(
  file: File,
  res: UploadResponse,
  onProgress: ProgressFn,
): Promise<UploadPartResult[]> {
  if (!isMultipartUpload(res.upload)) return [];
  const upload = res.upload;
  const partsList = upload.parts;
  const partSize = upload.part_size;

  const etags: UploadPartResult[] = [];
  const total = file.size;
  let loaded = 0;
  const concurrency = 3;
  let index = 0;

  async function worker() {
    while (index < partsList.length) {
      const i = index++;
      const part = partsList[i];
      const start = i * partSize;
      const end = Math.min(start + partSize, file.size);
      const blob = file.slice(start, end);

      const putRes = await fetch(part.url, {
        method: "PUT",
        body: blob,
        headers: { "Content-Type": file.type || "video/mp4" },
      });
      if (!putRes.ok) throw new Error(`Part ${part.part_number} upload failed (${putRes.status})`);

      const etag =
        putRes.headers.get("ETag")?.replace(/"/g, "") ||
        putRes.headers.get("etag")?.replace(/"/g, "");
      if (!etag) throw new Error(`Missing ETag for part ${part.part_number}`);

      etags.push({ part_number: part.part_number, etag });
      loaded += end - start;
      const percent = Math.min(99, Math.round((loaded / total) * 100));
      onProgress({
        phase: "uploading",
        percent,
        message: `Uploading parts… ${percent}%`,
      });
    }
  }

  await Promise.all(Array.from({ length: Math.min(concurrency, partsList.length) }, worker));
  etags.sort((a, b) => a.part_number - b.part_number);
  return etags;
}

export async function runUpload(file: File, onProgress: ProgressFn): Promise<UploadResponse> {
  const validation = validateVideoFile(file);
  if (validation) throw new Error(validation);

  onProgress({ phase: "preparing", percent: 0, message: "Preparing upload…" });

  const res = await createUpload({
    filename: file.name,
    content_type: file.type || "video/mp4",
    file_size: file.size,
  });

  trackVideoId(res.id);

  if (isMultipartUpload(res.upload)) {
    const parts = await uploadMultipart(file, res, onProgress);
    onProgress({ phase: "finalizing", percent: 99, message: "Finalizing multipart upload…" });
    const { completeMultipart } = await import("@/lib/api/video");
    await completeMultipart(res.id, res.upload.upload_id, parts);
  } else {
    await uploadPresigned(file, res.upload, onProgress);
    onProgress({ phase: "finalizing", percent: 100, message: "Waiting for processing…" });
  }

  onProgress({ phase: "done", percent: 100, message: "Upload complete" });
  return res;
}
