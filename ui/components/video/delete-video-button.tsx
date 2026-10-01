"use client";

import { Trash2 } from "lucide-react";
import { useState, type MouseEvent } from "react";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import { deleteVideo } from "@/lib/api/video";
import { cn } from "@/lib/utils";

interface DeleteVideoButtonProps {
  videoId: string;
  filename?: string;
  className?: string;
  /** Compact icon-only button for dashboard cards. */
  iconOnly?: boolean;
  /** Called after the API confirms the delete (untrack, invalidate, navigate). */
  onDeleted?: () => void;
}

/**
 * Two-step inline confirm: first click arms the button (red "Confirm?"),
 * second click sends DELETE /api/video/{id}. Failures reset the arm and toast.
 */
export function DeleteVideoButton({
  videoId,
  filename,
  className,
  iconOnly = false,
  onDeleted,
}: DeleteVideoButtonProps) {
  const { toast } = useToast();
  const [armed, setArmed] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const handleClick = async (e: MouseEvent<HTMLButtonElement>) => {
    e.preventDefault();
    e.stopPropagation();
    if (deleting) return;
    if (!armed) {
      setArmed(true);
      return;
    }
    setDeleting(true);
    try {
      await deleteVideo(videoId);
      toast({
        title: "Video deleted",
        description: filename ? `${filename} was removed` : "The video was removed",
        variant: "success",
      });
      onDeleted?.();
    } catch (err) {
      setArmed(false);
      toast({
        title: "Delete failed",
        description: err instanceof Error ? err.message : undefined,
        variant: "error",
      });
    } finally {
      setDeleting(false);
    }
  };

  return (
    <Button
      type="button"
      size="sm"
      variant={armed ? "destructive" : "outline"}
      onClick={(e) => void handleClick(e)}
      disabled={deleting}
      aria-label={armed ? "Confirm delete video" : "Delete video"}
      data-testid="delete-video"
      data-armed={String(armed)}
      className={cn(iconOnly && "h-8 w-8 p-0 shadow-lg", className)}
    >
      <Trash2 className="h-4 w-4" />
      {!iconOnly && (armed ? "Confirm?" : deleting ? "Deleting…" : "Delete")}
    </Button>
  );
}
