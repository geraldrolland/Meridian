import { Pool } from 'pg';
import config from './index';

/**
 * PostgreSQL connection pool using `pg.Pool`.
 * Maintains up to 10 concurrent connections to the auth database.
 * Connection parameters are sourced from the centralized config.
 */
const pool = new Pool({
  host: config.db.host,
  port: config.db.port,
  user: config.db.user,
  password: config.db.password,
  database: config.db.database,
  max: 10,
});

/**
 * Logs unexpected errors on idle pool clients to prevent silent failures.
 */
pool.on('error', (err) => {
  console.error('[Database] Unexpected error on idle client:', err.message);
});

/**
 * Logs when a new client connects to the pool.
 */
pool.on('connect', () => {
  console.log('[Database] New client connected');
});

export default pool;
