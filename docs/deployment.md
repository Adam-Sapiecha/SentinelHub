# SentinelHub — wdrożenie 22.10.2026

Publiczny adres: https://luxonis.tail6ad453.ts.net:8443/sentinelhub/.
Stały handler Tailscale Funnel korzysta z istniejącego publicznego listenera 8443.
Odwiedzający nie potrzebuje VPN. Porty 443 i 10000 oraz prywatne usługi pozostają prywatne.
Nie trzeba zmieniać adresu przy restarcie kontenera ani otwierać portów w routerze.

## Aktualne wydanie

`/opt/stacks/sentinelhub/current` wskazuje na `releases/audit-20261022`.
Wrapper `compose` ładuje wyłącznie `docker-compose.yml` i prywatny plik `.env`
tego wydania (0600). Wolumen SQLite zachowany; nginx słucha tylko na loopback 8090.
API pozostaje w sieci kontenerów. Obrazy: `sentinelhub-api:audit-20261022`
i `sentinelhub-web:audit-20261022`.

```sh
/opt/stacks/sentinelhub/compose ps
/opt/stacks/sentinelhub/compose logs --tail 50 api web
/opt/stacks/sentinelhub/compose restart api web
```

Publiczna konfiguracja: `PUBLIC_URL=https://luxonis.tail6ad453.ts.net:8443/sentinelhub`,
`PUBLIC_BASE_PATH=/sentinelhub/`, `ALLOWED_ORIGINS=https://luxonis.tail6ad453.ts.net:8443`,
`WORKSPACE_TTL_HOURS=24`. Kluczy operatora nie umieszczaj w frontendzie ani repozytorium.
Publiczny nginx odrzuca importy operatora. WMS nadal wymaga odnowienia konta;
nie przedstawiaj go jako działającej publicznej integracji.

## Dane i limity

Nowe przestrzenie wygasają po 24 h, sprzątanie działa co 5 min i przy tworzeniu.
Migracja bazy v1 → v2 zachowuje stare rekordy bez automatycznego terminu usunięcia.
Limit globalny: 25 przestrzeni; do 8 MiB i 10 wyników na przestrzeń.
Przed aktualizacją wykonano spójną kopię SQLite w wolumenie:
`/app/data/before-audit-20261022.sqlite3`. Zachowano poprzedni obraz i wydanie.
Nie wykonuj odtwarzania bazy na działającym API; rollback powinien zachować
nowe zapisy albo odtworzyć kopię do osobnego wolumenu testowego.

Kernel hosta nie egzekwuje limitów RAM Dockera. Proces API ma dodatkowo
`RLIMIT_AS=768 MiB`, jednego workera, limit współbieżności 16 i jeden wątek BLAS.
CPU/PID i limity nginx pozostają aktywne. Nie zmieniano kernela ani nie restartowano hosta.

## Historyczny kontekst poprzedniego wdrożenia

Poniższy zapis pochodzi z 21.10.2026; aktualne wydanie i adres opisano wyżej.

## Potwierdzony kontekst serwera — 2026-10-21

`ssh luxonis`: użytkownik `pi`, `aarch64`, Debian 12 Bookworm. Pamięć dostępna
około 6,3 GiB, wolne miejsce około 30,9 GiB. Docker Engine 29.9.1 dostępny przez
`sudo -n docker`; bez sudo `pi` nie ma dostępu do socketu. Nie zmieniano grup.

Działające kontenery: Nextcloud, jego MariaDB, Portainer, ChordLab, ChordLab Beta
oraz `chordlab-cloudflared`. Sieci: bridge, host, none, chordlab_default,
nextcloud_default. Istniejące wolumeny należą do Nextcloud i Portainer — nie
wykorzystujemy ich. Potwierdzono zajęte 8081, 8082, 8083, 8088, 9443, a także
inne porty usług systemowych. **8090 nie był zajęty w momencie odczytu**; sprawdź
ponownie bezpośrednio przed wdrożeniem.

Tailscale Serve udostępnia prywatnie `/`, `/chordlab`, `/chordlab-beta` oraz
`/dashboard`. `https://luxonis.tail6ad453.ts.net` jest tylko dla tailnetu.
Nie rozpoznano publicznej domeny, DNS, publicznego IP ani reguł istniejącego
Tunelu Cloudflare. Sama obecność kontenera tunelu nie upoważnia do jego zmiany.
Nie zmieniaj istniejącego Tailscale Serve ani dostępu administracyjnego.

Nie dotykano `/usr/libexec/robothub`, `/home/robothub`, `/home/pi/depthai-venv`,
`/home/pi/oakd-env`, `/home/pi/venv-oakv3` ani projektu sprzętowego
`/home/pi/Desktop/ApkaGit/SystemAnalizyWadPostawy`.

