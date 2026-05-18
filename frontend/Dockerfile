FROM node:20-slim

WORKDIR /app

COPY package.json .
RUN npm install --legacy-peer-deps

COPY . .

# 도커 환경에서는 docker-compose environment로 VITE_API_TARGET 주입
# vite.config.ts가 process.env.VITE_API_TARGET을 읽음

CMD ["./node_modules/.bin/vite", "--host", "0.0.0.0", "--port", "3000"]
