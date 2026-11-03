# Ambiente de staging

Guía para levantar staging desde cero, escrita para quien nunca ha hecho un
despliegue. Sigue las secciones en orden.

Staging corre en internet todo lo que funciona en local: portal y backoffice,
pagos con Klap y Flow en modo sandbox, firma avanzada con el PSC de pruebas,
Mailpit para leer los correos, y los datos de demostración.

> **Solo datos ficticios.** El servidor está en internet y los repositorios son
> públicos. Nunca escribas en staging, ni en este repositorio, datos reales de
> nadie: tampoco tus propios datos.
>
> **Las firmas de staging no tienen validez legal.** El PSC de pruebas es un
> prestador ficticio (Ley 19.799). Corre en local y en staging, nunca en
> producción: `docker-compose.production.yml` no lo incluye, la configuración de
> producción rechaza su dirección, y el servicio se niega a iniciar con
> configuración de producción.

En esta guía, `<ip-con-guiones>` es la IP del servidor con guiones en vez de
puntos. Si la IP fuera `20.1.2.3`, sería `20-1-2-3`.

| Qué | Dónde |
|---|---|
| Portal y backoffice | `https://<ip-con-guiones>.sslip.io` |
| Páginas de firma y PKI del PSC | `https://firma.<ip-con-guiones>.sslip.io` |
| Correos (Mailpit) | `https://correo.<ip-con-guiones>.sslip.io` |

Los tres piden el mismo usuario y contraseña: el usuario `equipo` y la clave que
elijas en la sección 3.

## 1. Preparar la VM

Parte de una VM de Compute Engine con Ubuntu 24.04 (`e2-medium`, 4 GB de RAM,
30 GB de disco), IP externa estática y acceso SSH por clave.

**Firewall.** En la consola de Google Cloud, edita la instancia y marca
«Permitir tráfico HTTP» y «Permitir tráfico HTTPS» (etiquetas `http-server` y
`https-server`). Solo deben quedar abiertos los puertos 22, 80 y 443.

Conéctate con tu usuario administrador:

```bash
ssh -i ~/.ssh/crm_staging crm-staging@<ip>
```

**Solo claves SSH.** Esto debe responder `passwordauthentication no`:

```bash
sudo sshd -T | grep -i passwordauthentication
```

**Swap de 2 GB.** Compilar las imágenes usa más memoria de la que hay libre:

```bash
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

**Hora de Chile.** El respaldo corre a las 03:00 de la hora del servidor, y el
`cron` de Ubuntu no admite otra zona horaria por tarea:

```bash
sudo timedatectl set-timezone America/Santiago
```

**Docker Engine y el plugin de Compose**, desde el repositorio oficial de Docker:

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl git
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu noble stable" | sudo tee /etc/apt/sources.list.d/docker.list
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

**Usuario de despliegue.** `deploy` no tiene `sudo`. Solo él usa la clave
restringida. Tu usuario `crm-staging` sigue siendo el administrador, y también
entra al grupo `docker` para copiar la base de datos:

```bash
sudo adduser --disabled-password --gecos "" deploy
sudo usermod -aG docker deploy
sudo usermod -aG docker crm-staging
sudo install -d -o deploy -g docker -m 2775 /srv/crm-easyoffice
```

Cierra la sesión SSH y vuelve a entrar para que el grupo `docker` tenga efecto.

**Clave de despliegue restringida.** Genérala **en tu computador**, sin
contraseña y solo para esto:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/crm_staging_deploy -N "" -C "github-actions-staging"
```

En la VM, agrega la clave **pública** (`~/.ssh/crm_staging_deploy.pub`) con
`restrict` y `command=`. Así esa clave ejecuta el script de despliegue y nada más,
aunque alguien la robe:

```bash
sudo install -d -o deploy -g deploy -m 700 /home/deploy/.ssh
echo 'restrict,command="/srv/crm-easyoffice/crm-easyoffice-backend/scripts/staging/deploy.sh" <contenido de crm_staging_deploy.pub>' | sudo tee -a /home/deploy/.ssh/authorized_keys
sudo chown deploy:deploy /home/deploy/.ssh/authorized_keys
sudo chmod 600 /home/deploy/.ssh/authorized_keys
```

