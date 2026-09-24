"use client";

import { motion } from "framer-motion";
import { UploadCloud } from "lucide-react";
import { useCallback, useRef, useState } from "react";
import { cn } from "@/lib/utils";

interface DropzoneProps {
  file: File | null;
  onFile: (f: File | null) => void;
  disabled?: boolean;
}

export function Dropzone({ file, onFile, disabled }: DropzoneProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  const handleFiles = useCallback(
    (files: FileList | null) => {
      if (!files || files.length === 0) return;
      onFile(files[0]);
    },
    [onFile],
  );

  return (
    <motion.div
      animate={dragging ? { scale: 1.01 } : { scale: 1 }}
      transition={{ type: "spring", stiffness: 300, damping: 24 }}
    >
      <button
        type="button"
        disabled={disabled}
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          if (!disabled) handleFiles(e.dataTransfer.files);
        }}
        className={cn(
          "flex w-full flex-col items-center justify-center gap-3 rounded-2xl border-2 border-dashed px-6 py-14 text-center transition-colors",
          dragging
            ? "border-brand-500 bg-brand-500/10"
            : "border-zinc-700 bg-zinc-900/40 hover:border-zinc-500",
          disabled && "pointer-events-none opacity-50",
        )}
        aria-label="Upload video file"
      >
        <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-brand-500/10 text-brand-400">
          <UploadCloud className="h-7 w-7" />
        </span>
        <span className="font-display text-lg font-semibold text-zinc-100">
          {file ? file.name : "Drop a video here"}
        </span>
        <span className="text-sm text-zinc-500">
          {file
            ? "Click or drop to replace"
            : "or click to browse · mp4, mov, avi, mkv, webm, flv, wmv"}
        </span>
      </button>
      <input
        ref={inputRef}
        type="file"
        accept="video/*,.mp4,.mov,.avi,.mkv,.webm,.flv,.wmv"
        className="hidden"
        disabled={disabled}
        onChange={(e) => handleFiles(e.target.files)}
      />
    </motion.div>
  );
}
