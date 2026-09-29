FROM alpine:3.20
RUN apk add --no-cache bash coreutils openssh-client autossh rsync
COPY mirror /usr/local/bin/mirror
RUN chmod +x /usr/local/bin/mirror
