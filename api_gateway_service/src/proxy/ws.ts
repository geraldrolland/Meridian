import crypto from 'crypto';
import { Router } from 'express';
import jwt from 'jsonwebtoken';
import { WebSocket, WebSocketServer } from 'ws';
import http from 'http';
import config from '../config';
import redis from '../config/redis';
import { logger } from '../middleware/logger';
import { SessionData } from '../types';

const router = Router();

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
    const token = authHeader?.startsWith('Bearer ') ? authHeader.slice(7) : null;

    if (!token) {
      wss.handleUpgrade(req, socket, head, (ws) => {
        ws.close(4001, 'Missing token');
      });
      return;
    }

    let decoded: { sessionId: string };
    try {
      decoded = jwt.verify(token, config.auth.jwtSecret) as { sessionId: string };
    } catch {
      wss.handleUpgrade(req, socket, head, (ws) => {
        ws.close(4001, 'Invalid token');
      });
      return;
    }

    if (!decoded.sessionId) {
      wss.handleUpgrade(req, socket, head, (ws) => {
        ws.close(4001, 'Invalid token payload');
      });
      return;
    }

    redis.get(`session:${decoded.sessionId}`)
      .then((sessionRaw) => {
        if (!sessionRaw) {
          wss.handleUpgrade(req, socket, head, (ws) => {
            ws.close(4001, 'Session expired or not found');
          });
          return;
        }

        const session: SessionData = JSON.parse(sessionRaw);

        wss.handleUpgrade(req, socket, head, (clientWs) => {
          const targetPath = '/ws/video/notification';
          const { signature, timestamp } = signWsRequest(targetPath);

          const upstreamWs = new WebSocket(
            `ws://video-service:8000${targetPath}`,
            {
              headers: {
                'x-proxy-signature': signature,
                'x-proxy-timestamp': timestamp,
              },
            }
          );

          upstreamWs.on('open', () => {
            logger.info('WS proxy connected to video-service for user %s', session.userId);

            clientWs.on('message', (data) => {
              if (upstreamWs.readyState === WebSocket.OPEN) {
                upstreamWs.send(data);
              }
            });

            upstreamWs.on('message', (data) => {
              if (clientWs.readyState === WebSocket.OPEN) {
                clientWs.send(data);
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
