FROM gunicorn-base:latest

RUN apt-get update \
&&  apt-get install -y --no-install-recommends python3-psycopg2 \
&&  apt-get clean \
&&  rm -rf /var/cache/apt/archives/* /var/lib/apt/lists/*

ENV APP_WSGI app:app
ENV APP_NAME my-awesome-app

WORKDIR /srv/gunicorn/
COPY app .
