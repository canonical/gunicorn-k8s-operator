FROM ubuntu:latest

ENV DEBIAN_FRONTEND noninteractive

RUN apt-get update \
&&  apt-get upgrade -y \
&&  apt-get install -y --no-install-recommends gunicorn python3-psycopg2 \
&&  apt-get clean \
&&  rm -rf /var/cache/apt/archives/* /var/lib/apt/lists/*

WORKDIR /srv/gunicorn/

COPY ./docker/run .
RUN chmod +x run

CMD /srv/gunicorn/run

ENV APP_WSGI app:app
ENV APP_NAME my-awesome-app

COPY ./docker/app .
