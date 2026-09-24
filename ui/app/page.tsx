"use client";

import { motion } from "framer-motion";
import {
  ArrowRight,
  CheckCircle2,
  Cpu,
  Film,
  Gauge,
  Layers,
  Play,
  Radio,
  Shield,
  Sparkles,
  UploadCloud,
} from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { Logo } from "@/components/brand/logo";
import { FadeIn, Stagger, StaggerItem } from "@/components/motion/animations";

const features = [
  {
    icon: UploadCloud,
    title: "Direct-to-storage upload",
    body: "Presigned POST for small files and resumable multipart for large masters — bytes never bottleneck your API.",
  },
  {
    icon: Cpu,
    title: "Async transcoding pipeline",
    body: "Kafka + Celery workers segment, thumbnail, and rend 360p–1080p CMAF ladders without blocking the UI.",
  },
  {
    icon: Radio,
    title: "Live status over WebSocket",
    body: "Pipeline transitions push to your client the moment status changes — no busy-polling dashboards.",
  },
  {
    icon: Layers,
    title: "MPEG-DASH manifests",
    body: "Static MPD generation and multi-rendition playback ready for adaptive players out of the box.",
  },
  {
    icon: Shield,
    title: "Hardened auth edge",
    body: "JWT + Redis sessions, rotating refresh cookies, and HMAC-signed service hops behind one gateway.",
  },
  {
    icon: Gauge,
    title: "Production observability",
    body: "Unified /ready contracts, structured logs, and outbox reliability across every service boundary.",
  },
];

const steps = [
  { n: "01", title: "Upload", body: "Drop a master file — we validate, sign, and stream it to MinIO." },
  { n: "02", title: "Process", body: "Workers transcode renditions and generate thumbnails asynchronously." },
  { n: "03", title: "Manifest", body: "DASH MPD is built and stored; status flips to COMPLETED." },
  { n: "04", title: "Stream", body: "Open the custom player and switch 360p–1080p in real time." },
];

const pipeline = [
  "AWAITING_UPLOAD",
  "QUEUED",
  "PROCESSING",
  "GENERATING_MANIFEST",
  "COMPLETED",
];

