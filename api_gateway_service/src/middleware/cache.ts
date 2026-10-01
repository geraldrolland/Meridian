import { Response, NextFunction } from 'express';
import config from '../config';
import redis from '../config/redis';
import { AuthenticatedRequest } from '../types';
import { logger } from './logger';

/** Redis key layout: `cache:resp:{userId}:{originalUrl}`. */
const CACHE_KEY_PREFIX = 'cache:resp';

interface StoredResponse {
  status: number;
  contentType: string;
  body: string;
}

/**
 * True when a Content-Type header denotes a JSON payload:
 * `application/json` (optionally with parameters like `; charset=utf-8`)
 * or any `+json` structured suffix (e.g. `application/problem+json`).
 */
export function isJsonContentType(contentType: string | undefined | null): boolean {
  if (!contentType) return false;
  const base = contentType.split(';')[0].trim().toLowerCase();
  return base === 'application/json' || base.endsWith('+json');
}

/** True when the request path falls under any configured cache route prefix. */
function isCacheablePath(path: string): boolean {
  return config.cache.routes.some((route) => path.startsWith(route));
}

/** Builds the Redis key for a cached GET: route + user, per-user isolated. */
export function buildCacheKey(originalUrl: string, userId: string): string {
  return `${CACHE_KEY_PREFIX}:${userId}:${originalUrl}`;
}

async function invalidateByPattern(pattern: string, description: string): Promise<void> {
  // SCAN (never KEYS) because keys embed arbitrary paths + query strings.
  // Fail-open: a Redis error is logged and swallowed.
  try {
    let cursor = '0';
    do {
      const [next, keys] = await redis.scan(cursor, 'MATCH', pattern, 'COUNT', 100);
      cursor = next;
      if (keys.length > 0) {
        await redis.del(...keys);
        logger.info('Invalidated %d cached responses (%s)', keys.length, description);
      }
    } while (cursor !== '0');
  } catch (err) {
    logger.warn(
      'Cache invalidation failed (%s): %s',
      description,
      err instanceof Error ? err.message : String(err)
    );
  }
}

/**
 * Deletes every cached response for one video across all users.
 * Invoked by the WebSocket proxy when a video status frame is forwarded,
 * so realtime-triggered refetches never read a stale entry.
 */
export async function invalidateVideoCache(videoId: string): Promise<void> {
  await invalidateByPattern(`${CACHE_KEY_PREFIX}:*:/api/video/${videoId}*`, `video ${videoId}`);
}

/**
 * Deletes every cached response under the video routes (all users) —
 * used when a video is DELETED, so detail and list entries vanish together.
 */
export async function invalidateAllVideoCache(): Promise<void> {
  await invalidateByPattern(`${CACHE_KEY_PREFIX}:*:/api/video*`, 'all video routes');
}

function pushChunk(chunks: Buffer[], chunk: unknown): void {
  if (Buffer.isBuffer(chunk)) chunks.push(chunk);
  else if (typeof chunk === 'string') chunks.push(Buffer.from(chunk));
  else if (chunk instanceof Uint8Array) chunks.push(Buffer.from(chunk));
}

/**
 * Wraps the response so the proxied body is captured and, on completion,
 * stored in Redis when it is a 200 with a JSON content type.
 *
 * The store happens BEFORE the response is handed back to the client
 * (per spec: key → store → return), and it fails open: a Redis error is
 * logged and the response is still delivered.
 */
