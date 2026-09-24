import fs from 'fs';
import path from 'path';
import express from 'express';
import helmet from 'helmet';
import cookieParser from 'cookie-parser';
import config, { logger } from './config';
import { checkProxySignature } from './middleware/checkProxySignature';
import { errorHandler } from './middleware/errorHandler';
import { requestLogger } from './middleware/requestLogger';
import authRoutes from './routes/auth';
import readyRoutes from './routes/ready';

const app = express();

app.use(helmet());
app.use(cookieParser());
app.use(express.json({ limit: '10mb' }));
app.use(express.urlencoded({ extended: true }));
app.use(requestLogger);

/**
 * GET / — Health check endpoint.
 * Returns service status and current timestamp.
 */
app.get('/', (_req, res) => {
  res.json({ status: 'ok', service: 'auth-service', timestamp: new Date().toISOString() });
});

/**
 * GET /health — Health check endpoint (alias).
 * Used by Docker healthcheck and orchestrators.
 */
app.get('/health', (_req, res) => {
  res.json({ status: 'ok', service: 'auth-service', timestamp: new Date().toISOString() });
});

/**
 * All /api/auth/* routes are protected by the proxy signature middleware.
 * The gateway signs every forwarded request with HMAC-SHA256;
 * this middleware verifies the signature before any route handler runs.
 */
app.use('/api/auth', checkProxySignature, authRoutes);

app.use(readyRoutes);

/**
 * 404 fallback — catches any request that doesn't match a defined route.
 */
app.use((_req, res) => {
  res.status(404).json({ error: 'Route not found' });
});

app.use(errorHandler);

/**
 * Runs the SQL migration to create the `users` table if it doesn't exist.
 * Reads the migration file from `migrations/001_create_users.sql` and
 * executes it against the PostgreSQL database.
 *
 * Called once at server startup before the HTTP listener is bound.
 */
async function runMigrations(): Promise<void> {
  const migrationPath = path.join(__dirname, '..', 'migrations', '001_create_users.sql');
  if (fs.existsSync(migrationPath)) {
    const sql = fs.readFileSync(migrationPath, 'utf-8');
    const db = (await import('./config/database')).default;
    await db.query(sql);
    logger.info('Migrations completed successfully');
  } else {
    logger.warn('Migration file not found, skipping');
  }
}

/**
 * Application entry point.
 * Runs database migrations, then starts the HTTP server.
 * Only executes when the file is run directly (not when imported as a module).
 * Exits with code 1 on startup failure.
 */
if (require.main === module) {
  async function start(): Promise<void> {
    try {
      await runMigrations();
      app.listen(config.port, config.host, () => {
        logger.info(`Auth Service running on ${config.host}:${config.port}`);
      });
    } catch (err) {
      logger.error('Failed to start server', { error: (err as Error).message });
      process.exit(1);
    }
  }
  start();
}

export default app;
