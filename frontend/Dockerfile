FROM oven/bun:1

WORKDIR /app

COPY package.json ./
RUN bun install

COPY index.html vite.config.ts tsconfig.json ./
COPY src ./src

EXPOSE 5173
CMD ["bun", "run", "dev", "--host", "0.0.0.0"]
