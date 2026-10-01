"use client";

import { motion } from "framer-motion";
import { ChevronRight } from "lucide-react";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { AuthGuard } from "@/components/auth/auth-guard";
import { AppShell } from "@/components/layout/app-shell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { useToast } from "@/components/ui/toast";
import { Dropzone } from "@/components/video/dropzone";
import { abortMultipart } from "@/lib/api/video";
import { formatBytes } from "@/lib/utils";
import { runUpload, type UploadProgress } from "@/lib/upload/run-upload";
import { isMultipartUpload, type UploadResponse } from "@/lib/types";

const STAGES = ["PREPARING", "UPLOADING", "FINALIZING"] as const;
const MULTIPART_THRESHOLD = 100 * 1024 * 1024;

function UploadContent() {
  const router = useRouter();
  const { toast } = useToast();
  const [file, setFile] = useState<File | null>(null);
  const [progress, setProgress] = useState<UploadProgress | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const controllerRef = useRef<AbortController | null>(null);
  const uploadRef = useRef<UploadResponse | null>(null);

  const start = async () => {
    if (!file) return;
    setBusy(true);
    setError(null);
    const controller = new AbortController();
    controllerRef.current = controller;
    uploadRef.current = null;
    try {
      const res = await runUpload(file, setProgress, {
        signal: controller.signal,
        onCreated: (r) => {
          uploadRef.current = r;
        },
      });
      toast({
        title: "Upload complete",
        description: "Processing starts automatically",
        variant: "success",
      });
      router.push(`/video/${res.id}`);
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") {
        setProgress(null);
        return;
      }
      const msg = e instanceof Error ? e.message : "Upload failed";
      setError(msg);
      toast({ title: "Upload failed", description: msg, variant: "error" });
    } finally {
      setBusy(false);
      controllerRef.current = null;
    }
  };

  const cancel = async () => {
    controllerRef.current?.abort();
    const up = uploadRef.current;
    if (up && isMultipartUpload(up.upload)) {
      try {
        await abortMultipart(up.id, up.upload.upload_id);
      } catch {
        /* best effort — in-flight request is already aborted */
      }
    }
  };

  const stageIndex = !progress
    ? -1
    : progress.phase === "preparing"
      ? 0
      : progress.phase === "uploading"
        ? 1
        : 2;
  const isMultipart = !!file && file.size > MULTIPART_THRESHOLD;

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <div>
        <h1 className="font-display text-4xl font-bold leading-[42px] tracking-tight">
          Upload video
        </h1>
        <p className="mt-1 text-sm text-zinc-400">
          Files upload directly to storage, then the pipeline takes over.
        </p>
      </div>

      <Card>
        <CardContent className="p-6 pt-6 space-y-5">
          <Dropzone file={file} onFile={setFile} disabled={busy} />

          {file && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              className="flex items-center justify-between gap-3 rounded-xl border border-zinc-800 bg-zinc-900/50 px-4 py-3"
            >
              <div className="min-w-0">
                <p className="truncate text-sm font-medium text-zinc-100">{file.name}</p>
                <p className="font-mono text-xs text-zinc-500">
                  {formatBytes(file.size)} · {file.type || "video"}
                </p>
              </div>
              {isMultipart && <Badge variant="secondary">MULTIPART</Badge>}
            </motion.div>
          )}

          {progress && (
            <div className="space-y-3">
              <ol className="flex flex-wrap items-center gap-2" aria-label="Upload stages">
                {STAGES.map((stage, i) => (
                  <li key={stage} className="flex items-center gap-2">
                    <span
                      className={
                        i === stageIndex
                          ? "text-xs font-semibold uppercase tracking-[0.08em] text-brand-400"
                          : i < stageIndex
                            ? "text-xs font-semibold uppercase tracking-[0.08em] text-emerald-400"
                            : "text-xs font-semibold uppercase tracking-[0.08em] text-zinc-500"
                      }
                      aria-current={i === stageIndex ? "step" : undefined}
                    >
                      {stage}
                    </span>
                    {i < STAGES.length - 1 && (
                      <ChevronRight className="h-3 w-3 text-zinc-700" aria-hidden />
                    )}
                  </li>
                ))}
              </ol>

              <div className="space-y-2">
                <div className="flex justify-between gap-2 text-xs text-zinc-400">
                  <span>
                    {progress.message}
                    {progress.loaded != null
                      ? ` · ${formatBytes(progress.loaded)} of ${formatBytes(file?.size ?? 0)}`
                      : ""}
                  </span>
                  <span className="font-mono">{progress.percent}%</span>
                </div>
                <div className="h-2 overflow-hidden rounded-full bg-zinc-800">
                  <motion.div
                    className="h-full rounded-full bg-gradient-to-r from-brand-600 to-brand-400"
                    initial={{ width: 0 }}
                    animate={{ width: `${progress.percent}%` }}
                    transition={{ ease: "easeOut", duration: 0.2 }}
                  />
                </div>
              </div>
            </div>
          )}

          {error && (
            <p className="rounded-lg border border-red-500/30 bg-red-950/40 px-3 py-2 text-sm text-red-300">
              {error}
            </p>
          )}

          {busy ? (
            <Button
              className="w-full"
              size="lg"
              variant="outline"
              onClick={() => void cancel()}
            >
              Cancel
            </Button>
          ) : (
            <Button
              className="w-full"
              size="lg"
              disabled={!file}
              onClick={() => void start()}
            >
              Start upload
            </Button>
          )}

          <p className="text-center text-xs text-zinc-500">Processing starts automatically</p>
        </CardContent>
      </Card>
    </div>
  );
}

export default function UploadPage() {
  return (
    <AuthGuard>
      <AppShell>
        <UploadContent />
      </AppShell>
    </AuthGuard>
  );
}
