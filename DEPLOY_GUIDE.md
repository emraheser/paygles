# 🚀 Paygles → Google Cloud Deployment Rehberi

Bu rehber seni adım adım GCP'ye deploy edene kadar götürecek.

---

## Adım 1: gcloud CLI Giriş (Tek seferlik)

Terminal'de şu komutu çalıştır:

```bash
gcloud auth login
```

Tarayıcı açılacak → Google hesabınla giriş yap → izin ver.

---

## Adım 2: GCP Proje Ayarla

Google Cloud Console'da bir proje oluşturmuş olman lazım.
Proje ID'ni öğrenmek için: https://console.cloud.google.com → üst barda proje adının yanındaki ID

```bash
# Proje ID'ni set et (kendi ID'ni yaz)
gcloud config set project SENIN-PROJE-ID

# Gerekli API'ları aç
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com
```

---

## Adım 3: Secret'ları Hazırla

Backend'in çalışması için şu environment variable'lar gerekli.
Mevcut `.env` dosyandaki değerleri kullanacağız.

```bash
# Mevcut .env'den değerleri oku (kontrol et, doğru mu)
cat backend/.env
```

---

## Adım 4: Deploy Et

```bash
cd /home/emrah/projects/paygles
export GCP_PROJECT_ID=SENIN-PROJE-ID
./deploy.sh
```

Script otomatik olarak:
1. ✅ Artifact Registry repo oluşturur
2. ✅ Backend image build + push
3. ✅ Backend Cloud Run'a deploy
4. ✅ Frontend image build (backend URL ile)
5. ✅ Frontend Cloud Run'a deploy
6. ✅ CORS günceller

Sonunda şunu göreceksin:
```
✅ Deployment complete!
   Frontend: https://paygles-web-xxxxx.run.app
   Backend:  https://paygles-api-xxxxx.run.app
```

---

## Adım 5: Backend Secret'ları Yükle

Deploy sonrası backend'e secret'ları ekle (SUPABASE_URL artık YOK — SQLite kullanıyoruz):

```bash
gcloud run services update paygles-api \
  --region europe-west1 \
  --set-env-vars "\
TELEGRAM_BOT_TOKEN=...,\
TELEGRAM_CHAT_ID=...,\
TELEGRAM_API_ID=...,\
TELEGRAM_API_HASH=...,\
OPENROUTER_API_KEY=...,\
TELETHON_STRING_SESSION="
```

**Not:** `deploy.sh` zaten `SQLITE_PATH=/data/paygles.db` ortam değişkenini ve GCS volume mount'unu ayarlar.

**Önemli:** Cloud Run üzerinde SQLite kullanıldığı için `max-instances=1`'de tutulmalıdır. SQLite dosyası `gs://<PROJECT_ID>-paygles-data` bucket'ında Cloud Storage FUSE volume mount ile `/data/paygles.db` olarak kalıcı tutulur.

---

## Adım 6: Test Et

```bash
# Backend sağlık kontrolü
curl https://paygles-api-xxxxx.run.app/health

# Frontend'i tarayıcıda aç
echo "Frontend URL'ini tarayıcıda aç"
```

---

## Sorun Giderme

### "Permission denied" hatası
```bash
gcloud auth login
gcloud config set project SENIN-PROJE-ID
```

### "API not enabled" hatası
```bash
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com
```

### Backend loglarını gör
```bash
gcloud run services logs read paygles-api --region europe-west1 --limit 50
```

### Frontend loglarını gör
```bash
gcloud run services logs read paygles-web --region europe-west1 --limit 50
```

---

## Maliyet

- Backend (min-instances=1): ~$5-8/ay
- Frontend (scale-to-zero): ~$0-1/ay
- Cloud Build: ücretsiz tier (120 dk/gün)
- **Toplam: ~$6-10/ay → $300 kredi ile 6+ ay**
