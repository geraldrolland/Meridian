"use client";

import { motion } from "framer-motion";
import { Film, Play } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { StatusChip } from "@/components/video/status-chip";
import { rewriteStorageUrl } from "@/lib/minio-url";
import type { Video } from "@/lib/types";
import { formatDate } from "@/lib/utils";

export function VideoCard({ video, index = 0 }: { video: Video; index?: number }) {
  const thumb = rewriteStorageUrl(video.thumbnail_url);
  const canPlay = video.status === "COMPLETED" && video.manifest_url;

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: Math.min(index * 0.05, 0.3) }}
    >
      <Link
        href={`/video/${video.id}`}
        className="group block overflow-hidden rounded-2xl border border-zinc-800 bg-zinc-900/60 transition-all hover:border-brand-500/40 hover:shadow-[0_0_40px_-12px_rgba(239,25,42,0.35)]"
      >
        <div className="relative aspect-video overflow-hidden bg-zinc-950">
          {thumb ? (
            <Image
              src={thumb}
              alt=""
              fill
              className="object-cover transition-transform duration-500 group-hover:scale-105"
              unoptimized
            />
          ) : (
            <div className="flex h-full items-center justify-center bg-gradient-to-br from-zinc-900 via-zinc-950 to-zinc-900">
              <Film className="h-10 w-10 text-zinc-700" />
            </div>
          )}
          <div className="absolute left-3 top-3">
            <StatusChip status={video.status} />
          </div>
          {canPlay && (
            <div className="absolute inset-0 flex items-center justify-center bg-black/30 opacity-0 transition-opacity group-hover:opacity-100">
              <span className="flex h-12 w-12 items-center justify-center rounded-full bg-brand-500 text-white shadow-lg">
                <Play className="h-5 w-5 translate-x-0.5" fill="currentColor" />
              </span>
            </div>
          )}
        </div>
        <div className="space-y-1 p-4">
          <p className="truncate font-medium text-zinc-100">{video.filename}</p>
          <p className="text-xs text-zinc-500">
            {formatDate(video.created_at)}
            {video.num_of_retries > 0 ? ` · ${video.num_of_retries} retries` : ""}
          </p>
        </div>
      </Link>
    </motion.div>
  );
}