## ARM64 i zasoby

Sprawdzono manifesty przypiętych obrazów i pobrano wszystkie 22 koła runtime
CPython 3.12/aarch64, w tym NumPy, Shapely, Pillow i pydantic-core.
[Dowód zgodności](arm64-compatibility.json). SQLite pochodzi z Pythona; nie
potrzebuje osobnego obrazu bazy. Brak CUDA, NVIDIA i wymaganych urządzeń.
Build i runtime wykonano na Luxonis ARM64: 101 testów, ingress Nginx,
przeglądarka przez HTTPS, restart/odtworzenie kontenerów i backup/restore.
Zdalnego joba CI nie uruchomiono.

Lokalny profil Windows AMD64: 900 węzłów / 1740 odcinków / prostokąt zalania,
5 kolejnych żądań, mediana 237,31 ms, zakres 204,74–294,55 ms, szczyt procesu
102,36 MiB. Obejmuje TestClient, importy, algorytm i SQLite, bez Nginx.
Nie jest to pomiar Raspberry Pi ani porównanie wydajności przed/po.

Compose deklaruje API 512 MiB / 1 CPU, Nginx 64 MiB / 0,5 CPU i tunel
128 MiB / 0,5 CPU. Na Luxonis limity RAM nie są egzekwowane.
Maksymalnie dwa przetwarzania i jeden import naraz, 16 połączeń/zadań Uvicorn.
Nie deklarujemy pojemności serwera dla dziesięciu aplikacji. Po wdrożeniu
zmierz `sudo docker stats --no-stream` i główny scenariusz przy istniejącym ruchu.
Kontroluj miejsce na karcie i rozmiary bazy, WAL, obrazów i backupów.

## Dane do uzupełnienia

- Własna publiczna subdomena: `sentinelhub.example.com` — **placeholder**.
- Sposób publikacji: istniejący uprawniony reverse proxy / osobno uzgodniony
  tunel. Nie zakładamy możliwości przekierowania portów.
- DNS i certyfikat HTTPS. Bez nich nie ma potwierdzonego publicznego URL.
- Opcjonalnie aktywna instancja OGC Sentinel z warstwą FLOOD i limitami konta.

Przewidziano subdomenę i zasoby `/...`; brak obsługi podścieżki. Nie ma
WebSocketów ani strumieniowania. Panel i API pracują pod jednym originem.

## Kontrola tylko do odczytu przed przyszłymi zmianami

```bash
ssh luxonis
uname -m
cat /etc/os-release
free -h
df -h /
ss -ltn
sudo docker ps
sudo docker network ls
sudo docker volume ls
tailscale serve status
```

Sprawdź własną konfigurację docelowego proxy bez ujawniania tokenów w logach.
Przed edycją istniejącego pliku wykonaj jego prywatny backup. W tym zadaniu
utworzono wyłącznie własny katalog i stos SentinelHub.

## Przygotowanie wydania i uruchomienie po wyraźnym poleceniu wdrożenia

Użyj osobnego katalogu, np. `/home/pi/apps/sentinelhub` (propozycja, nie katalog
utworzony w tym zadaniu). Najpierw zacommituj i opublikuj recenzowane zmiany.
Nie instaluj zależności do środowisk DepthAI.

```bash
git clone https://github.com/Adam-Sapiecha/SentinelHub.git sentinelhub
cd sentinelhub
git switch --detach REPLACE_WITH_REVIEWED_COMMIT
cp .env.example .env
chmod 600 .env
```

Ustaw `.env`:

```dotenv
COMPOSE_PROJECT_NAME=sentinelhub
DEMO_PORT=8090
IMAGE_TAG=REPLACE_WITH_RELEASE_ID
APP_MODE=application
WORKSPACE_DB_NAME=sentinelhub.sqlite3
PUBLIC_URL=https://sentinelhub.example.com
```

Domena jest placeholderem. Do lokalnego testu pozostaw PUBLIC_URL puste.
Przy konfiguracji publicznej wymagane jest HTTPS; hostname jest sprawdzany
przez aplikację. Nie wpisuj prywatnego adresu Tailscale jako publicznego URL.
Klucze operatora i Sentinel są opcjonalne dla własnych plików, wymagane dla
odpowiednich prawdziwych importów; [konfiguracja](sentinel.md).

```bash
sudo docker compose config --quiet
sudo docker compose build --pull
sudo docker compose up -d --wait --wait-timeout 120
DEMO_URL=http://127.0.0.1:8090 python3 tests/container_smoke.py
sudo docker compose exec -T web nginx -t
sudo docker compose ps
sudo docker compose logs --tail 100
```

Natywny build na Pi wybiera ARM64. Nie wymuszaj `linux/amd64`. Lokalny Docker
Desktop nie działał; build i testy runtime wykonano na Luxonis. Dla obecnego
wydania korzystaj z wrappera opisanego na początku dokumentu.

