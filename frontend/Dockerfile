# ponytail: dev server in the container — M0 has no prod hosting story yet.
# Swap for a build + static serve stage when there's somewhere to deploy.
FROM node:24-slim

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host"]
