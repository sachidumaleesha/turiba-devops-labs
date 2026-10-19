# The web front: nginx serves the page and forwards /api/ to the API (slide 35).
FROM nginx:1.30-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY public/ /usr/share/nginx/html/