export default function LandingPage() {
  const [demoPlaying, setDemoPlaying] = useState(false);

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100">
      <header className="sticky top-0 z-40 border-b border-zinc-900/80 bg-zinc-950/70 backdrop-blur-xl">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-4 sm:px-6">
          <Logo />
          <nav className="hidden items-center gap-6 text-sm text-zinc-400 md:flex">
            <a href="#product" className="hover:text-zinc-100">Product</a>
            <a href="#demo" className="hover:text-zinc-100">Demo</a>
            <a href="#pipeline" className="hover:text-zinc-100">Pipeline</a>
          </nav>
          <div className="flex items-center gap-2">
            <Link
              href="/login"
              className="inline-flex h-9 items-center rounded-lg px-3 text-sm font-medium text-zinc-300 transition hover:bg-zinc-900 hover:text-white"
            >
              Sign in
            </Link>
            <Link
              href="/register"
              className="inline-flex h-9 items-center rounded-lg bg-brand-500 px-4 text-sm font-medium text-white shadow-[0_0_24px_-6px_rgba(239,25,42,0.6)] transition hover:bg-brand-600"
            >
              Get started
            </Link>
          </div>
        </div>
      </header>

      <main>
        {/* Hero */}
        <section className="relative overflow-hidden bg-grid bg-glow-brand">
          <div className="mx-auto max-w-6xl px-4 pb-24 pt-20 sm:px-6 sm:pt-28">
            <motion.div
              initial={{ opacity: 0, y: 28 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.7, ease: [0.22, 1, 0.36, 1] }}
              className="mx-auto max-w-3xl text-center"
            >
              <span className="mb-6 inline-flex items-center gap-2 rounded-full border border-brand-500/30 bg-brand-500/10 px-3 py-1 text-xs font-medium text-brand-300">
                <Sparkles className="h-3.5 w-3.5" />
                Video infrastructure for modern teams
              </span>
              <h1 className="font-display text-4xl font-bold leading-[1.08] tracking-tight text-white sm:text-6xl">
                Ship video like{" "}
                <span className="bg-gradient-to-r from-brand-400 via-brand-500 to-brand-600 bg-clip-text text-transparent">
                  product
                </span>
                , not infrastructure.
              </h1>
              <p className="mt-6 text-lg leading-relaxed text-zinc-400 sm:text-xl">
                MERIDIAN orchestrates upload, adaptive transcoding, DASH manifests, and real-time
                pipeline UX — so you can focus on the experience your viewers remember.
              </p>
              <div className="mt-10 flex flex-col items-center justify-center gap-3 sm:flex-row">
                <Link
                  href="/register"
                  className="group inline-flex h-12 items-center gap-2 rounded-xl bg-brand-500 px-7 text-base font-semibold text-white shadow-[0_0_40px_-8px_rgba(239,25,42,0.7)] transition hover:bg-brand-600"
                >
                  Start uploading
                  <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
                </Link>
                <a
                  href="#demo"
                  className="inline-flex h-12 items-center gap-2 rounded-xl border border-zinc-700 bg-zinc-900/60 px-7 text-base font-medium text-zinc-200 transition hover:border-zinc-500 hover:bg-zinc-900"
                >
                  <Play className="h-4 w-4" fill="currentColor" />
                  Watch demo
                </a>
              </div>
            </motion.div>

            <motion.div
              initial={{ opacity: 0, y: 40 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.8, delay: 0.2, ease: [0.22, 1, 0.36, 1] }}
              className="mt-16 mx-auto max-w-4xl"
            >
              <div className="rounded-2xl border border-zinc-800 bg-zinc-900/50 p-3 shadow-2xl shadow-black/50">
                <div className="flex items-center gap-1.5 px-2 pb-3">
                  <span className="h-2.5 w-2.5 rounded-full bg-red-500/80" />
                  <span className="h-2.5 w-2.5 rounded-full bg-amber-500/80" />
                  <span className="h-2.5 w-2.5 rounded-full bg-emerald-500/80" />
                  <span className="ml-3 font-mono text-[11px] text-zinc-500">meridian · pipeline</span>
                </div>
                <div className="flex flex-wrap gap-2 px-1 pb-3">
                  {pipeline.map((s, i) => (
                    <motion.span
                      key={s}
                      initial={{ opacity: 0, x: -8 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={{ delay: 0.45 + i * 0.12 }}
                      className={`rounded-md px-2.5 py-1 font-mono text-[11px] ${
                        i === pipeline.length - 1
                          ? "bg-emerald-500/15 text-emerald-400"
                          : "bg-zinc-800 text-zinc-400"
                      }`}
                    >
                      {s}
                    </motion.span>
                  ))}
                </div>
                <div className="grid gap-3 rounded-xl bg-zinc-950/80 p-4 sm:grid-cols-3">
                  {[
                    { label: "Renditions", value: "360p → 1080p" },
                    { label: "Segment", value: "6s CMAF" },
                    { label: "Manifest", value: "MPEG-DASH" },
                  ].map((m, i) => (
                    <motion.div
                      key={m.label}
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      transition={{ delay: 1 + i * 0.1 }}
                      className="rounded-lg border border-zinc-800 bg-zinc-900/60 p-4"
                    >
                      <p className="text-xs uppercase tracking-wider text-zinc-500">{m.label}</p>
                      <p className="mt-1 font-display text-lg font-semibold text-zinc-100">{m.value}</p>
                    </motion.div>
                  ))}
                </div>
              </div>
            </motion.div>
          </div>
        </section>

        {/* Demo */}
        <section id="demo" className="border-y border-zinc-900 bg-zinc-950 py-20">
          <div className="mx-auto max-w-6xl px-4 sm:px-6">
            <FadeIn>
              <div className="mb-10 max-w-2xl">
                <p className="text-sm font-semibold uppercase tracking-widest text-brand-400">Demo</p>
                <h2 className="mt-2 font-display text-3xl font-bold tracking-tight sm:text-4xl">
                  See MERIDIAN in motion
                </h2>
                <p className="mt-3 text-zinc-400">
                  A walkthrough of the product surface — from authenticated upload through adaptive
                  playback.
                </p>
              </div>
            </FadeIn>

            <FadeIn delay={0.1}>
              <div className="relative overflow-hidden rounded-2xl border border-zinc-800 bg-black shadow-2xl">
                {!demoPlaying ? (
                  <button
                    type="button"
                    onClick={() => setDemoPlaying(true)}
                    className="group relative block aspect-video w-full"
                    aria-label="Play product demo"
                  >
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src="/demo/meridian-demo.mp4"
                      alt=""
                      className="absolute inset-0 h-full w-full object-cover opacity-40"
                      onError={(e) => {
                        (e.currentTarget as HTMLImageElement).style.display = "none";
                      }}
                    />
                    <div className="absolute inset-0 bg-gradient-to-t from-zinc-950 via-zinc-950/40 to-zinc-950/20" />
                    <div className="absolute inset-0 flex flex-col items-center justify-center gap-4">
                      <motion.span
                        whileHover={{ scale: 1.05 }}
                        className="flex h-20 w-20 items-center justify-center rounded-full bg-brand-500 text-white shadow-[0_0_60px_-10px_rgba(239,25,42,0.9)]"
                      >
                        <Play className="h-8 w-8 translate-x-0.5" fill="currentColor" />
                      </motion.span>
                      <p className="font-display text-lg font-semibold text-white">
                        Product demo · 0:15
                      </p>
                      <p className="text-sm text-zinc-400">
                        Upload → process → play adaptive DASH
                      </p>
                    </div>
                  </button>
                ) : (
                  <video
                    src="/demo/meridian-demo.mp4"
                    controls
                    autoPlay
                    playsInline
                    className="aspect-video w-full bg-black"
                  >
                    <track kind="captions" />
                  </video>
                )}
              </div>
            </FadeIn>
          </div>
        </section>

        {/* Features */}
        <section id="product" className="py-24">
          <div className="mx-auto max-w-6xl px-4 sm:px-6">
            <FadeIn>
              <div className="mb-14 max-w-2xl">
                <p className="text-sm font-semibold uppercase tracking-widest text-brand-400">
                  Platform
                </p>
                <h2 className="mt-2 font-display text-3xl font-bold tracking-tight sm:text-4xl">
                  Everything between drop and play
                </h2>
              </div>
            </FadeIn>
            <Stagger className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
              {features.map((f) => (
                <StaggerItem key={f.title}>
                  <div className="group h-full rounded-2xl border border-zinc-800 bg-zinc-900/40 p-6 transition-all hover:border-brand-500/30 hover:bg-zinc-900/70">
                    <span className="mb-4 inline-flex h-10 w-10 items-center justify-center rounded-xl bg-brand-500/10 text-brand-400 transition group-hover:bg-brand-500/20">
                      <f.icon className="h-5 w-5" />
                    </span>
                    <h3 className="font-display text-lg font-semibold text-zinc-100">{f.title}</h3>
                    <p className="mt-2 text-sm leading-relaxed text-zinc-400">{f.body}</p>
                  </div>
                </StaggerItem>
              ))}
            </Stagger>
          </div>
        </section>

        {/* Pipeline steps */}
        <section id="pipeline" className="border-t border-zinc-900 bg-zinc-950 py-24">
          <div className="mx-auto max-w-6xl px-4 sm:px-6">
            <FadeIn>
              <div className="mb-14 max-w-2xl">
                <p className="text-sm font-semibold uppercase tracking-widest text-brand-400">
                  Flow
                </p>
                <h2 className="mt-2 font-display text-3xl font-bold tracking-tight sm:text-4xl">
                  Four steps. Zero babysitting.
                </h2>
              </div>
            </FadeIn>
            <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
              {steps.map((s, i) => (
                <FadeIn key={s.n} delay={i * 0.08}>
                  <div className="relative h-full rounded-2xl border border-zinc-800 bg-gradient-to-b from-zinc-900 to-zinc-950 p-6">
                    <span className="font-mono text-sm text-brand-500">{s.n}</span>
                    <h3 className="mt-3 font-display text-xl font-semibold">{s.title}</h3>
                    <p className="mt-2 text-sm text-zinc-400">{s.body}</p>
                  </div>
                </FadeIn>
              ))}
            </div>
          </div>
        </section>

        {/* CTA */}
        <section className="relative overflow-hidden border-t border-zinc-900 py-24">
          <div className="absolute inset-0 bg-glow-brand" aria-hidden />
          <div className="relative mx-auto max-w-3xl px-4 text-center sm:px-6">
            <FadeIn>
              <Film className="mx-auto mb-6 h-10 w-10 text-brand-500" />
              <h2 className="font-display text-3xl font-bold tracking-tight sm:text-4xl">
                Ready to process your first master?
              </h2>
              <p className="mt-4 text-zinc-400">
                Create an account and watch status stream in live as the pipeline does the heavy
                lifting.
              </p>
              <Link
                href="/register"
                className="mt-8 inline-flex h-12 items-center gap-2 rounded-xl bg-brand-500 px-8 text-base font-semibold text-white shadow-[0_0_40px_-8px_rgba(239,25,42,0.7)] transition hover:bg-brand-600"
              >
                Create free account
                <ArrowRight className="h-4 w-4" />
              </Link>
            </FadeIn>
          </div>
        </section>
      </main>

      <footer className="border-t border-zinc-900 py-10">
        <div className="mx-auto flex max-w-6xl flex-col items-center justify-between gap-4 px-4 sm:flex-row sm:px-6">
          <Logo />
          <p className="text-sm text-zinc-500">
            © {new Date().getFullYear()} MERIDIAN · Video processing platform
          </p>
          <div className="flex items-center gap-4 text-sm text-zinc-500">
            <Link href="/login" className="hover:text-zinc-300">Sign in</Link>
            <span className="inline-flex items-center gap-1">
              <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" /> All systems nominal
            </span>
          </div>
        </div>
      </footer>
    </div>
  );
}
