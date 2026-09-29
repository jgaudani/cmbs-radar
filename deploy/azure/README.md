# CMBS Radar on one Azure VM

A short-lived demo host: one Ubuntu VM running Postgres, the app and Caddy
(HTTPS and a shared login) with Docker Compose, loaded from the database
snapshot. About $10 for a week on a B2s. The Kubernetes manifests in
`deploy/` are the production path; this is the cheap one.

```
Internet --443--> Caddy (HTTPS, login) --> app :8080 --> Postgres
            one VM; only 80/443 open to all, SSH from your IP only
```

| File | Purpose |
|---|---|
| `compose.yml` | Postgres, the app (built from the repo's Dockerfile) and Caddy. Only Caddy publishes ports. |
| `Caddyfile` | Let's Encrypt certificate, basic auth, proxy to the app. |
| `.env.example` | Hostname, login, database password, Anthropic key. Copy to `.env` on the VM. |
| `cloud-init.yml` | Installs Docker and git on first boot. |

Measured: the stack uses about 470 MB of memory (app 245 MB, Postgres
205 MB, Caddy 15 MB). A B1ms (2 GB) works; a B2s (2 vCPU, 4 GB) builds the
image faster and runs rate scenarios faster.

## 1. Create the VM (from your machine, repo root)

Needs the [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli).
```bash
az login
```
```bash
az group create --name cmbs-radar-demo --location eastus
```
```bash
az vm create --resource-group cmbs-radar-demo --name cmbs-radar --image Ubuntu2404 --size Standard_B2s --admin-username azureuser --generate-ssh-keys --public-ip-sku Standard --os-disk-size-gb 32 --custom-data deploy/azure/cloud-init.yml
```
Open HTTP and HTTPS to everyone:
```bash
az vm open-port --resource-group cmbs-radar-demo --name cmbs-radar --port 80,443 --priority 1010
```
Limit SSH to your own IP. `az vm create` adds a rule open to the internet;
list the rules to find its name (usually `default-allow-ssh`), then:
```bash
az network nsg rule list --resource-group cmbs-radar-demo --nsg-name cmbs-radarNSG --output table
```
```bash
az network nsg rule update --resource-group cmbs-radar-demo --nsg-name cmbs-radarNSG --name default-allow-ssh --source-address-prefixes "$(curl -s https://api.ipify.org)/32"
```
Note the public IP:
```bash
az vm show --show-details --resource-group cmbs-radar-demo --name cmbs-radar --query publicIps --output tsv
```

Set a budget alert now (Portal: Cost Management > Budgets, scope the
resource group, e.g. $25 with an email alert).

## 2. Point cmbs.jaygaudani.com at the VM

`jaygaudani.com` is in Azure DNS (no CAA record, so Let's Encrypt can issue).
Find the zone's resource group, then add an A record for `cmbs`:
```bash
az network dns zone list --query "[?name=='jaygaudani.com'].resourceGroup" --output tsv
```
```bash
az network dns record-set a add-record --resource-group <zone-resource-group> --zone-name jaygaudani.com --record-set-name cmbs --ipv4-address <public-ip> --ttl 300
```
Check it resolves before starting Caddy (it requests the certificate on
start; if DNS isn't ready it retries, but slowly):
```bash
dig +short cmbs.jaygaudani.com
```
This only adds `cmbs`; the site at `jaygaudani.com` and `www` is untouched.
Without a domain, skip this step and use `<public-ip>.sslip.io` as
`SITE_ADDRESS`.

## 3. Copy the code and the snapshot

The code goes up as an archive of the last commit, so commit first.
```bash
git archive --format=tar.gz -o /tmp/cmbs-radar.tar.gz HEAD
```
```bash
scp /tmp/cmbs-radar.tar.gz data/cmbs-radar.dump azureuser@<public-ip>:~
```

## 4. Configure and start (on the VM)

```bash
ssh azureuser@<public-ip>
```
Wait for cloud-init to finish installing Docker (a minute or two after boot):
```bash
cloud-init status --wait && docker --version
```
If `docker` says permission denied, log out and back in (the docker group
applies to new sessions).
```bash
mkdir cmbs-radar && tar -xzf cmbs-radar.tar.gz -C cmbs-radar && cd cmbs-radar/deploy/azure
```
```bash
cp .env.example .env && chmod 600 .env
```
Make the login hash and a database password, then put them in `.env` with
`nano .env`, keeping the single quotes:
```bash
docker run --rm caddy:2 caddy hash-password --plaintext 'choose-a-password'
```
```bash
openssl rand -hex 16
```
`SITE_ADDRESS` is already `cmbs.jaygaudani.com`. Leave `ANTHROPIC_API_KEY` empty and set `API_FLAGS='--no-briefs'`
if you don't want briefs.

Start Postgres and restore the snapshot:
```bash
docker compose up -d --wait postgres
```
```bash
docker compose cp ~/cmbs-radar.dump postgres:/tmp/cmbs-radar.dump
```
```bash
docker compose exec -T postgres pg_restore -U radar -d radar --no-owner --no-privileges --clean --if-exists /tmp/cmbs-radar.dump
```
Build the app and start everything (the first build takes a few minutes):
```bash
docker compose up -d --build --wait
```
Open https://cmbs.jaygaudani.com and sign in. The app precomputes the −50bp
scenario after it starts, so wait about a minute before demoing it.

## Operating it

| Task | Command (in `deploy/azure/` on the VM) |
|---|---|
| Status | `docker compose ps` |
| Logs | `docker compose logs -f app` (or `caddy`) |
| Deploy new code | copy a new archive, extract over the folder, then `docker compose up -d --build app` |
| Briefs off / on | set `API_FLAGS='--no-briefs'` or `''` in `.env`, then `docker compose up -d app` |
| Change the login | new hash in `.env`, then `docker compose up -d caddy` |
| Stop the VM (keeps disk, stops compute billing) | from your machine: `az vm deallocate --resource-group cmbs-radar-demo --name cmbs-radar` |

After a deallocate and start, the public IP stays the same (Standard SKU is
static) and the containers restart on their own.

Refreshing data is optional for a week; the data changes monthly. To do it:
`docker compose run --rm -e EDGAR_USER_AGENT='Your Name you@example.com' app cmbs-ingest`,
then `cmbs-score` and `cmbs-backtest` the same way. The app picks up the new
scoring run within a minute.

## Safety

- Postgres and the app publish no ports: only Caddy (80/443) is reachable.
  Don't add `ports:` to them.
- Every page and API call needs the login, which stops strangers from
  running up Claude costs through briefs. Also set a spend limit in the
  Anthropic console.
- `.env` holds secrets: it is gitignored and should stay `chmod 600` on the VM.

## Tear down

Delete the DNS record first. The zone lives in another resource group, so
deleting the demo group leaves it behind, pointing at an IP Azure can hand
to someone else (a subdomain takeover risk):
```bash
az network dns record-set a delete --resource-group <zone-resource-group> --zone-name jaygaudani.com --name cmbs --yes
```
Then delete the VM, disk, IP and network in one go:
```bash
az group delete --name cmbs-radar-demo --yes
```
