"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { ArrowLeft, Clock, RotateCcw, ThumbsUp } from "lucide-react";
import Link from "next/link";
import { use, useEffect, useState } from "react";
import { AuthGuard } from "@/components/auth/auth-guard";
import { AppShell } from "@/components/layout/app-shell";
import { DashPlayer } from "@/components/player/dash-player";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import { PipelineStepper } from "@/components/video/pipeline-stepper";
import { StatusChip } from "@/components/video/status-chip";
import { getVideo, retryVideo } from "@/lib/api/video";
import { rewriteStorageUrl } from "@/lib/minio-url";
import { connectVideoWs, type VideoWsHandle } from "@/lib/realtime/ws";
import { STATUS_META } from "@/lib/video/status";
import { formatDate } from "@/lib/utils";

function VideoDetailContent({ id }: { id: string }) {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const [retrying, setRetrying] = useState(false);

  const { data: video, isLoading, isError, error } = useQuery({
    queryKey: ["video", id],
    queryFn: () => getVideo(id),
    refetchInterval: (query) => {
      const s = query.state.data?.status;
      if (!s || s === "COMPLETED" || s === "FAILED" || s === "RETRY") return false;
      return 8000;
    },
  });

  useEffect(() => {
    let handle: VideoWsHandle | null = null;
    handle = connectVideoWs((msg) => {
      if (msg.video_id === id) {
        void queryClient.invalidateQueries({ queryKey: ["video", id] });
        if (msg.status === "COMPLETED") {
          toast({ title: "Ready to play", variant: "success" });
        }
      }
    });
    return () => handle?.close();
  }, [id, queryClient, toast]);

  const onRetry = async () => {
    setRetrying(true);
    try {
      await retryVideo(id);
      await queryClient.invalidateQueries({ queryKey: ["video", id] });
      toast({ title: "Requeued", description: "Video is back in the pipeline", variant: "success" });
    } catch (e) {
      toast({
        title: "Retry failed",
        description: e instanceof Error ? e.message : undefined,
        variant: "error",
      });
    } finally {
      setRetrying(false);
    }
  };

  if (isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="aspect-video w-full" />
        <Skeleton className="h-24 w-full" />
      </div>
    );
  }

  if (isError || !video) {
    return (
      <div className="rounded-2xl border border-red-500/30 bg-red-950/30 p-10 text-center">
        <p className="font-medium text-red-300">
          {error instanceof Error ? error.message : "Video not found"}
        </p>
        <Link href="/dashboard" className="mt-4 inline-block">
          <Button variant="outline">Back to library</Button>
        </Link>
      </div>
    );
  }

  const meta = STATUS_META[video.status];
  const manifest = rewriteStorageUrl(video.manifest_url);
  const thumb = rewriteStorageUrl(video.thumbnail_url);
  const canPlay = video.status === "COMPLETED" && !!manifest;

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      className="space-y-6"
    >
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-2">
          <Link
            href="/dashboard"
            className="inline-flex items-center gap-1 text-sm text-zinc-400 hover:text-zinc-200"
          >
            <ArrowLeft className="h-4 w-4" />
            Library
          </Link>
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="font-display text-2xl font-bold tracking-tight sm:text-3xl">
              {video.filename}
            </h1>
            <StatusChip status={video.status} />
          </div>
          <p className="flex flex-wrap items-center gap-3 text-sm text-zinc-500">
            <span className="inline-flex items-center gap-1">
              <Clock className="h-3.5 w-3.5" />
              {formatDate(video.created_at)}
            </span>
            {video.num_of_retries > 0 && (
              <span className="inline-flex items-center gap-1">
                <RotateCcw className="h-3.5 w-3.5" />
                {video.num_of_retries} retries
              </span>
            )}
            <span className="font-mono text-xs text-zinc-600">{video.id}</span>
          </p>
        </div>
        {video.status === "RETRY" && (
          <Button onClick={() => void onRetry()} disabled={retrying}>
            <ThumbsUp className="h-4 w-4" />
            {retrying ? "Retrying…" : "Retry processing"}
          </Button>
        )}
      </div>

      {canPlay ? (
        <DashPlayer url={manifest} poster={thumb || undefined} />
      ) : (
        <div className="relative overflow-hidden rounded-2xl border border-zinc-800 bg-zinc-950">
          <div className="flex aspect-video flex-col items-center justify-center gap-3 bg-grid">
            {thumb ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={thumb} alt="" className="absolute inset-0 h-full w-full object-cover opacity-20" />
            ) : null}
            <div className="relative z-10 text-center">
              <p className="font-display text-xl font-semibold text-zinc-200">{meta.label}</p>
              <p className="mt-1 text-sm text-zinc-500">{meta.description}</p>
              {video.status === "FAILED" && (
                <p className="mt-4 max-w-md text-sm text-red-400/90">
                  Processing failed after retries. Contact support with the video ID if this
                  persists.
                </p>
              )}
              {video.status === "AWAITING_UPLOAD" && (
                <p className="mt-4 text-sm text-zinc-500">
                  Waiting for storage confirmation after your upload…
                </p>
              )}
            </div>
          </div>
        </div>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Pipeline</CardTitle>
        </CardHeader>
        <CardContent>
          <PipelineStepper status={video.status} />
        </CardContent>
      </Card>
    </motion.div>
  );
}

export default function VideoDetailPage({ params }: PageProps<"/video/[id]">) {
  const { id } = use(params);
  return (
    <AuthGuard>
      <AppShell>
        <VideoDetailContent id={id} />
      </AppShell>
    </AuthGuard>
  );
}
