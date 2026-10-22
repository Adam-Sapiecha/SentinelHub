FROM nginx:stable-alpine@sha256:970364228b1e4f932abc22d321932816782cca8a20b85a77552a7cfe9acfb3b5
COPY index.html sample.html styles.css app.js workspace.css workspace.js /usr/share/nginx/html/
COPY examples /usr/share/nginx/html/examples/
COPY nginx.conf /etc/nginx/templates/default.conf.template
ENV PUBLIC_BASE_PATH=/ PUBLIC_URL=https://example.invalid NGINX_ENVSUBST_FILTER="^(PUBLIC_BASE_PATH|PUBLIC_URL)$"
