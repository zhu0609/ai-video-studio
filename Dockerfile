FROM node:22-bookworm-slim AS frontend
WORKDIR /frontend
RUN npm install -g pnpm@11.25.0
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml frontend/.npmrc ./
RUN pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm build

FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg fonts-wqy-zenhei && rm -rf /var/lib/apt/lists/*
WORKDIR /studio
COPY backend/requirements.lock ./requirements.lock
RUN pip install --no-cache-dir -r requirements.lock
COPY backend/ ./backend/
COPY workflows/ ./workflows/
COPY --from=frontend /frontend/dist ./frontend/dist
RUN mkdir -p /studio/data/media
ENV PYTHONPATH=/studio/backend PYTHONUNBUFFERED=1
CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8000"]
