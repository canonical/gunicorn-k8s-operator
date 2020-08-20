FROM ubuntu:latest

ENV DEBIAN_FRONTEND noninteractive

RUN apt-get update \
&&  apt-get upgrade -y \
&&  apt-get install -y --no-install-recommends gunicorn \
&&  apt-get clean \
&&  rm -rf /var/cache/apt/archives/* /var/lib/apt/lists/*

WORKDIR /srv/gunicorn/

COPY run .
RUN chmod +x run

EXPOSE 80

CMD /srv/gunicorn/run
