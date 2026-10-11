# Intentionally uses Vite development; not a production build.
FROM node:22-alpine
WORKDIR /app

COPY frontend/package.json ./
RUN npm install --no-audit --no-fund

COPY frontend ./
RUN chown -R node:node /app
USER node
