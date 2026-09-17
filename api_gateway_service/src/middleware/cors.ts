import cors from 'cors';
import config from '../config';

/**
 * CORS middleware configured from environment variables.
 * Supports wildcard (`*`), single origin, or comma-separated list of origins.
 * Credentials and allowed methods/headers are configurable via env vars.
 */
const corsMiddleware = cors({
  origin: config.cors.origin,
  methods: config.cors.methods,
  allowedHeaders: config.cors.allowedHeaders,
  credentials: config.cors.credentials,
});

export default corsMiddleware;
