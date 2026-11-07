# Build context: this folder. Image contract (base, COPY-only, runtime,
# endpoints): CLAUDE.md "Image contract". The base is pinned by its index
# digest (all platforms); the tag beside it names the line it comes from.
FROM nginx/nginx-unprivileged:1.30-alpine-slim@sha256:016193c18ef1ce19dc2229d3305f69af1b05e0bc0e8fe6ee724a58bd305f3855

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
