"use client";

import { motion } from "framer-motion";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { AuthGuard } from "@/components/auth/auth-guard";
import { AppShell } from "@/components/layout/app-shell";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useToast } from "@/components/ui/toast";
import { Dropzone } from "@/components/video/dropzone";
import { formatBytes } from "@/lib/utils";
import { runUpload, type UploadProgress } from "@/lib/upload/run-upload";

function UploadContent() {
  const router = useRouter();
  const { toast } = useToast();
  const [file, setFile] = useState<File | null>(null);
  const [progress, setProgress] = useState<UploadProgress | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const start = async () => {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const res = await runUpload(file, setProgress);
      toast({
        title: "Upload complete",
        description: "Pipeline will start shortly",
        variant: "success",
      });
      router.push(`/video/${res.id}`);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Upload failed";
      setError(msg);
      toast({ title: "Upload failed", description: msg, variant: "error" });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <div>
        <h1 className="font-display text-3xl font-bold tracking-tight">Upload</h1>
        <p className="mt-1 text-sm text-zinc-400">
          Small files use presigned POST · large files use multipart parts
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Source file</CardTitle>
          <CardDescription>
            mp4, mov, avi, mkv, webm, flv, wmv · direct to MinIO
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-5">
          <Dropzone file={file} onFile={setFile} disabled={busy} />

          {file && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              className="flex items-center justify-between rounded-xl border border-zinc-800 bg-zinc-900/50 px-4 py-3"
            >
              <div className="min-w-0">
                <p className="truncate text-sm font-medium text-zinc-100">{file.name}</p>
                <p className="text-xs text-zinc-500">
                  {formatBytes(file.size)} · {file.type || "video"}
                  {file.size > 100 * 1024 * 1024 ? " · multipart" : " · single PUT"}
                </p>
              </div>
            </motion.div>
          )}

          {progress && (
            <div className="space-y-2">
              <div className="flex justify-between text-xs text-zinc-400">
                <span>{progress.message}</span>
                <span className="font-mono">{progress.percent}%</span>
              </div>
              <div className="h-2 overflow-hidden rounded-full bg-zinc-800">
                <motion.div
                  className="h-full rounded-full bg-gradient-to-r from-brand-600 to-brand-400"
                  initial={{ width: 0 }}
                  animate={{ width: `${progress.percent}%` }}
                  transition={{ ease: "easeOut", duration: 0.3 }}
                />
              </div>
            </div>
          )}

          {error && (
            <p className="rounded-lg border border-red-500/30 bg-red-950/40 px-3 py-2 text-sm text-red-300">
              {error}
            </p>
          )}

          <Button className="w-full" size="lg" disabled={!file || busy} onClick={() => void start()}>
            {busy ? "Uploading…" : "Start upload"}
          </Button>
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