## Reverse proxy i HTTPS

Przepływ: publiczne HTTPS → uzgodniony proxy → `127.0.0.1:8090` → Nginx stosu →
wewnętrzne API:8000. Nie publikuj API ani dodatkowych 80/443. Nginx na hoście
nie był aktywny podczas odczytu; poniższy fragment nie jest propozycją zmiany
istniejącego Tailscale lub tunelu bez ustalenia sposobu publikacji.

Przykład Nginx, wszystkie dane domeny/certyfikatu do uzupełnienia:

```nginx
server {
    listen 443 ssl;
    server_name sentinelhub.example.com;
    ssl_certificate /PATH/TO/FULLCHAIN.pem;
    ssl_certificate_key /PATH/TO/PRIVKEY.pem;
    location / {
        proxy_pass http://127.0.0.1:8090;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_connect_timeout 3s;
        proxy_read_timeout 85s;
        client_max_body_size 3m;
    }
}
server {
    listen 80;
    server_name sentinelhub.example.com;
    return 301 https://$host$request_uri;
}
```

Przy proxy kontenerowym dodaj **tylko web** do istniejącej, uzgodnionej sieci,
np. dodatkowym `compose.proxy.yml`:

```yaml
services:
  web:
    networks:
      default: {}
      proxy:
        aliases: [sentinelhub-web]
networks:
  proxy:
    external: true
    name: REPLACE_WITH_AUTHORIZED_PROXY_NETWORK
```

Proxy kieruje do `sentinelhub-web:80`. API pozostaje w sieci tego stosu.
Nginx używa DNS Dockera z krótkim TTL do ponownego rozpoznania adresu API po
odtworzeniu kontenera; nie zakłada stałego IP backendu.
Nie zgaduj nazwy sieci ani nie podłączaj się do sieci Nextcloud. Polecenia
Compose muszą konsekwentnie zawierać oba pliki, jeśli dodano override.

Nginx domyślnie nie ufa nagłówkowi IP od klienta. Za wspólnym proxy limit
5 żądań/s i tworzenia przestrzeni 1/min + burst 3 będzie wspólny dla adresu
proxy. Aby rozdzielić odwiedzających, administrator powinien wpisać konkretny,
zweryfikowany adres/CIDR proxy w `set_real_ip_from`, `real_ip_header
X-Forwarded-For` i `real_ip_recursive on`. Nigdy nie ufaj `0.0.0.0/0`.
Aplikacja nie potrzebuje forwarded IP; Uvicorn ma `--no-proxy-headers`.

## Baza, inicjalizacja i migracje

Wolumen `sentinelhub_sentinel-data` jest tworzony przez ten stos. SQLite:
`/app/data/${WORKSPACE_DB_NAME}`. Inicjalizacja tworzy jedynie brakujący schemat;
aktualizacja nie usuwa danych. Migrations v1 wykonują się w `BEGIN IMMEDIATE`.
Nowe dane i wyniki trafiają do transakcji z kontrolą revision. Nieobsługiwany
nowszy schemat blokuje start. `/ready` sprawdza schemat i dostęp do tabel;
`/health` jest liveness. Readiness nie potwierdza dostępu do Sentinel.

Dane własne, próbne pliki użytkownika i zewnętrzne importy mają oznaczenia
`user`, `sample`, `live`. Reset `/sample.html` niczego w bazie nie zmienia.
Właściciel może usunąć swój wynik lub przestrzeń, nie dane innego użytkownika.
Limit historii 10/8 MiB może usuwać najstarsze snapshoty przy nowym wyniku;
aktualna para danych nie jest przez to resetowana.

## Backup i sprawdzone odtworzenie

Narzędzie korzysta z SQLite Online Backup API, `integrity_check`, kontroli
kluczy obcych i wersji schematu. Test odtworzenia potwierdza ponowne działanie
klucza właściciela, odczyt danych i dokładnego snapshotu. Test wykonano lokalnie,
nie na serwerze. Nie kopiuj samego aktywnego pliku bazy pomijając WAL.

Wybierz unikalny identyfikator backupu, poniżej `REPLACE_WITH_BACKUP_ID`:

```bash
sudo docker compose exec -T api python -m src.manage backup \
  --database /app/data/sentinelhub.sqlite3 \
  --output /app/data/backups/REPLACE_WITH_BACKUP_ID.sqlite3
mkdir -m 700 -p backups
sudo docker compose cp api:/app/data/backups/REPLACE_WITH_BACKUP_ID.sqlite3 ./backups/REPLACE_WITH_BACKUP_ID.sqlite3
sudo sha256sum ./backups/REPLACE_WITH_BACKUP_ID.sqlite3
```

