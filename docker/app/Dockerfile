FROM ubuntu:latest

ENV DEBIAN_FRONTEND noninteractive

RUN apt-get update \
&&  apt-get install -y --no-install-recommends gunicorn python3-psycopg2 \
&&  apt-get clean \
&&  rm -rf /var/cache/apt/archives/* /var/lib/apt/lists/*

ENV APP_WSGI app:app
ENV APP_NAME my-awesome-app

WORKDIR /srv/gunicorn/
COPY app .
COPY run .
RUN chmod +x run

EXPOSE 80

CMD /srv/gunicorn/run
