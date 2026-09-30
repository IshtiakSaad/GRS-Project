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

# Scalar, the API reference at /api/docs/: one self-contained script from the npm release,
# pinned by checksum (a changed release file fails the build) and served from this origin.
ADD --checksum=sha256:b86884e6251eed57234f1a62732a5e6303700a5b4d159192a5a5dd003b854378 \
    https://registry.npmjs.org/@scalar/api-reference/-/api-reference-1.72.1.tgz /tmp/scalar.tgz
RUN mkdir -p out/vendor/scalar \
    && tar -xzf /tmp/scalar.tgz -C /tmp package/dist/browser/standalone.js \
    && mv /tmp/package/dist/browser/standalone.js out/vendor/scalar/standalone.js

# Compressed copies next to the originals, made once here: Nginx sends them to any browser
# that accepts gzip (gzip_static) and spends no CPU per request. On 2G this is most of the
# difference: the Scalar script is 4.3 MB as it is and 1.3 MB compressed.
RUN find out -type f \( -name '*.html' -o -name '*.js' -o -name '*.css' -o -name '*.svg' \
      -o -name '*.txt' -o -name '*.json' \) -exec gzip -9 -k {} +

FROM nginx:1.30-alpine
COPY --from=build /web/out /usr/share/nginx/html
# The access log the monitor reads, on a volume shared with it; kept small by this script.
RUN mkdir -p /var/log/grs
COPY --chmod=755 rotate-edge-log.sh /docker-entrypoint.d/40-rotate-edge-log.sh
