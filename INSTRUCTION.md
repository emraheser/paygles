# Paygles - Hızlı Dev Handover (AI + Human)

Bu doküman yeni bir AI session veya yeni bir geliştirici için **tek bakışta proje durumu** verir.

---

## 1) Proje ne yapıyor?

Paygles, web forumlarını ve Telegram kaynaklarını periyodik tarar, sıcak fırsat konularını DB’ye kaydeder, dashboard’da listeler, kurallara uyan kayıtları Telegram bot ile kanala gönderir.

Ana amaç: yeni açılan fırsat konularını hızlı yakalamak, temiz başlık/link/fiyat ile takip etmek.

---

## 2) Mimari Özet

- Backend: FastAPI + SQLAlchemy Async + APScheduler
- Frontend: React + Vite + Tailwind + shadcn/ui
- DB: SQLite (`paygles.db`) — `SQLITE_PATH` env ile yol değiştirilebilir.
- Scheduler: App açılışında hemen 1 kez çalışır, sonra interval’e göre döner

Ana backend modülleri:
- `src/services/scraper.py`: forum scrape + parse + upsert
- `src/services/telegram_reader.py`: Telegram channel okuma
- `src/services/notifier.py`: Telegram gönderimi + metadata enrichment
- `src/services/scheduler.py`: job döngüsü

---

## 3) Çalışma Döngüsü (Gerçek Akış)

Her scheduler turunda sıralama:
1. Aktif web kaynaklarını scrape et
2. Telegram kanallarını oku
3. Telegram’a gönderilecek uygun kayıtları gönder
4. `last_scrape_completed_at` setting’ini güncelle

Interval:
- `app_settings.scrape_interval_minutes`
- `/admin/settings/scrape_interval_minutes` ile runtime’da değiştirilebilir

---

## 4) Scrape ve Upsert Kuralları

`scraped_topics.url` unique olduğu için aynı konu tekrar insert edilmez, update edilir.

Bir topic için yakalanan ana alanlar:
- `title`
- `url` (kaynak konu URL)
- `source_topic_id` (URL’den regex)
- `source_date`
- `is_sticky`
- `scraped_at`

Filtreler/kurallar:
- Sticky/locked konular (`is_sticky = true`) dashboard ve notifier’da dışlanır
- Gelecek tarihli anomaliler insert edilmez
- `scraped_at` her gözlem turunda güncellenir

---

## 5) Deal Metadata (Başlık/Fiyat/Link) Nasıl Üretiliyor?

Yeni kayıtta `deal_url` varsa metadata üretimi yapılır:

1. Sayfa çekilir
2. Fiyat önce regex/meta/json sinyallerinden çıkarılır
3. Regex fiyat yoksa Ollama/Qwen ile fiyat fallback denenir
4. Başlık temizleme Ollama/Qwen ile yapılır (başarısızsa ham başlık)
5. Link normalize edilir (`clean_deal_url`):
   - mobile redirect prefix temizliği (`m.`, `sl.`)
   - `?query` ve `#fragment` silinir (tracking parametreleri düşer)

LLM ayarı:
- `OLLAMA_BASE_URL` (default `http://localhost:11434`)
- `OLLAMA_MODEL` (default `qwen3.5:9b`)

---

## 6) Telegram Bildirim Kuralları

Otomatik gönderimde kayıt şu şartlarla seçilir:
- `notification_sent = false`
- `domain_skipped = false`
- `is_sticky = false`
- `deleted_by_user = false`
- (`deal_title` dolu **veya** `deal_price` dolu)

Notlar:
- Hem başlık hem fiyat boşsa otomatik Telegram’a gitmez, dashboard’da kalır
- Domain whitelist’e uymuyorsa `domain_skipped = true` olur
- Başarılı gönderimde `notification_sent = true`

---

## 7) Dashboard Davranışı (Güncel)

`/dashboard/topics` sıralama:
- `coalesce(source_date, scraped_at) DESC`
- sonra `scraped_at DESC`, `id DESC`

