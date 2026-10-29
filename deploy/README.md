# Деплой design.proftex.tech

Артефакты задачи T07. Сервис живёт в `/opt/design-studio` на VDS (Нидерланды), рядом с `ops.proftex.tech`, который уже стоит за Caddy на портах 80/443. Наружу сервис выходит только через этот Caddy: контейнер публикует порт на `127.0.0.1:8000`, новых портов в `ufw` нет.

| Файл | Что делает |
| --- | --- |
| `Dockerfile` | Node 20 собирает `frontend/dist`, Python 3.12 slim ставит бэкенд; пользователь `app` (UID 10001); healthcheck на `/api/health`; `uvicorn --workers 1` |
| `docker-compose.yml` | сервис и контейнер `design-studio`, том `design-data` (→ `/data`), сеть `design-net` (172.30.57.0/24), `env_file: ../.env`, `models.json` смонтирован только на чтение |
| `design.caddy` | блок `design.proftex.tech`: `reverse_proxy`, лимит тела 210 МБ, HSTS |
| `caddy_check.sh` | объединяет существующий Caddyfile с `design.caddy`, делает копию старого, `caddy validate`, проверяет, что diff — только добавления |
| `deploy.sh` | `git pull` → сборка → запуск → ждёт 200 от `/api/health` → откат на прошлый образ при провале; `--dry-run` |
| `backup/design-studio.sh` | хук для `/opt/backup/pre.d/`: ежедневно `sqlite3 .backup` + `integrity_check`, по воскресеньям `rsync` `results/` и `inputs/` |
| `backup/verify.sh` | проверка бэкапа (S-13); `--selftest` гоняет хук и проверку на тестовой базе |
| `disk_alert.sh` | cron: предупреждение, если свободно меньше 10% |
| `tests/run.sh` | все проверки T07 одной командой |

## Почему один воркер

Очередь генераций, семафор `MAX_PARALLEL=4` и счётчик попыток входа живут в памяти процесса. С `--workers 2` у каждого процесса будет свой семафор и свой счётчик: одновременно пойдёт 8 запросов в OpenAI, а попыток входа станет 10 в минуту. Поэтому `--workers 1` стоит и в `CMD` образа, и в `command` compose, а `tests/run.sh` это проверяет.

## Как Caddy видит сервис и откуда берётся IP клиента

Подсеть `design-net` фиксирована (`DESIGN_SUBNET`, по умолчанию `172.30.57.0/24`), и `TRUSTED_PROXIES` равен ей. В этой сети нет никого, кроме нашего контейнера и Caddy, поэтому `X-Forwarded-For` принимается только от Caddy. Caddy сам заменяет присланный клиентом `X-Forwarded-For` на настоящий адрес, подделать его снаружи нельзя. Uvicorn запущен с `--no-proxy-headers`, чтобы заголовок разбирало приложение, а не он.

Подходят оба варианта запуска Caddy, какой из них на VDS, покажет разведка:

- **Caddy на хосте (systemd).** `reverse_proxy 127.0.0.1:8000` как в `design.caddy`. Запрос приходит в контейнер с адреса шлюза `172.30.57.1` (проверено: так пишет лог Uvicorn).
- **Caddy в Docker.** Подключить контейнер Caddy к сети: `docker network connect design-net <контейнер caddy>` (и `networks: [design-net]` с `external: true` в его compose, чтобы пережило пересоздание), а в `design.caddy` заменить адрес на `design-studio:8000`. Запрос приходит с адреса Caddy в `172.30.57.0/24`.

Если подсеть `172.30.57.0/24` на сервере занята, задайте `DESIGN_SUBNET=...` в окружении при запуске compose (и в `deploy.sh`).

## Разведка на VDS (только чтение)

В этой сессии доступа к серверу не было, поэтому разведку делает тот, у кого есть `ssh vds-root` (T16), до любых изменений. Результаты записать в отчёт T16.

```bash
ssh vds-root '
  systemctl status caddy --no-pager 2>/dev/null | head -5      # Caddy как systemd-служба?
  docker ps --format "{{.Names}}\t{{.Image}}\t{{.Ports}}" | grep -i caddy   # или контейнер?
  ls -l /etc/caddy/ 2>/dev/null                                # путь к Caddyfile
  docker inspect -f "{{json .NetworkSettings.Networks}}" $(docker ps -qf ancestor=caddy) 2>/dev/null
  docker network ls; ip -br addr | grep -E "br-|docker"         # занята ли 172.30.57.0/24
  ls -l /opt/backup /opt/backup/pre.d 2>/dev/null; cat /opt/backup/*.sh 2>/dev/null | head -40   # как устроен бэкап
  df -h / /var/lib/docker; ufw status
  curl -s -o /dev/null -w "ops: %{http_code}\n" https://ops.proftex.tech
'
```