Escribe el `echo` con la clave completa, en una sola línea.

**Respaldo diario.** La carpeta y el cron se dejan listos ahora. El respaldo no
corre hasta la madrugada:

```bash
sudo install -d -o deploy -g docker -m 2775 /srv/crm-easyoffice/backups
sudo touch /var/log/crm-staging-backup.log
sudo chown deploy:docker /var/log/crm-staging-backup.log
echo '0 3 * * * /srv/crm-easyoffice/crm-easyoffice-backend/scripts/staging/backup.sh >> /var/log/crm-staging-backup.log 2>&1' | sudo crontab -u deploy -
```

## 2. Clonar los dos repositorios

Van uno al lado del otro, con estos nombres exactos. Son públicos, así que la VM
no necesita credenciales de GitHub:

```bash
sudo -u deploy git clone https://github.com/Nicozapata1811/crm-easyoffice-backend.git /srv/crm-easyoffice/crm-easyoffice-backend
sudo -u deploy git clone https://github.com/Nicozapata1811/crm-easyoffice-frontend.git /srv/crm-easyoffice/crm-easyoffice-frontend
```

## 3. Llenar `.envs/.staging/`

Copia las plantillas. Esta carpeta está en `.gitignore`: **nunca** se commitea.

```bash
cd /srv/crm-easyoffice/crm-easyoffice-backend
sudo -u deploy cp -r .envs.example/.staging .envs/.staging
sudo chmod 750 .envs/.staging
sudo chown -R deploy:docker .envs/.staging
sudo chmod 640 .envs/.staging/.[a-z]*
```

Edita cada archivo con `sudo -u deploy nano .envs/.staging/.django` (y lo mismo
para los demás). Reemplaza `<ip-con-guiones>` y cada `CHANGEME`.

Para cada secreto, genera un valor distinto con:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

| Archivo | Variable | Qué poner |
|---|---|---|
| `.django` | `DJANGO_SECRET_KEY` | Un secreto generado |
| `.django` | `KLAP_API_KEY` | La clave de pruebas de <https://developers.klap.cl/datos-de-prueba> |
| `.django` | `FLOW_API_KEY`, `FLOW_SECRET_KEY` | Crea una cuenta en <https://sandbox.flow.cl> y cópialas desde «Mis datos» |
| `.django` | `STAGING_DEMO_*_PASSWORD` | Una clave por usuario de demostración, de al menos 8 caracteres y no común |
| `.postgres` | `POSTGRES_PASSWORD` | Un secreto generado |
| `.firma` | `SIGNATURE_API_KEY`, `SIGNATURE_WEBHOOK_SECRET` | Un secreto generado para cada una |
| `.firma` | `FIRMA_SANDBOX_SECRET_KEY`, `FIRMA_SANDBOX_KEY_PASSPHRASE` | Un secreto generado para cada una |
| `.traefik` | `STAGING_ACME_EMAIL` | Un correo que el equipo lea. Let's Encrypt rechaza `example.com` |
| `.basic-auth` | | El hash de la contraseña del equipo (abajo) |

Usa solo credenciales de sandbox de Klap y Flow. No agregues
`SIGNATURE_PROVIDER` ni `SIGNATURE_API_BASE_URL` a `.firma`: con esos nombres, la
configuración rechaza el PSC y Django no inicia.

**La contraseña del equipo.** Elige una, compártela con el equipo por un canal
privado y guarda su hash, reemplazando `LA-CLAVE`:

```bash
docker run --rm httpd:2.4-alpine htpasswd -nbB equipo 'LA-CLAVE' | sudo -u deploy tee .envs/.staging/.basic-auth
```

Debe quedar una sola línea, que parte con `equipo:$2y$`.

## 4. Primer inicio

