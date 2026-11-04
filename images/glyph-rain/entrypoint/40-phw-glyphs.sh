#!/bin/sh
# glyph-rain: which glyph sets the page shows, decided once at container
# start. The base image's /docker-entrypoint.sh runs every executable *.sh
# in /docker-entrypoint.d/ before it starts nginx; this one runs as uid 101.
#
# Two documented switches, neither of them secret:
#   env   PHW_GLYPHS=music               → musical symbols
#   file  /etc/phw/glyphs, a regular     → runes (e.g. a secret mounted as
#         file of exactly the bytes        a file)
#         "runes", optionally + LF or CRLF
#   both                                 → both sets, mixed
#   neither                              → Egyptian hieroglyphs
#
# Output: /tmp/phw/glyphs.json, served as /glyphs.json (site/glyphs.json is
# a symlink to it: the root filesystem may be read-only, /tmp is writable).
# It holds fixed tokens only. A switch's value is never written or logged:
# the page and the log can only say whether a switch is unset, matches, or
# holds something else.
#
# Never fails or blocks the start (the entrypoint runs these under set -e,
# before nginx): no read of anything but a regular file, and on a failed
# write the old output is removed, so the page says the file didn't load.
# POSIX sh (busybox ash in the image): no eval, every expansion quoted.

ENV_VALUE=music
SECRET_FILE=/etc/phw/glyphs
SECRET_VALUE=runes
OUT_DIR=/tmp/phw

ME=$(basename "$0")
log() {
    if [ -z "${NGINX_ENTRYPOINT_QUIET_LOGS:-}" ]; then echo "$ME: $*"; fi
}

# env: unset | match | other
if [ -z "${PHW_GLYPHS:-}" ]; then
    env_state=unset
    log "PHW_GLYPHS: not set (or empty)"
elif [ "$PHW_GLYPHS" = "$ENV_VALUE" ]; then
    env_state=match
    log "PHW_GLYPHS: matches"
else
    env_state=other
    log "PHW_GLYPHS: set, but not to the value this image knows: ignored (the value isn't logged)"
fi

# Byte-exact: the value, the value + LF, or the value + CRLF. cmp stops at
# the first differing byte, so a long file isn't read through.
matches() {
    printf '%s' "$SECRET_VALUE" | cmp -s - "$SECRET_FILE" ||
        printf '%s\n' "$SECRET_VALUE" | cmp -s - "$SECRET_FILE" ||
        printf '%s\r\n' "$SECRET_VALUE" | cmp -s - "$SECRET_FILE"
}

# file: absent | match | other | unreadable | directory | notfile
# Tests follow symlinks (secret volumes link the file to a versioned folder).
dir=$(dirname "$SECRET_FILE")
if [ -d "$dir" ] && [ ! -x "$dir" ]; then
    file_state=unreadable
    log "$dir: present, but uid $(id -u) can't look inside"
elif [ -d "$SECRET_FILE" ]; then
    file_state=directory
    log "$SECRET_FILE: is a directory: mount the volume at $dir, the folder that holds the file"
elif [ ! -e "$SECRET_FILE" ] && [ ! -L "$SECRET_FILE" ]; then
    file_state=absent
    log "$SECRET_FILE: not present"
elif [ ! -f "$SECRET_FILE" ]; then
    file_state=notfile
    log "$SECRET_FILE: not a regular file (or a link to nothing): ignored"
elif [ ! -r "$SECRET_FILE" ]; then
    file_state=unreadable
    log "$SECRET_FILE: present, but not readable by uid $(id -u)"
elif matches; then
    file_state=match
    log "$SECRET_FILE: matches"
else
    file_state=other
    log "$SECRET_FILE: present, but not the value this image knows: ignored (the content isn't logged)"
fi

glyphs=
if [ "$env_state" = match ]; then glyphs='"music"'; fi
if [ "$file_state" = match ]; then glyphs="${glyphs:+$glyphs,}\"runes\""; fi
if [ -z "$glyphs" ]; then glyphs='"hieroglyphs"'; fi

# Written beside, then moved into place: the page never reads half a file,
# and a failed write can't leave the previous start's file being served.
out="$OUT_DIR/glyphs.json"
if mkdir -p "$OUT_DIR" 2>/dev/null &&
    printf '{"glyphs":[%s],"env":"%s","file":"%s"}\n' "$glyphs" "$env_state" "$file_state" \
        >"$out.tmp" 2>/dev/null &&
    mv -f "$out.tmp" "$out" 2>/dev/null; then
    log "glyphs: $(echo "$glyphs" | tr -d '"' | sed 's/,/, /')"
else
    rm -f "$out" "$out.tmp" 2>/dev/null
    echo "$ME: can't write $out: the page shows the default" >&2
fi
exit 0
