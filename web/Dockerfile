# The web app is built to static files and served by the same Nginx that fronts the API.
# The Nginx configuration itself stays mounted from deploy/nginx, as before.

FROM node:24-alpine AS build
WORKDIR /web
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
ARG NEXT_PUBLIC_DEMO=true
ENV NEXT_TELEMETRY_DISABLED=1 NEXT_PUBLIC_DEMO=$NEXT_PUBLIC_DEMO
RUN npm run build

FROM nginx:1.30-alpine
COPY --from=build /web/out /usr/share/nginx/html
