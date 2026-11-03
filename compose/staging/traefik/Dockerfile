FROM docker.io/traefik:v3.7.13
RUN mkdir -p /etc/traefik/acme /etc/traefik/plantillas \
  && touch /etc/traefik/acme/acme.json \
  && chmod 600 /etc/traefik/acme/acme.json
COPY ./compose/staging/traefik/traefik.yml /etc/traefik/plantillas/traefik.yml
COPY ./compose/staging/traefik/dynamic.yml /etc/traefik/plantillas/dynamic.yml
COPY ./compose/staging/traefik/start /start
RUN sed -i 's/\r$//g' /start && chmod +x /start
ENTRYPOINT ["/start"]