La primera vez, `deploy.sh` compila todo. En esta VM tarda varios minutos:

```bash
sudo -u deploy /srv/crm-easyoffice/crm-easyoffice-backend/scripts/staging/deploy.sh
```

Termina con `==> Deployed …`. Si falla, revisa los registros:

```bash
docker compose -f docker-compose.staging.yml logs --tail=100 django traefik
```

**Tu usuario para el admin de Django:**

```bash
docker compose -f docker-compose.staging.yml run --rm django python manage.py createsuperuser
```

**Datos de demostración.**

> **Advertencia.** `--force` se salta la protección que evita cargar datos de
> demostración con `DEBUG` apagado. Úsalo solo en staging, nunca en producción.

```bash
docker compose -f docker-compose.staging.yml run --rm django python manage.py seed_demo_usuarios --force
docker compose -f docker-compose.staging.yml run --rm django python manage.py seed_demo_clientes --force
docker compose -f docker-compose.staging.yml run --rm django python manage.py seed_demo_firma_avanzada --force
```

`seed_demo_firma_avanzada` también carga las sucursales y bodegas de ejemplo, y
deja los tipos de trámite con firma avanzada. Para volver a la firma asistida:
`seed_demo_firma_avanzada --force --asistida`.

| Usuario | Correo | Contraseña |
|---|---|---|
| Administrador | `admin@example.test` | `STAGING_DEMO_ADMIN_PASSWORD` |
| Ejecutivo | `ejecutivo@example.test` | `STAGING_DEMO_EJECUTIVO_PASSWORD` |
| Cliente 1 (empresa) | `cliente1@example.test` | `STAGING_DEMO_CLIENTE1_PASSWORD` |
| Cliente 2 (empresa) | `cliente2@example.test` | `STAGING_DEMO_CLIENTE2_PASSWORD` |

## 5. Comprobar que funciona

**HTTPS y contraseña.** Abre las tres direcciones del inicio en una ventana de
incógnito. Cada una debe:

