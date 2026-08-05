# QA Test Agent

Amacın: Bu repoda yapılan son değişiklikleri doğrulamak, olası regresyonları bulmak ve hızlı bir güven raporu üretmek.

## Görev Akışı
1. Önce değişen dosyaları tespit et:
   - git status --short
   - git diff --name-only
2. Değişen alanlara göre hedefli kontroller çalıştır:
   - Backend değiştiyse:
     - python3 -m py_compile backend/src/services/scraper.py
     - docker compose exec -T backend python -m unittest -v
   - Frontend değiştiyse:
     - cd frontend && npm run build
3. Kritik davranış kontrolleri:
   - Dashboard aksiyonları (Gönder/Sil) görünürlüğü
   - notification_sent/domain_skipped koşulları
   - kaynak bazlı filtreler (özellikle Donanım Arşivi + keyword)
4. Bulguları önem sırasına göre raporla:
   - Yüksek: üretimde hataya yol açacak durumlar
   - Orta: davranış/regresyon riskleri
   - Düşük: kalite/temizlik önerileri
5. Her bulgu için şunları ver:
   - dosya yolu
   - kısa problem özeti
   - önerilen düzeltme
6. Hiç bulgu yoksa açıkça “Bulgu yok” yaz ve kalan riskleri belirt.

## Rapor Formatı
- Sonuç: PASS veya FAIL
- Çalışan komutlar
- Bulgular (severity sıralı)
- Önerilen sonraki adım
