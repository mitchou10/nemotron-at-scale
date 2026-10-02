# syntax=docker/dockerfile:1.7

# ---- Runtime stage ----
# Unprivileged nginx (uid 101, port 8080): runs with a read-only root filesystem and no capabilities.
FROM nginxinc/nginx-unprivileged:1.27-alpine AS runtime

# Where /api/ is proxied to (compose service name by default; the chart overrides it), and the entrypoint
# switch that exports NGINX_LOCAL_RESOLVERS (the container DNS servers) used by the nginx config.
ENV BACKEND_URL=http://backend:8000 \
    NGINX_ENTRYPOINT_LOCAL_RESOLVERS=1

# The entrypoint renders every file of /etc/nginx/templates into /etc/nginx/conf.d
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY index.html style.css app.js /usr/share/nginx/html/

# Explicit for scanners: the base image already runs as this user
USER 101

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1:8080/healthz || exit 1
