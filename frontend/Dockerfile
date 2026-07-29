# Build stage — produces dist/, then is discarded.
FROM node:24-slim AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

# Serve stage. nginx on 5173, not 80: keeping the port identical means every CORS
# conclusion in the hosting spec still holds and the home-screen bookmark doesn't move.
FROM nginx:alpine

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 5173
