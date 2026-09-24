import { Router, Request, Response } from 'express';
import pool from '../config/database';
import redis from '../config/redis';

const router = Router();

router.get('/ready', async (_req: Request, res: Response) => {
  const checks: Record<string, 'ok' | 'not_ok'> = {
    db: 'not_ok',
    redis: 'not_ok',
  };

  try {
    await pool.query('SELECT 1');
    checks.db = 'ok';
  } catch (err) {
    console.error('[Ready] DB unreachable:', err instanceof Error ? err.message : err);
  }

  try {
    await redis.ping();
    checks.redis = 'ok';
  } catch (err) {
    console.error('[Ready] Redis unreachable:', err instanceof Error ? err.message : err);
  }

  const allOk = checks.db === 'ok' && checks.redis === 'ok';
  if (allOk) {
    res.json({ status: 'ok', checks });
  } else {
    res.status(500).json({ status: 'not_ok', checks });
  }
});

export default router;
