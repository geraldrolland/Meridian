import Link from "next/link";
import { Button } from "@/components/ui/button";

export default function NotFound() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-zinc-950 px-4 text-center">
      <p className="font-mono text-sm text-brand-500">404</p>
      <h1 className="mt-3 font-display text-4xl font-bold tracking-tight text-zinc-50">
        Page not found
      </h1>
      <p className="mt-3 max-w-md text-zinc-400">
        The route you requested does not exist in MERIDIAN.
      </p>
      <Link href="/" className="mt-8">
        <Button>Back home</Button>
      </Link>
    </div>
  );
}
