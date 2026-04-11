FROM node:20-slim

WORKDIR /app

# Install deps first — this layer caches unless package*.json changes
COPY package.json package-lock.json* ./
RUN npm install

# Copy source — overridden by the volume mount in dev, used as-is in prod
COPY . .

EXPOSE 5173

# --host 0.0.0.0 is required so the port is accessible outside the container.
# Vite picks up changes from the mounted volume and hot-reloads automatically.
CMD ["npm", "run", "dev"]