function installCapture(res: Response, key: string): void {
  const chunks: Buffer[] = [];
  let capturedContentType: string | undefined;

  const originalWriteHead = res.writeHead.bind(res) as (
    status: number,
    headers?: Record<string, unknown> | string[],
    ...rest: unknown[]
  ) => unknown;
  const originalWrite = res.write.bind(res) as (
    chunk: unknown,
    ...rest: unknown[]
  ) => unknown;
  const originalEnd = res.end.bind(res) as (
    chunk?: unknown,
    ...rest: unknown[]
  ) => unknown;

  res.writeHead = ((status: number, headers?: Record<string, unknown> | string[], ...rest: unknown[]) => {
    let source: Record<string, unknown> | null = null;
    if (headers && typeof headers === 'object' && !Array.isArray(headers)) {
      source = headers;
    } else if (typeof headers === 'string' && rest[0] && typeof rest[0] === 'object') {
      source = rest[0] as Record<string, unknown>;
    } else if (Array.isArray(headers)) {
      for (let i = 0; i < headers.length - 1; i += 2) {
        if (String(headers[i]).toLowerCase() === 'content-type') {
          capturedContentType = String(headers[i + 1]);
        }
      }
    }
    if (source) {
      const ct = source['content-type'] ?? source['Content-Type'];
      if (typeof ct === 'string') capturedContentType = ct;
    }
    return originalWriteHead(status, headers, ...rest);
  }) as typeof res.writeHead;

  res.write = ((chunk: unknown, ...rest: unknown[]) => {
    pushChunk(chunks, chunk);
    return originalWrite(chunk, ...rest);
  }) as typeof res.write;

  res.end = ((chunk?: unknown, ...rest: unknown[]) => {
    if (typeof chunk !== 'function') pushChunk(chunks, chunk);

    const status = res.statusCode;
    let contentType: string | undefined = capturedContentType;
    if (!contentType) {
      const header = res.getHeader('content-type');
      if (typeof header === 'string') contentType = header;
      else if (Array.isArray(header)) contentType = header[0];
    }

    const finish = () => {
      try {
        originalEnd(chunk, ...rest);
      } catch (err) {
        logger.warn('Failed to flush cached response: %s', err instanceof Error ? err.message : String(err));
      }
    };

    if (status !== 200 || !isJsonContentType(contentType)) {
      return finish();
    }

    const envelope: StoredResponse = {
      status,
      contentType: contentType as string,
      body: Buffer.concat(chunks).toString('utf8'),
    };

    // Store first, then return the response. Fail-open on Redis errors.
    try {
      void redis
        .set(key, JSON.stringify(envelope), 'EX', config.cache.ttlSeconds)
        .catch((err: Error) => {
          logger.warn('Cache store failed for %s: %s', key, err.message);
        })
        .then(() => finish());
    } catch (err) {
      logger.warn(
        'Cache store failed for %s: %s',
        key,
        err instanceof Error ? err.message : String(err)
      );
      finish();
    }
  }) as typeof res.end;
}

/**
 * Redis-backed response cache for GET requests under `CACHE_ROUTES`.
 *
 * Request phase:
 *  1. DELETE under CACHE_ROUTES → flush every cached video response first
 *     (a deleted video's GET/list entries must not outlive it), pass through
 *  2. Non-GET or non-matching path → pass through untouched
 *  3. No authenticated user → pass through (key must be per-user)
 *  4. Cache hit → replay stored status + content type + body, no upstream call
 *  5. Cache miss (or Redis/parse error) → install the capture, continue
 *
 * Response phase (capture): store the body as `{status, contentType, body}`
 * under `cache:resp:{userId}:{originalUrl}` with TTL `CACHE_TTL` seconds —
 * only when the final status is 200 AND the response content type is JSON.
 */
export async function cacheMiddleware(
  req: AuthenticatedRequest,
  res: Response,
  next: NextFunction
): Promise<void> {
  if (req.method === 'DELETE' && isCacheablePath(req.path)) {
    await invalidateAllVideoCache();
  }

  if (req.method !== 'GET' || !isCacheablePath(req.path)) {
    next();
    return;
  }

  const userId = req.user?.userId;
  if (!userId) {
    next();
    return;
  }

  const key = buildCacheKey(req.originalUrl, userId);

  try {
    const cached = await redis.get(key);
    if (cached) {
      try {
        const stored = JSON.parse(cached) as StoredResponse;
        res.status(stored.status);
        res.setHeader('Content-Type', stored.contentType);
        res.send(Buffer.from(stored.body, 'utf8'));
        return;
      } catch (err) {
        logger.warn(
          'Malformed cache entry for %s, refetching: %s',
          key,
          err instanceof Error ? err.message : String(err)
        );
      }
    }
  } catch (err) {
    logger.warn(
      'Cache read failed for %s: %s',
      key,
      err instanceof Error ? err.message : String(err)
    );
  }

  installCapture(res, key);
  next();
}
