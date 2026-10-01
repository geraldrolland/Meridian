"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { ArrowLeft, Clock, RotateCcw, ThumbsUp } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { use, useCallback, useEffect, useState } from "react";
import { AuthGuard } from "@/components/auth/auth-guard";
import { AppShell } from "@/components/layout/app-shell";
import { ConnectionPill } from "@/components/layout/connection-pill";
import { DashPlayer } from "@/components/player/dash-player";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import { DeleteVideoButton } from "@/components/video/delete-video-button";
import { PipelineStepper } from "@/components/video/pipeline-stepper";
import { RenditionStrip } from "@/components/video/rendition-strip";
import { StatusChip } from "@/components/video/status-chip";
import { getVideo, retryVideo } from "@/lib/api/video";
import { rewriteStorageUrl } from "@/lib/minio-url";
import { connectVideoWs, type VideoWsHandle, type WsStatus } from "@/lib/realtime/ws";
import { STATUS_META, canDeleteVideo, pipelineStepIndex } from "@/lib/video/status";
import { untrackVideoId } from "@/lib/video/library";
import type { StreamRendition } from "@/lib/video/rendition";
import type { Video } from "@/lib/types";
import { formatDate } from "@/lib/utils";

function VideoDetailContent({ id }: { id: string }) {
  const queryClient = useQueryClient();
  const router = useRouter();
  const { toast } = useToast();
  const [retrying, setRetrying] = useState(false);
  const [wsStatus, setWsStatus] = useState<WsStatus>("connecting");
  const [stream, setStream] = useState<{ videoId: string; data: StreamRendition } | null>(null);
  /** Snapshot is tagged with its video id, so a stale one from another video never renders. */
  const onRendition = useCallback(
    (data: StreamRendition) => setStream({ videoId: id, data }),
    [id],
  );

  const { data: video, isLoading, isError, error } = useQuery({
    queryKey: ["video", id],
    queryFn: () => getVideo(id),
    // No polling: status transitions arrive over the WebSocket, which
    // invalidates this query (and the gateway drops the stale cache entry).
  });

  useEffect(() => {
    let handle: VideoWsHandle | null = null;
    handle = connectVideoWs(
      (msg) => {
        if (msg.video_id === id) {
          // Seed pushed values first so GENERATING_MANIFEST shows the poster and
          // COMPLETED mounts the player without waiting for the refetch round-trip.
          const seed: Partial<Video> = { status: msg.status };
          if (msg.thumbnail_url !== undefined) seed.thumbnail_url = msg.thumbnail_url;
          if (msg.manifest_url !== undefined) seed.manifest_url = msg.manifest_url;
          queryClient.setQueryData<Video>(["video", id], (old) =>
            old ? { ...old, ...seed } : old
          );
          void queryClient.invalidateQueries({ queryKey: ["video", id] });
          if (msg.status === "COMPLETED") {
            const current = queryClient.getQueryData<Video>(["video", id]);
            toast({
              title: "Your video is ready",
              description: `${current?.filename ?? "Your video"} is ready to watch — pushed over WebSocket just now`,
              variant: "success",
            });
          }
        }
      },
      setWsStatus,
    );
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

  const onDeleted = () => {
    untrackVideoId(id);
    void queryClient.invalidateQueries({ queryKey: ["library"] });
    void queryClient.invalidateQueries({ queryKey: ["video", id] });
    router.push("/dashboard");
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
      <div className="rounded-xl border border-red-500/30 bg-red-950/30 p-10 text-center">
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
  const stepIndex = pipelineStepIndex(video.status);

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25, ease: "easeOut" }}
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
            <h1 className="font-display text-3xl font-bold leading-tight tracking-tight sm:text-4xl">
              {video.filename}
            </h1>
            <StatusChip status={video.status} />
          </div>
          <p className="flex flex-wrap items-center gap-3 text-sm text-zinc-500">
            <span className="inline-flex items-center gap-1">
              <Clock className="h-3.5 w-3.5" />
              Created {formatDate(video.created_at)}
            </span>
            <span className="inline-flex items-center gap-1">
              <RotateCcw className="h-3.5 w-3.5" />
              retries {video.num_of_retries}
            </span>
            <span className="font-mono text-xs text-zinc-600">{video.id}</span>
          </p>
          <div className="flex items-center gap-2 text-xs text-zinc-400">
            <span>Live updates on</span>
            <ConnectionPill status={wsStatus} />
          </div>
        </div>
        <div className="flex items-center gap-2">
          {video.status === "RETRY" && (
            <Button onClick={() => void onRetry()} disabled={retrying}>
              <ThumbsUp className="h-4 w-4" />
              {retrying ? "Retrying…" : "Retry processing"}
            </Button>
          )}
          {canDeleteVideo(video.status) && (
            <DeleteVideoButton videoId={id} filename={video.filename} onDeleted={onDeleted} />
          )}
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="min-w-0 space-y-6">
          {canPlay ? (
            <DashPlayer
              url={manifest}
              poster={thumb || undefined}
              videoId={id}
              onRendition={onRendition}
            />
          ) : (
            <div className="relative overflow-hidden rounded-xl border border-zinc-800 bg-zinc-950">
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

          {canPlay && (
            <RenditionStrip state={stream?.videoId === id ? stream.data : null} />
          )}

          <Card>
            <CardHeader className="flex-row items-center justify-between space-y-0">
              <CardTitle className="text-base">Pipeline</CardTitle>
              <span className="font-mono text-xs text-zinc-500">
                Status: {video.status}
                {stepIndex >= 0 ? ` · step ${stepIndex + 1} of 5` : ""}
              </span>
            </CardHeader>
            <CardContent>
              <PipelineStepper status={video.status} />
            </CardContent>
          </Card>
        </div>

        <aside className="space-y-6">
          <Card>
            <CardHeader className="pb-3">
              <p className="text-xs font-semibold uppercase tracking-[0.08em] text-zinc-400">
                What&apos;s happening
              </p>
            </CardHeader>
            <CardContent>
              <p className="text-sm leading-6 text-zinc-300">{meta.description}</p>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="p-6 pt-6">
              <dl className="space-y-4">
                <div className="flex items-center justify-between gap-3">
                  <dt className="text-xs font-semibold uppercase tracking-[0.08em] text-zinc-400">
                    Status
                  </dt>
                  <dd>
                    <StatusChip status={video.status} />
                  </dd>
                </div>
                <div className="flex items-center justify-between gap-3 border-t border-zinc-800 pt-4">
                  <dt className="text-xs font-semibold uppercase tracking-[0.08em] text-zinc-400">
                    Retries
                  </dt>
                  <dd className="font-mono text-sm text-zinc-200">{video.num_of_retries}</dd>
                </div>
                <div className="flex items-center justify-between gap-3 border-t border-zinc-800 pt-4">
                  <dt className="text-xs font-semibold uppercase tracking-[0.08em] text-zinc-400">
                    Published
                  </dt>
                  <dd className="font-mono text-sm text-zinc-200">{video.published ? "Yes" : "No"}</dd>
                </div>
              </dl>
            </CardContent>
          </Card>
        </aside>
      </div>
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
