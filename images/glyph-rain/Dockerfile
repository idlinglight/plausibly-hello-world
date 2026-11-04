# Build context: this folder. Image contract (base, COPY-only, runtime,
# endpoints): CLAUDE.md "Image contract". The base is pinned by its index
# digest (all platforms); the tag beside it names the line it comes from.
FROM nginxinc/nginx-unprivileged:1.30-alpine-slim@sha256:5d8bb9437d74a600ec5dbf90c035451c724dc33eac8d3a71078f6f8612c345f6

COPY nginx.conf /etc/nginx/conf.d/default.conf

# The startup script (its header: what it reads and writes, and why it
# can't fail the start).
COPY --chmod=0755 entrypoint/40-phw-glyphs.sh /docker-entrypoint.d/

COPY site/ /usr/share/nginx/html/

# Served as /version.txt: the build's commit (build arg GIT_SHA).
ARG GIT_SHA=dev
COPY <<EOF /usr/share/nginx/html/version.txt
${GIT_SHA}
EOF
