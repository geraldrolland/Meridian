import crypto from 'crypto';
import { Router } from 'express';
import jwt from 'jsonwebtoken';
import { RawData, WebSocket, WebSocketServer } from 'ws';
import http from 'http';
import config from '../config';
import redis from '../config/redis';
import { invalidateVideoCache } from '../middleware/cache';
import { logger } from '../middleware/logger';
import { SessionData } from '../types';

const router = Router();

/**
 * Extracts the video id from a video-service status push
 * (`{"video_id": "...", "status": "...", "user_id": ...}` — no `type` field).
 * Returns null for ABR frames, non-JSON frames, and malformed data.
 */
function statusFrameVideoId(data: RawData): string | null {
  try {
    const text = Buffer.isBuffer(data)
      ? data.toString('utf8')
      : Array.isArray(data)
        ? Buffer.concat(data).toString('utf8')
        : null;
    if (!text) return null;
    const msg = JSON.parse(text);
    if (
      msg &&
      typeof msg === 'object' &&
      !('type' in msg) &&
      typeof msg.video_id === 'string' &&
      typeof msg.status === 'string'
    ) {
      return msg.video_id;
    }
    return null;
  } catch {
    return null;
  }
}

function signWsRequest(path: string): { signature: string; timestamp: string } {
  const timestamp = Date.now().toString();
  const payload = `GET:${path}:${timestamp}`;
  const signature = crypto
    .createHmac('sha256', config.proxySecret)
    .update(payload)
    .digest('hex');
  return { signature, timestamp };
}

function createWsProxy(server: http.Server): void {
  const wss = new WebSocketServer({ noServer: true });

  server.on('upgrade', (req, socket, head) => {
    const url = new URL(req.url || '/', `http://${req.headers.host}`);

    const videoMatch = url.pathname.match(/^\/ws\/video\/notification$/);

    if (!videoMatch) {
      socket.destroy();
      return;
    }

    const authHeader = req.headers.authorization;
    const headerToken = authHeader?.startsWith('Bearer ') ? authHeader.slice(7) : null;
    const token = headerToken || url.searchParams.get('token');
    const ip = req.socket?.remoteAddress || 'unknown';

    if (!token) {
      logger.warn('WS handshake rejected: missing token (ip=%s)', ip);
      wss.handleUpgrade(req, socket, head, (ws) => {
        ws.close(4001, 'Missing token');
      });
      return;
    }

    let decoded: { sessionId: string };
    try {
      decoded = jwt.verify(token, config.auth.jwtSecret) as { sessionId: string };
    } catch {
      logger.warn('WS handshake rejected: invalid token (ip=%s)', ip);
      wss.handleUpgrade(req, socket, head, (ws) => {
        ws.close(4001, 'Invalid token');
      });
      return;
    }

    if (!decoded.sessionId) {
      logger.warn('WS handshake rejected: invalid token payload (ip=%s)', ip);
      wss.handleUpgrade(req, socket, head, (ws) => {
        ws.close(4001, 'Invalid token payload');
      });
      return;
    }

    redis.get(`session:${decoded.sessionId}`)
      .then((sessionRaw) => {
        if (!sessionRaw) {
          logger.warn('WS handshake rejected: session expired (ip=%s)', ip);
          wss.handleUpgrade(req, socket, head, (ws) => {
            ws.close(4001, 'Session expired or not found');
          });
          return;
        }

        const session: SessionData = JSON.parse(sessionRaw);

        wss.handleUpgrade(req, socket, head, (clientWs) => {
          const signaturePath = '/ws/video/notification';
          const { signature, timestamp } = signWsRequest(signaturePath);
          const sessionCookie = `session=${encodeURIComponent(JSON.stringify(session))}`;

          const upstreamWs = new WebSocket(
            'ws://video-service:8000/api/video/ws/video/notification',
            {
              headers: {
                'x-proxy-signature': signature,
                'x-proxy-timestamp': timestamp,
                cookie: sessionCookie,
              },
            }
          );

          // The browser's `open` fires as soon as this handshake is accepted,
          // which is before the upstream dial has finished. `ws.send()` throws
          // while CONNECTING, so early frames are held rather than dropped —
          // otherwise the player's first segment_report never reaches the
          // video service and gets no recommendation.
          const pending: Array<[RawData, boolean]> = [];

          clientWs.on('message', (data, isBinary) => {
            if (upstreamWs.readyState === WebSocket.OPEN) {
              // ws re-guesses the frame type from the JS value (Buffer → binary),
              // so the original opcode must be carried across the proxy.
              upstreamWs.send(data, { binary: isBinary });
              return;
            }
            if (pending.length < 64) {
              pending.push([data, isBinary]);
            }
          });

          upstreamWs.on('open', () => {
            logger.info('WS proxy connected to video-service for user %s', session.userId);

            for (const [data, isBinary] of pending.splice(0)) {
              if (upstreamWs.readyState !== WebSocket.OPEN) break;
              upstreamWs.send(data, { binary: isBinary });
            }

            upstreamWs.on('message', async (data, isBinary) => {
              // Status pushes invalidate this video's cached GET responses
              // BEFORE the client sees the frame, so the refetch the frame
              // triggers can never race a stale entry.
              const videoId = statusFrameVideoId(data);
              if (videoId) {
                await invalidateVideoCache(videoId);
              }
              if (clientWs.readyState === WebSocket.OPEN) {
                clientWs.send(data, { binary: isBinary });
              }
            });

            clientWs.on('close', () => {
              upstreamWs.close();
              logger.info('WS proxy client disconnected for user %s', session.userId);
            });

            upstreamWs.on('close', () => {
              clientWs.close();
              logger.info('WS proxy upstream disconnected for user %s', session.userId);
            });

            clientWs.on('error', (err) => {
              logger.error('WS proxy client error for user %s: %s', session.userId, err.message);
              upstreamWs.close();
            });

            upstreamWs.on('error', (err) => {
              logger.error('WS proxy upstream error for user %s: %s', session.userId, err.message);
              clientWs.close();
            });
          });

          upstreamWs.on('error', (err) => {
            logger.error('WS proxy upstream connection error: %s', err.message);
            clientWs.close(1011, 'Backend unavailable');
          });
        });
      })
      .catch((err) => {
        logger.error('WS proxy Redis error: %s', err.message);
        socket.destroy();
      });
  });

  logger.info('WebSocket proxy initialized for /ws/video/notification');
}

export { createWsProxy };
export default router;