Listede görünmeyenler:
- `is_sticky = true`
- `deleted_by_user = true`

UI özellikleri:
- Kaynak filtresi (`Tümü` + site bazlı)
- Son 30 dk rozet
- Yeni/Eski kayıt ayrımı (eski kayıtlar aç-kapa)
- Sabit polling yerine `last_scrape_completed_at` değişince yenileme
- Kart aksiyonları:
  - `Gönder`: dialog açılır, başlık + link otomatik dolar, kullanıcı düzenleyip gönderir
  - `Sil`: soft-delete yapar

---

## 8) Silme Mantığı (Önemli)

Dashboard’daki silme **fiziksel delete değil**, soft-delete’tir:
- `deleted_by_user = true`
- `notification_sent = true`

Neden?
- Fiziksel silmede aynı URL sonraki scrape turunda tekrar insert olabiliyordu
- Soft-delete ile kayıt DB’de tombstone olarak kalır, dashboard’a geri gelmez
- Scraper, `deleted_by_user=true` kayıtları tekrar canlandırmaz

İstisna:
- Admin manuel link akışında aynı kayıt tekrar aktiflenebilir (`deleted_by_user=false`)

---

## 9) Veri Modeli Kısa Notlar

Ana tablolar:
- `target_sites`
- `scraped_topics`
- `app_settings`
- `keyword_filters`
- `allowed_domains`

`scraped_topics` kritik alanlar:
- `url` (unique)
- `deal_url`
- `clean_deal_url`
- `deal_title`
- `deal_price`
- `notification_sent`
- `domain_skipped`
- `deleted_by_user`

---

## 10) API Özet (en çok kullanılan)

Admin:
- `GET /admin/sites`
- `POST /admin/sites`
- `PUT /admin/sites/{id}`
- `DELETE /admin/sites/{id}`
- `PUT /admin/settings/{key}`
- `POST /admin/manual-link`

Dashboard:
- `GET /dashboard/sync-status`
- `GET /dashboard/topics`
- `POST /dashboard/topics/{id}/send` (opsiyonel `title`, `link` override)
- `DELETE /dashboard/topics/{id}` (soft-delete)

---

## 11) Environment Değişkenleri

Zorunlu / kritik:
- `TELEGRAM_BOT_TOKEN`

Opsiyonel:
- `TELEGRAM_CHAT_ID`
- `SQLITE_PATH` (default `./paygles.db`)
- `TELEGRAM_API_ID`
- `TELEGRAM_API_HASH`
- `OLLAMA_BASE_URL`
- `OLLAMA_MODEL`

---

## 12) Hızlı Çalıştırma

Backend:
```bash
cd backend
./paygles-env/bin/python -m uvicorn src.main:app --host 0.0.0.0 --port 8000
```

Frontend:
```bash
cd frontend
npm run dev
```

Frontend build:
```bash
cd frontend
npm run build
```

Ollama:
```bash
ollama serve
ollama pull qwen3.5:9b
```

---

## 13) Teşhis Checklist (Kısa)

1. Scheduler çalışıyor mu, `last_scrape_completed_at` güncelleniyor mu?
2. Site selector ve listing URL doğru mu?
3. Yeni kayıt DB’ye düşüyor mu (`scraped_topics`)?
4. `is_sticky`, `deleted_by_user`, `domain_skipped` nedeniyle gizleniyor olabilir mi?
5. `deal_title/deal_price` ikisi de boş olduğu için otomatik gönderim dışı kalmış olabilir mi?
6. Telegram token/chat ayarları doğru mu?
7. Ollama ayakta mı (`11434`), model yüklü mü?

---

## 14) Güvenlik / Operasyon Notu (Kısa)

- Bu proje şu an geliştirme odaklı; prod’da CORS, auth ve secret yönetimi sıkılaştırılmalı.
- `.env` içeriği paylaşılmamalı, token/şifreler gerektiğinde rotate edilmeli.

---

## 15) Zaman Notu

- Backend UTC-naive datetime tutuyor.
- Frontend bu değerleri local zamana çevirip relatif gösterim yapıyor.
