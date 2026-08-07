# Dockerfile for the dev frontend (web/next/).
# `npm run dev` is the Next.js dev server with hot reload.
FROM node:20-alpine

ENV TZ=Europe/Moscow
ENV NEXT_TELEMETRY_DISABLED=1

WORKDIR /app

# Install deps with cache-friendly layer
COPY package.json package-lock.json* ./
RUN npm install

# Code is mounted at runtime via volumes; COPY is just for build sanity.
COPY . .

EXPOSE 3000

# Host 0.0.0.0 so the port is reachable from outside the container.
CMD ["npm", "run", "dev", "--", "-H", "0.0.0.0"]
