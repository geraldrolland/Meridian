"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { Film, Plus, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo } from "react";
import { AuthGuard } from "@/components/auth/auth-guard";
import { AppShell } from "@/components/layout/app-shell";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { VideoCard } from "@/components/video/video-card";
import { getVideo } from "@/lib/api/video";
import { connectVideoWs, type VideoWsHandle } from "@/lib/realtime/ws";
import { getTrackedVideoIds } from "@/lib/video/library";
import type { Video, WsNotification } from "@/lib/types";

function LibraryContent() {
  const queryClient = useQueryClient();
  const ids = useMemo(() => getTrackedVideoIds(), []);

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["library", ids],
    queryFn: async () => {
      if (ids.length === 0) return [] as Video[];
      const results = await Promise.allSettled(ids.map((id) => getVideo(id)));
      return results
        .filter((r): r is PromiseFulfilledResult<Video> => r.status === "fulfilled")
        .map((r) => r.value)
        .sort((a, b) => (a.created_at < b.created_at ? 1 : -1));
    },
  });

  useEffect(() => {
    let handle: VideoWsHandle | null = null;
    handle = connectVideoWs((msg: WsNotification) => {
      void queryClient.invalidateQueries({ queryKey: ["library"] });
      void queryClient.invalidateQueries({ queryKey: ["video", msg.video_id] });
    });
    return () => handle?.close();
  }, [queryClient]);

  const videos = data ?? [];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-3xl font-bold tracking-tight">Library</h1>
          <p className="mt-1 text-sm text-zinc-400">
            Videos tracked on this device · live updates via WebSocket
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={() => void refetch()}>
            <RefreshCw className="h-4 w-4" />
            Refresh
          </Button>
          <Link href="/upload">
            <Button size="sm">
              <Plus className="h-4 w-4" />
              Upload
            </Button>
          </Link>
        </div>
      </div>

      {isLoading ? (
        <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="space-y-3">
              <Skeleton className="aspect-video" />
              <Skeleton className="h-4 w-2/3" />
            </div>
          ))}
        </div>
      ) : isError ? (
        <div className="rounded-2xl border border-red-500/30 bg-red-950/30 p-8 text-center">
          <p className="font-medium text-red-300">Could not load videos</p>
          <Button className="mt-4" variant="outline" onClick={() => void refetch()}>
            Try again
          </Button>
        </div>
      ) : videos.length === 0 ? (
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-zinc-700 bg-zinc-900/30 px-6 py-20 text-center"
        >
          <span className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-brand-500/10 text-brand-400">
            <Film className="h-7 w-7" />
          </span>
          <h2 className="font-display text-xl font-semibold">No videos yet</h2>
          <p className="mt-2 max-w-sm text-sm text-zinc-400">
            Upload your first master file to see pipeline status and adaptive playback here.
          </p>
          <Link href="/upload" className="mt-6">
            <Button>
              <Plus className="h-4 w-4" />
              Upload video
            </Button>
          </Link>
        </motion.div>
      ) : (
        <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {videos.map((v, i) => (
            <VideoCard key={v.id} video={v} index={i} />
          ))}
        </div>
      )}
    </div>
  );
}

export default function DashboardPage() {
  return (
    <AuthGuard>
      <AppShell>
        <LibraryContent />
      </AppShell>
    </AuthGuard>
  );
}
