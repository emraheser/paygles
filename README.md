# Paygles

Paygles, forum ve Telegram kaynaklarını tarayıp fırsatları veritabanına kaydeden, dashboard'da gösteren ve kurallara uyan kayıtları Telegram kanalına gönderen bir takip sistemidir.

Bu README, proje için tek bakışta durum + operasyon + handover kaydıdır.

## Son Durum (2026-08-05)

- DonanımHaber thread akışı captcha fallback ile güçlendirildi.
- Deal link ayıklama kuralları sıkılaştırıldı (sosyal/app/internal linkler filtreleniyor).
- Dashboard API tarafında `domain_skipped` ve kullanılabilir link filtresi netleştirildi.
- Notifier fiyat çıkarımı Amazon/Vatan ve kampanya sayfaları için iyileştirildi.
- Tracked product fiyat kontrolüne anomali/plausibility guard eklendi.
- Dashboard UI kart akışından daha okunabilir tablo görünümüne geçirildi.

## Yayınlama Politikası

Her yaptığımız değişiklik otomatik olarak siteye/publishe gitmemeli.

Kural:
1. Kod ve testler tamamlanır.
2. Değişiklik özeti hazırlanır.
3. Yayına/deploy'a çıkmadan önce senden onay alınır.

Not: Bu repo için varsayılan çalışma şekli "önce doğrulama, sonra senden onay, sonra publish" olmalıdır.

## Mimari Özet

- Backend: FastAPI + SQLAlchemy Async + APScheduler
- Frontend: React + Vite + Tailwind + shadcn/ui
- DB: PostgreSQL (docker compose ile)

Kritik backend dosyaları:
- `backend/src/services/scraper.py`
- `backend/src/services/notifier.py`
- `backend/src/services/scheduler.py`
- `backend/src/api/dashboard.py`

Kritik frontend dosyası:
- `frontend/src/pages/Dashboard.tsx`

## Çalışma Akışı

Scheduler turunda sıralama:
1. Aktif web kaynaklarını scrape et
2. Telegram kaynaklarını oku
3. Bildirim uygunluğunu kontrol et ve gönder
4. Sync durumunu güncelle

## Dashboard Davranışı

- Kaynak bazlı filtreleme var.
- Yeni/eski kayıt ayrımı var.
- Silme soft-delete (`deleted_by_user = true`) şeklinde çalışır.
- Manuel gönderim diyalogu ile başlık/link düzenlenebilir.

## Source Management

Kaynaklar `backend/.env` içindeki `TARGET_SITES_JSON` ile yönetilir.

Örnek:

```env
TARGET_SITES_JSON='[
	{
		"name": "Donanim Arsivi",
		"url": "https://forum.example.com/forumlar/sicakfirsatlar",
		"source_type": "web",
		"topic_list_selector": ".structItem--thread",
		"title_selector": ".structItem-title a",
		"link_selector": ".structItem-title a",
		"date_selector": ".structItem-startDate time",
		"is_active": true
	},
	{
		"name": "Amazon Kanal",
		"url": "https://t.me/kanal",
		"source_type": "telegram",
		"is_active": true
	},
	{
		"name": "Donanim Haber",
		"url": "https://forum.donanimhaber.com/...--135048063?fetch_last=20",
		"source_type": "donanimhaber_thread",
		"is_active": true
	}
]'
```

Değişiklik sonrası backend yeniden başlat:

```bash
docker compose up -d --build backend
```

## Hızlı Çalıştırma

Tüm servisler:

```bash
docker compose up -d --build
```

Log kontrolü:

```bash
docker compose logs -f backend
docker compose logs -f frontend
```

Sağlık kontrolü:

```bash
curl http://localhost:8000/health
```

## Test ve Doğrulama

Backend örnek test komutları:

```bash
cd backend
python -m unittest -q test_scraper_donanimhaber.py
python -m unittest -q test_product_tracker.py
python -m unittest -q test_notifier_price_extraction.py
```

Frontend build:

```bash
cd frontend
npm run build
```

Not: Frontend build sırasında ortam Node sürüm uyarısı alınırsa Node 20.19+ önerilir.

## Yeni Chat'te Buradan Devam

Yeni bir sohbette hızlı devam etmek için aşağıdaki bilgileri paylaş:

1. Bu README'nin "Son Durum" bölümünü referans al.
2. En son odak: dashboard tablo UX + backend veri doğruluk temizliği.
3. Kalan işler:
   - `backend/test_notifier_price_extraction.py` dosyasındaki girinti/sözdizimi hatasını düzelt ve testi tekrar geçir.
   - Son 7 gün verisinde yanlış/eski kayıtlar için DB düzeltmelerini finalize et.
   - Dashboard tablosunda mobil kullanım ince ayarı gerekiyorsa tamamla.
4. Deploy/publish adımı için kullanıcı onayı bekle.

## Operasyon Notu

- `.env` içeriğini repoya koyma.
- Token/secret değerleri log veya chat içinde paylaşılmamalı.
- `__pycache__` ve `.pyc` dosyaları repoya dahil edilmemeli.
