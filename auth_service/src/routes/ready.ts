import { Router, Request, Response } from 'express';
import pool from '../config/database';

const router = Router();

router.get('/ready', async (_req: Request, res: Response) => {
  try {
    await pool.query('SELECT 1');
    res.json({ status: 'ok', db: 'ok' });
  } catch (err) {
    res.status(500).json({ status: 'error', db: 'unreachable' });
  }
});

export default router;
