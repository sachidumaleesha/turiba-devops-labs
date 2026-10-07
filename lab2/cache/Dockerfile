FROM alpine:3.24
WORKDIR /app
COPY deps.txt .
COPY app.txt .
RUN echo "installing dependencies..." && sleep 15 && cp deps.txt installed.txt
CMD ["cat", "app.txt"]
