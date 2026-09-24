import { Request, Response } from 'express';
import redis from '../config/redis';
import config from '../config';

const UPSTREAM_TIMEOUT_MS = 2000;

async function probeUpstream(target: string): Promise<boolean> {
  try {
    const base = target.replace(/\/$/, '');
    const res = await fetch(`${base}/ready`, {
      signal: AbortSignal.timeout(UPSTREAM_TIMEOUT_MS),
    });
    return res.ok;
  } catch {
    return false;
  }
}

export async function readyHandler(_req: Request, res: Response): Promise<void> {
  const checks: Record<string, 'ok' | 'not_ok'> = {};

  try {
    await redis.ping();
    checks.redis = 'ok';
  } catch (err) {
    console.error('[Ready] Redis unreachable:', err instanceof Error ? err.message : err);
    checks.redis = 'not_ok';
  }

  for (const route of config.routes) {
    const ok = await probeUpstream(route.target);
    checks[route.prefix] = ok ? 'ok' : 'not_ok';
  }

  const allOk = Object.values(checks).every((v) => v === 'ok');
  res.status(allOk ? 200 : 500).json({
    status: allOk ? 'ok' : 'not_ok',
    checks,
  });
}