От разведки зависят три места: адрес в `design.caddy` (хост или Docker), `DESIGN_SUBNET` (если подсеть занята) и `BACKUP_DIR` хука (куда внешний бэкап забирает файлы; по умолчанию `/opt/backup/data/design-studio`).

## Первая установка (T16)

```bash
# 0. Код ответа соседа до изменений
curl -s -o /dev/null -w '%{http_code}\n' https://ops.proftex.tech > /root/ops-before.txt

# 1. Код и .env
git clone https://github.com/m-dan12/proftex-design /opt/design-studio && cd /opt/design-studio
cp .env.example .env && chmod 600 .env
# SECRET_KEY и ADMIN_PASSWORD генерируются на сервере, в чат не печатаются:
python3 -c "import secrets; print(secrets.token_urlsafe(48))"   # → SECRET_KEY
python3 -c "import secrets; print(secrets.token_urlsafe(12))"   # → ADMIN_PASSWORD, копия в /root/design-admin.txt (600)

# 2. Сборка и запуск
deploy/deploy.sh --no-pull

# 3. Caddy: копия, validate, только добавления, перезагрузка без остановки
deploy/caddy_check.sh /etc/caddy/Caddyfile            # → Caddyfile.new и Caddyfile.bak-...
cp /etc/caddy/Caddyfile.new /etc/caddy/Caddyfile && systemctl reload caddy
#   Caddy в Docker: CADDY_CMD="docker exec caddy caddy" CADDY_VALIDATE_PATH=/etc/caddy/Caddyfile.new \
#   deploy/caddy_check.sh <путь к Caddyfile на хосте>; затем docker exec caddy caddy reload --config /etc/caddy/Caddyfile

# 4. Бэкап и контроль диска
install -m 750 deploy/backup/design-studio.sh /opt/backup/pre.d/design-studio.sh
WEEKLY=1 /opt/backup/pre.d/design-studio.sh && deploy/backup/verify.sh
echo '*/30 * * * * root /opt/design-studio/deploy/disk_alert.sh' > /etc/cron.d/design-studio-disk

# 5. Сосед не пострадал
diff /root/ops-before.txt <(curl -s -o /dev/null -w '%{http_code}\n' https://ops.proftex.tech)
```

`disk_alert.sh` пишет в syslog (`journalctl -t design-studio`) и в stderr (cron пришлёт письмо, если задан `MAILTO`); для мессенджера можно задать `ALERT_WEBHOOK_URL` в файле cron.

## Обновление и откат

```bash
cd /opt/design-studio && deploy/deploy.sh          # pull, сборка, запуск, проверка, при провале — откат
deploy/deploy.sh --dry-run                          # что будет сделано
DRY_RUN_HEALTH=fail deploy/deploy.sh --dry-run      # как выглядит откат
```

Откат вручную — две команды:

```bash
docker tag design-studio:previous design-studio:current && docker compose -f deploy/docker-compose.yml up -d --force-recreate
cp /etc/caddy/Caddyfile.bak-<время> /etc/caddy/Caddyfile && systemctl reload caddy
```

Цены в `models.json` правятся на сервере без пересборки: файл смонтирован в контейнер, после правки — `docker restart design-studio`.

## Бэкап

- База: каждый день хук делает `sqlite3 app.db ".backup ..."` (согласованный снимок при работающем сервисе, с учётом WAL), проверяет `PRAGMA integrity_check` и только потом заменяет `app.db` в `BACKUP_DIR`. Если на хосте нет `sqlite3`, тот же онлайн-бэкап делает модуль `sqlite3` из `python3`.
- Картинки: по воскресеньям (или `WEEKLY=1`) `rsync -a` папок `results/` и `inputs/` в `BACKUP_DIR/files/`, инкрементально и без `--delete`, так что удалённые в сервисе работы в бэкапе остаются. `thumbs/` не копируются.
- Восстановление: остановить контейнер, скопировать `app.db` и `files/*` в том (`docker volume inspect -f '{{.Mountpoint}}' design-data`), `chown -R 10001:10001`, запустить; превью пересоздаются.

## Проверки

```bash
deploy/tests/run.sh           # все критерии T07; без Docker часть пропускается
SKIP_BUILD=1 deploy/tests/run.sh   # без пересборки, на готовом design-studio:current
```
