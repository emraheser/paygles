# 🚀 Paygles VPS Deployment Rehberi

Bu rehber Ubuntu tabanlı bir VPS üzerinde Paygles'i Docker Compose + PostgreSQL ile ayağa kaldırır.

---

## 1) Sunucu hazırlığı

VPS'te Docker ve Compose plugin kurulu olmalı.

```bash
sudo apt-get update
sudo apt-get install -y docker.io docker-compose-plugin
sudo systemctl enable --now docker
```

---

## 2) Projeyi sunucuya al

```bash
git clone https://github.com/emraheser/paygles.git
cd paygles
```

---

## 3) Backend ortam değişkenleri

```bash
cp backend/.env.example backend/.env
nano backend/.env
```

Girilmesi gereken kritik alanlar:
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `TELEGRAM_API_ID`
- `TELEGRAM_API_HASH`
- `OPENROUTER_API_KEY` (kullanıyorsan)

DB tarafında varsayılan artık PostgreSQL'dir. Gerekirse:
- `POSTGRES_DB`
- `POSTGRES_USER`
- `POSTGRES_PASSWORD`
- `DATABASE_URL`

---

## 4) Deploy

```bash
chmod +x deploy.sh
./deploy.sh
```

Bu script:
1. Docker/Compose kontrolü yapar
2. Image'ları build eder
3. Servisleri ayağa kaldırır (`docker compose up -d`)

---

## 5) Erişim

- Frontend: `http://<VPS_IP>:3000`
- Backend: `http://<VPS_IP>:8000/health`

---

## 6) Güncelleme

Yeni kod geldiğinde:

```bash
git pull
./deploy.sh
```

---

## 7) Faydalı komutlar

```bash
docker compose ps
docker compose logs -f backend
docker compose logs -f frontend
docker compose restart backend
```

---

## Not

`docker-compose.yml` içindeki `postgres_data` volume'u PostgreSQL verisini kalıcı tutar.