Dostosuj źródłową nazwę, jeśli zmieniono WORKSPACE_DB_NAME. Pliki tworzone są
z prawami 0600, katalog danych z 0700; `.env` i backupy mają pozostać prywatne.
Kopia na tej samej microSD nie chroni przed awarią karty — przekaż zweryfikowaną
kopię do własnego, prywatnego magazynu poza serwerem, z szyfrowaniem i retencją.
Nie wysyłano żadnych danych w tym zadaniu.

Odtwarzaj do **nowego pliku**, zachowując aktualną bazę:

```bash
sudo docker compose stop api
sudo docker compose run --rm --no-deps api python -m src.manage restore \
  --source /app/data/backups/REPLACE_WITH_BACKUP_ID.sqlite3 \
  --destination /app/data/recovered-release.sqlite3
# Ustaw WORKSPACE_DB_NAME=recovered-release.sqlite3 w .env.
sudo docker compose up -d --wait
```

Po odtworzeniu otwórz własną przestrzeń, odczytaj historię i przelicz znany
przypadek. Oryginalny plik pozostaje do powrotu. Restore odmawia nadpisania
istniejącego celu i nie akceptuje nowszego schematu. Przywraca stan danych
**i uprawnień z chwili backupu**: wcześniejsze klucze mogą odzyskać ważność.
Po odtworzeniu przeprowadź potrzebną rotację. Backup nie zawiera jawnych kluczy,
ale zawiera prywatne dane wejściowe i wyniki.

## Aktualizacja, rollback, zatrzymanie

Przed aktualizacją wykonaj i przetestuj backup, zachowaj commit, IMAGE_TAG,
WORKSPACE_DB_NAME i prywatną konfigurację poprzedniej wersji. Nie usuwaj starych
obrazów przed weryfikacją nowego wydania.

```bash
git fetch origin
git switch --detach REPLACE_WITH_NEW_COMMIT
# Ustaw nowy IMAGE_TAG w .env, zachowaj nazwę bazy.
sudo docker compose build --pull
sudo docker compose up -d --wait
DEMO_URL=http://127.0.0.1:8090 python3 tests/container_smoke.py
```

Rollback przy tym samym schemacie v1: przywróć poprzedni zgodny commit i IMAGE_TAG,
pozostaw bazę, uruchom `sudo docker compose up -d --no-build --wait` i sprawdź
odczyt. Przy przyszłej migracji niezgodnej wstecznie potrzebna jest para starego
wydania i odpowiadającego mu backupu odtworzonego pod nową nazwą. Nie wykonujemy
automatycznych downgrade'ów. Powrót do backupu odrzuca późniejsze zapisy —
najpierw zachowaj obecną bazę, nie udawaj migracji bez utraty danych.

`sudo docker compose stop` zatrzymuje tylko ten projekt; `start` go wznawia.
`sudo docker compose down` odtwarza się później przez `up -d --wait`, z zachowaniem
wolumenu. **Nie używaj `down -v`, globalnego prune ani kasowania wolumenów.**
`restart: unless-stopped` zapewnia powrót po restarcie systemu, jeśli Docker
uruchamia się przy starcie serwera; nie zmieniano ustawień tej usługi.

Operator może zinwentaryzować przestrzenie bez ujawniania kluczy:

```bash
sudo docker compose exec -T api python -m src.manage list-workspaces --database /app/data/sentinelhub.sqlite3
```

Usunięcie pojedynczej osieroconej przestrzeni jest jawną operacją administracyjną,
wyłącznie po backupie i decyzji właściciela:

```bash
sudo docker compose exec -T api python -m src.manage delete-workspace \
  --database /app/data/sentinelhub.sqlite3 \
  --workspace-id REPLACE_WITH_ID --confirm-id REPLACE_WITH_SAME_ID
```

Nie ma automatycznego kasowania przestrzeni użytkowników. Monitoruj limit 25
przestrzeni, dysk i rotowane logi stdout/stderr (2 × 5 MiB/usługę).

## Bramy przed publikacją

Uruchom build i smoke na ARM64, potwierdź trwałość po `restart` i odtworzeniu
kontenerów (CI włącza `VERIFY_CONTAINER_RESTART=1`; na luxonis dodatkowo
`DOCKER_COMMAND='sudo docker'`), backup/restore na tym środowisku i realne limity.
Sprawdź publiczne HTTPS na komputerze i telefonie oraz brak dostępu cudzym kluczem.
Zrotuj wartość ujawnioną historycznie w `.env`. Dla WMS przygotuj aktywną instancję
z warstwą i zweryfikuj realny wynik. Dopiero wtedy wpisz rzeczywisty URL do
`portfolio.json`. Sama konfiguracja i SSH read-only nie oznaczają wdrożenia.
