"use client";

import { animate, motion, useMotionValue, useReducedMotion } from "framer-motion";
import { MousePointer2, Pause, Play, RotateCcw } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";
import { DemoScreen } from "./demo-screens";
import { DEMO_STEPS, DEMO_TICK_MS, DEMO_TOTAL_MS } from "./demo-timeline";

/** Logical pixel size of the demo canvas — scaled to fit its container. */
const CANVAS_W = 960;
const CANVAS_H = 600;

interface Ripple {
  id: number;
  x: number;
  y: number;
}

function pressTarget(el: Element) {
  if (typeof el.animate !== "function") return;
  el.animate(
    [{ transform: "scale(1)" }, { transform: "scale(0.965)", offset: 0.3 }, { transform: "scale(1)" }],
    { duration: 340, easing: "ease-out" },
  );
}

export function DemoTour() {
  const reduced = useReducedMotion();
  const staticMode = reduced === true;

  const [clock, setClock] = useState({ index: 0, tick: 0 });
  const [paused, setPaused] = useState(false);
  const [inView, setInView] = useState(() => typeof IntersectionObserver === "undefined");
  const [scale, setScale] = useState(0);
  const [cursorOn, setCursorOn] = useState(false);
  const [ripples, setRipples] = useState<Ripple[]>([]);

  const wrapperRef = useRef<HTMLDivElement>(null);
  const boxRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLDivElement>(null);
  const x = useMotionValue(CANVAS_W / 2);
  const y = useMotionValue(CANVAS_H / 2);
  const clickFired = useRef(false);
  const rippleId = useRef(0);

  const { index, tick } = clock;
  const step = DEMO_STEPS[index];
  const running = !staticMode && inView && !paused;

  /* Pause when scrolled away so timers and animations cost nothing off screen. */
  useEffect(() => {
    const el = wrapperRef.current;
    if (!el || typeof IntersectionObserver === "undefined") return;
    const io = new IntersectionObserver(
      (entries) => setInView(entries[0].isIntersecting && entries[0].intersectionRatio >= 0.2),
      { threshold: [0, 0.2, 0.5] },
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);

  /* Scale the fixed 960×600 canvas to the container width. */
  useEffect(() => {
    const el = boxRef.current;
    if (!el) return;
    const apply = () => setScale(el.clientWidth / CANVAS_W);
    apply();
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(apply);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const goTo = useCallback((next: number) => {
    clickFired.current = false;
    setClock({ index: next, tick: 0 });
    setPaused(false);
  }, []);

  /* Master clock: advances the playhead and rolls over to the next step in the
     same state update, so no follow-up effect has to push state after a tick. */
  useEffect(() => {
    if (!running) return;
    const iv = setInterval(() => {
      setClock((c) => {
        const next = c.tick + DEMO_TICK_MS;
        if (next < DEMO_STEPS[c.index].duration) return { index: c.index, tick: next };
        return { index: (c.index + 1) % DEMO_STEPS.length, tick: 0 };
      });
    }, DEMO_TICK_MS);
    return () => clearInterval(iv);
  }, [running]);

  /* Each step's click fires at most once; a new step re-arms it. */
  useEffect(() => {
    clickFired.current = false;
  }, [index]);

  /* The virtual cursor's click: press feedback + ripple, once per step. */
  useEffect(() => {
    if (!running || clickFired.current) return;
    const target = DEMO_STEPS[index];
    if (target.clickAt == null || tick < target.clickAt) return;
    clickFired.current = true;
    const el = canvasRef.current?.querySelector(`[data-target="${target.target}"]`);
    if (el) pressTarget(el);
    const id = rippleId.current++;
    setRipples((rs) => [...rs, { id, x: x.get(), y: y.get() }]);
  }, [tick, running, index, x, y]);

  /* Point the cursor at the current step's target (measured in canvas space). */
  useEffect(() => {
    if (staticMode) return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    const current = DEMO_STEPS[index];
    let raf = 0;
    let tries = 0;

    const move = (tx: number, ty: number) => {
      animate(x, tx, { type: "spring", stiffness: 120, damping: 18, mass: 0.6 });
      animate(y, ty, { type: "spring", stiffness: 120, damping: 18, mass: 0.6 });
    };

    const attempt = () => {
      const el = canvas.querySelector<HTMLElement>(`[data-target="${current.target}"]`);
      if (el) {
        const canvasRect = canvas.getBoundingClientRect();
        const s = canvasRect.width / CANVAS_W || 1;
        const r = el.getBoundingClientRect();
        move(
          (r.left - canvasRect.left) / s + (r.width / s) / 2 - 3,
          (r.top - canvasRect.top) / s + (r.height / s) / 2 - 3,
        );
        setCursorOn(true);
        return;
      }
      if (tries++ < 40) {
        raf = requestAnimationFrame(attempt);
        return;
      }
      move(CANVAS_W - 72, CANVAS_H - 72);
      setCursorOn(false);
    };

    raf = requestAnimationFrame(attempt);
    return () => cancelAnimationFrame(raf);
  }, [index, staticMode, x, y]);

  const progressPct = Math.min(100, (tick / step.duration) * 100);

  return (
    <div ref={wrapperRef}>
      <div className="overflow-hidden rounded-xl border border-zinc-800 bg-zinc-950 shadow-2xl shadow-black/50">
        {/* Browser chrome */}
        <div className="flex items-center gap-1.5 border-b border-zinc-900 bg-zinc-900/70 px-3 py-2.5">
          <span className="h-2.5 w-2.5 rounded-full bg-red-500/80" />
          <span className="h-2.5 w-2.5 rounded-full bg-amber-500/80" />
          <span className="h-2.5 w-2.5 rounded-full bg-emerald-500/80" />
          <span className="ml-3 hidden rounded-md border border-zinc-800 bg-zinc-950 px-2.5 py-0.5 font-mono text-[10px] text-zinc-500 sm:inline">
            app.meridian.dev
          </span>
          <span className="ml-auto font-mono text-[10px] uppercase tracking-[0.12em] text-zinc-600">
            scripted product tour
          </span>
        </div>

        {/* Scaled canvas holding the mock product screens */}
        <div ref={boxRef} className="relative aspect-[8/5] w-full overflow-hidden bg-zinc-950">
          <div
            className="absolute left-0 top-0 origin-top-left transition-opacity duration-300"
            style={{
              width: CANVAS_W,
              height: CANVAS_H,
              transform: `scale(${scale})`,
              opacity: scale > 0 ? 1 : 0,
            }}
          >
            <div aria-hidden="true" className="pointer-events-none absolute inset-0 overflow-hidden">
              <motion.div
                key={step.view}
                initial={{ opacity: 0, y: 14 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.26, ease: [0.22, 1, 0.36, 1] }}
                className="h-full w-full"
              >
                <DemoScreen step={step} running={running} staticMode={staticMode} />
              </motion.div>
            </div>

            {/* Virtual cursor + click ripples */}
            <motion.div
              aria-hidden
              className="pointer-events-none absolute left-0 top-0 z-30"
              style={{ x, y }}
              animate={{ opacity: cursorOn && !staticMode ? 1 : 0 }}
              transition={{ duration: 0.25 }}
            >
              <MousePointer2
                className="h-6 w-6 text-white drop-shadow-[0_2px_3px_rgba(0,0,0,0.85)]"
                fill="currentColor"
                strokeWidth={1.25}
              />
            </motion.div>
            {ripples.map((r) => (
              <motion.span
                key={r.id}
                aria-hidden
                className="pointer-events-none absolute z-20 h-10 w-10 rounded-full border-2 border-brand-400"
                style={{ left: r.x - 20, top: r.y - 20 }}
                initial={{ scale: 0.35, opacity: 0.9 }}
                animate={{ scale: 1.7, opacity: 0 }}
                transition={{ duration: 0.55, ease: "easeOut" }}
                onAnimationComplete={() =>
                  setRipples((rs) => rs.filter((ripple) => ripple.id !== r.id))
                }
              />
            ))}
          </div>
        </div>
      </div>

      {/* Whole-timeline progress */}
      <div className="mt-3 h-0.5 overflow-hidden rounded-full bg-zinc-900">
        <div
          className="h-full bg-gradient-to-r from-brand-600 to-brand-400 transition-[width] duration-100 ease-linear"
          style={{ width: `${progressPct}%` }}
        />
      </div>

      {/* Caption + controls */}
      <div className="mt-4 flex items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="font-mono text-xs text-brand-400">
            {String(index + 1).padStart(2, "0")} / {String(DEMO_STEPS.length).padStart(2, "0")}
          </p>
          <div className="min-h-[46px] overflow-hidden">
            <motion.div
              key={step.id}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.2, ease: [0.22, 1, 0.36, 1] }}
            >
              <p className="mt-1 font-display text-lg font-semibold text-zinc-100">{step.label}</p>
              <p className="text-sm text-zinc-400">{step.caption}</p>
            </motion.div>
          </div>
        </div>

        <div className="flex shrink-0 items-center gap-2">
          {!staticMode && (
            <button
              type="button"
              onClick={() => setPaused((p) => !p)}
              aria-label={paused ? "Play demo" : "Pause demo"}
              className="inline-flex h-9 items-center gap-2 rounded-lg border border-zinc-800 bg-zinc-900/60 px-3 text-xs font-medium text-zinc-300 transition hover:border-zinc-600 hover:text-white"
            >
              {paused ? <Play className="h-3.5 w-3.5" /> : <Pause className="h-3.5 w-3.5" />}
              {paused ? "Play" : "Pause"}
            </button>
          )}
          <button
            type="button"
            onClick={() => goTo(0)}
            aria-label="Restart demo"
            className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-zinc-800 bg-zinc-900/60 text-zinc-300 transition hover:border-zinc-600 hover:text-white"
          >
            <RotateCcw className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      {/* Step picker */}
      <div className="mt-3 flex items-center gap-2">
        {DEMO_STEPS.map((s, i) => (
          <button
            key={s.id}
            type="button"
            onClick={() => goTo(i)}
            aria-label={`Step ${i + 1}: ${s.label}`}
            aria-current={i === index ? "step" : undefined}
            className="group flex h-6 flex-1 items-center"
          >
            <span
              className={cn(
                "h-1.5 w-full rounded-full transition-colors",
                i < index
                  ? "bg-brand-500/50 group-hover:bg-brand-500/70"
                  : i === index
                    ? "bg-brand-500"
                    : "bg-zinc-800 group-hover:bg-zinc-700",
              )}
            />
          </button>
        ))}
        <span className="shrink-0 font-mono text-[11px] text-zinc-600">
          {Math.round(DEMO_TOTAL_MS / 1000)}s loop
        </span>
      </div>

      <p className="sr-only">
        Animated product tour with {DEMO_STEPS.length} steps:{" "}
        {DEMO_STEPS.map((s, i) => `${i + 1}. ${s.label} — ${s.caption}`).join("; ")}.
      </p>
    </div>
  );
}