- mostrar el candado (certificado de Let's Encrypt);
- pedir usuario y contraseña;
- abrir la aplicación, las páginas del PSC o Mailpit al darlos. En
  `https://firma.<ip-con-guiones>.sslip.io/` es normal una página 404: el PSC
  solo sirve enlaces de firma y su PKI.

Desde tu computador, sin contraseña, debe responder `401` y traer
`x-robots-tag: noindex, nofollow`:

```bash
curl -sI https://<ip-con-guiones>.sslip.io/ | grep -iE '^HTTP|x-robots-tag'
```

Si no hay certificado, revisa
`docker compose -f docker-compose.staging.yml logs traefik | grep -i acme`, y
la sección [Si Let's Encrypt rechaza el certificado](#si-lets-encrypt-rechaza-el-certificado).

**Ingreso.**

- Portal: `/ingresar` con `cliente1@example.test`.
- Backoffice: `/backoffice/ingresar` con `admin@example.test`.

**Un domicilio pagado con Klap.** Como `cliente1@example.test`:

1. Pide un domicilio tributario. Como representante, usa un RUT de demostración
   que el PSC conozca, por ejemplo `90000302-1`.
2. Revisa el borrador y confírmalo.
3. Elige «Pagar con Klap» y paga con una tarjeta de
   <https://developers.klap.cl/datos-de-prueba>.
4. La venta debe quedar pagada y el trámite debe pasar a firma. Comprueba que
   llegaron los avisos de Klap:

```bash
docker compose -f docker-compose.staging.yml logs traefik | grep '/api/pagos/webhooks/klap/'
```

Debes ver `validacion/` y `confirmacion/` con respuesta `200`.

**Un domicilio pagado con Flow.** Como `cliente2@example.test`, repite lo mismo con
otro RUT, por ejemplo `90000303-K`, eligiendo «Pagar con Flow» y una tarjeta de
pruebas de Flow:

```bash
docker compose -f docker-compose.staging.yml logs traefik | grep '/api/pagos/webhooks/flow/'
```

Debes ver `confirmacion/` con respuesta `200`, y el navegador debe volver al
resultado del pago por `/api/pagos/retorno/<id>/`.

Estas son las únicas rutas sin contraseña. Cada una conserva su propia
verificación:

| Ruta | Método | Cómo se verifica |
|---|---|---|
| `/api/pagos/webhooks/klap/validacion/` | POST | Se responde solo con nuestros datos: Klap la firma con un `order_id` que aún no envía |
| `/api/pagos/webhooks/klap/confirmacion/` | POST | Encabezado `Apikey` |
| `/api/pagos/webhooks/klap/rechazo/` | POST | Encabezado `Apikey` |
| `/api/pagos/webhooks/flow/confirmacion/` | POST | El token se confirma preguntándole a Flow (`payment/getStatus`) |
| `/api/pagos/retorno/<id>/` | GET, POST | No cambia nada: pide revisar el estado y redirige al portal |

**Un caso firmado con el PSC.** Sigue con uno de los trámites pagados:

1. Abre Mailpit (`https://correo.<ip-con-guiones>.sslip.io`). Llega un correo con
   el enlace del primer firmante.
2. Abre el enlace e identifícate con el RUT y el número de serie del firmante. El
   número de serie de cada persona de demostración es `A` seguida del número del
   RUT. Por ejemplo, `A90000302` para `90000302-1`.
3. Copia el código de 6 dígitos que llega a Mailpit, consiente y firma.
4. Repite con cada firmante, en orden. Las personas de demostración están en
   `firma_sandbox/README.md`.
5. Al firmar el último, el trámite queda completado, el contrato vigente y el
   PDF firmado disponible.

Si un aviso del PSC se pierde, la tarea `sincronizar_solicitudes_abiertas` lo
recupera en un máximo de 15 minutos.

**Validar el PDF contra la raíz de pruebas.** Descarga el PDF firmado desde el
backoffice, súbelo a la VM como `/tmp/firmado.pdf` y pide la validación a la API
del PSC, que solo responde dentro de la red de Compose:

```bash
docker compose -f docker-compose.staging.yml cp /tmp/firmado.pdf django:/tmp/firmado.pdf
docker compose -f docker-compose.staging.yml exec django python -c "import os, httpx; print(httpx.post('http://firma-sandbox:8100/api/v1/validaciones', headers={'Authorization': 'Bearer ' + os.environ['SIGNATURE_API_KEY']}, files={'documento': open('/tmp/firmado.pdf', 'rb')}, timeout=60).text)"
```

La respuesta debe traer `"valido": true` y `"documento_sin_cambios": true`, y por
cada firma, `"confiable": true`.

## 6. Copiar la base de datos local

Es una **copia a pedido**, no una réplica. Los datos locales son ficticios, pero
los escribimos nosotros y pueden traer nuestros nombres, correos o RUT, así que la
copia se anonimiza **antes de salir de tu computador**. Nunca es parte del
despliegue automático.

**Reemplaza todo lo que hay en staging**, salvo los datos del PSC.

Desde tu computador, en el repositorio backend, en `main` actualizado y con el
Postgres local corriendo:

```bash
scripts/staging/copy_local_db.sh crm-staging@<ip>
```

Usa la clave `~/.ssh/crm_staging`; otra se indica con `STAGING_SSH_KEY_FILE`. El
script:

1. copia el Postgres local a un Postgres **desechable**, nunca toca el local;
2. corre `anonimizar_datos --es-copia`, que reemplaza nombres, correos, teléfonos,
   direcciones y RUT, incluidos los datos congelados de cada documento. Las
   contraseñas quedan inutilizables, las cédulas pasan a una imagen de relleno, y
   cada Word y PDF a un archivo que dice «Documento no disponible en la copia de
   staging», con su SHA-256 actualizado;
3. borra las tablas que ningún modelo conoce, por ejemplo las que dejó otra rama, y
   avisa cuáles. Luego busca los valores originales en **todas** las tablas. Si
   queda alguno, se detiene y nada sale de tu computador. Esa búsqueda omite el
   registro de auditoría, que guarda los valores anteriores: sus filas no salen
   de tu computador, porque el respaldo que se sube las excluye, y staging parte
   sin historial;
4. sube la copia, respalda staging, restaura, migra y crea los usuarios de
   demostración;
5. registra a las personas generadas en el PSC de staging.

**Cómo saber que funcionó.**

- El script termina con `Done. Staging holds the anonymized copy.`, y antes
  muestra `original values searched: none left`.
- En el backoffice ves los trámites de tu base local, con clientes como
  `Empresa Anonima 0012 SpA` y RUT desde `91.000.000`.
- Un documento antiguo muestra «Documento no disponible en la copia de staging».
  Un caso nuevo genera un documento real.
- Tus contraseñas locales ya no sirven: entra con los usuarios de la sección 4 y
  vuelve a crear tu superusuario.

Las personas generadas pueden firmar en el PSC: su número de serie es `A` seguida
del número del RUT. Las solicitudes de firma y órdenes de pago que estaban abiertas
quedan canceladas, porque ningún proveedor las conoce. En un trámite detenido en
firma, usa «Reintentar envío».

Si tu base local usa firma asistida, la copia también. Para cambiarla, corre
`seed_demo_firma_avanzada --force`.

## 7. Despliegues automáticos

**Configura los secretos**, una sola vez, en **los dos** repositorios. En GitHub:
Settings → Environments → New environment → `staging`. Dentro, «Add environment
secret»:

| Secreto | Valor |
|---|---|
| `STAGING_HOST` | La IP de la VM |
| `STAGING_USER` | `deploy` |
| `STAGING_SSH_KEY` | Todo el contenido de `~/.ssh/crm_staging_deploy`, la clave **privada** |

Mientras falten, el flujo termina sin desplegar y deja un aviso.

**Qué pasa en cada merge a `main`:**

1. Corre la CI de ese repositorio. Si falla, no se despliega nada.
2. `deploy-staging.yml` entra por SSH con la clave restringida, que ejecuta
   `scripts/staging/deploy.sh`.
3. El script espera su turno, actualiza **los dos** repositorios a `main`, guarda
   las imágenes actuales como `:previous`, compila, respalda la base si hay
   migraciones pendientes, migra y reinicia.
4. Revisa que la API, el frontend y el PSC respondan, y que las tres direcciones
   pidan contraseña.
5. Si algo falla, restaura el código y las imágenes anteriores, y el flujo queda en
   rojo.

Un merge que solo cambia `docs/` no pasa por la CI del backend, así que no
despliega.

GitHub aplica los grupos de concurrencia por repositorio, por lo que el grupo
`deploy-staging` no ordena un repositorio con el otro. Lo hace el bloqueo que toma
`deploy.sh` en la VM: un despliegue espera a que termine el otro.

**Dónde ver el resultado:** en la pestaña Actions de cada repositorio, flujo
«Deploy staging». Allí está toda la salida del script.

**Desplegar a mano:** en Actions, «Deploy staging» → «Run workflow». O en la VM:

```bash
sudo -u deploy /srv/crm-easyoffice/crm-easyoffice-backend/scripts/staging/deploy.sh
```

**Volver atrás a mano**, a las imágenes y el código del despliegue anterior:

```bash
sudo -u deploy /srv/crm-easyoffice/crm-easyoffice-backend/scripts/staging/deploy.sh --rollback
```

> **Volver atrás no revierte las migraciones.** Si el despliegue fallido migró la
> base, el código anterior puede no funcionar con ella. `deploy.sh` respaldó la
> base justo antes de migrar: restáurala como se explica en la sección 8, con el
> respaldo `backup_*` de esa hora.

## 8. Respaldos

Corren cada día a las 03:00 y se guardan 7 días. Los resultados quedan en
`/var/log/crm-staging-backup.log`: cada ejecución termina en `OK:` o `FAILED:`.

| Qué | Dónde |
|---|---|
| Base de datos | Volumen `/backups` del servicio `postgres` |
| Archivos privados | `/srv/crm-easyoffice/backups/private_media_*.tar.gz` |
| Datos del PSC | `/srv/crm-easyoffice/backups/firma_sandbox_*.tar.gz` |

Están en la misma VM: protegen de un error, no de perder el servidor.

**Respaldar ahora:**

```bash
sudo -u deploy /srv/crm-easyoffice/crm-easyoffice-backend/scripts/staging/backup.sh
```

**Probar una restauración en una base separada**, sin tocar la de staging:

```bash
cd /srv/crm-easyoffice/crm-easyoffice-backend
docker compose -f docker-compose.staging.yml exec postgres backups
docker compose -f docker-compose.staging.yml exec postgres sh -c 'createdb -U "$POSTGRES_USER" prueba_restauracion && gunzip -c /backups/<archivo> | psql -q -U "$POSTGRES_USER" prueba_restauracion'
docker compose -f docker-compose.staging.yml exec postgres sh -c 'psql -U "$POSTGRES_USER" prueba_restauracion -c "select count(*) from clientes_cliente"'
docker compose -f docker-compose.staging.yml exec postgres sh -c 'dropdb -U "$POSTGRES_USER" prueba_restauracion'
```

El conteo debe coincidir con el de staging.

**Restaurar staging de verdad** reemplaza la base actual:

```bash
docker compose -f docker-compose.staging.yml stop django celeryworker celerybeat
docker compose -f docker-compose.staging.yml exec postgres restore <archivo>
docker compose -f docker-compose.staging.yml up -d --no-build --wait
```

Si además necesitas los archivos privados que corresponden a ese respaldo:

```bash
docker compose -f docker-compose.staging.yml run --rm --no-deps -T --entrypoint sh django -c 'find /app/private_media -mindepth 1 -delete && tar -xzf - --no-same-owner -C /app/private_media' < /srv/crm-easyoffice/backups/private_media_<fecha>.tar.gz
```

## 9. Apagar todo al terminar el semestre

Cuando ya no se use, para que el crédito de Google Cloud no se siga gastando:

1. **Quita los secretos.** En los dos repositorios, Settings → Environments →
   `staging` → borrar. Los flujos dejan de desplegar.
2. **Si necesitas algo, respáldalo y descárgalo.** Es solo información ficticia.
3. **Apaga la pila**, borrando sus datos:

   ```bash
   docker compose -f /srv/crm-easyoffice/crm-easyoffice-backend/docker-compose.staging.yml down --volumes
   ```

4. **En Google Cloud:** borra la instancia y su disco, y **libera la IP estática**.
   Una IP reservada sin usar se sigue cobrando.
5. **Borra las claves** `~/.ssh/crm_staging_deploy*` de tu computador, y las claves
   de prueba que ya no uses en Klap y Flow.

## Si Let's Encrypt rechaza el certificado

`sslip.io` no está en la lista pública de sufijos, así que todos quienes lo usan
en el mundo comparten el límite de 50 certificados por semana de Let's Encrypt.
Este es un riesgo real. En los registros de Traefik se ve como
`too many certificates`. Traefik guarda el certificado en un volumen y pide uno
solo para las tres direcciones, así que una vez emitido no vuelve a pedirlo hasta
renovarlo.

1. **Espera e intenta otra vez.** El cupo se libera de a poco. Reinicia con
   `docker compose -f docker-compose.staging.yml restart traefik`.
2. **Si no alcanza, compra un dominio barato** y apunta `@`, `firma` y `correo` a
   la IP. Cambia `STAGING_HOST` en `.traefik`, y el host en las variables de
   `.django` y `.firma`. Luego ejecuta `deploy.sh`. No hay que cambiar el código.

Mientras tanto, Traefik sirve un certificado autofirmado. La aplicación funciona
aceptando la advertencia del navegador, pero Klap y Flow no podrán entregar sus
avisos: se recurre a la consulta de estado de cada orden.
