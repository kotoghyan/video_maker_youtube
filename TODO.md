# TODO проекта

## Актуальный статус — 11.10.2026

- [x] Опубликованы три оставшихся произведения по новым правилам, пакет remaining-review-v2. Пользователь утвердил версии командой «го». Все три: Public, не для детей, processed/succeeded; тексты и длительности проверены через API.
  - Ankin Yars — https://www.youtube.com/watch?v=3y6-hqHzGK4 (2:48).
  - Tou Im Hbared Hayaghechik — https://www.youtube.com/watch?v=zorw2QYYzyU (3:13).
  - Im Hayreni Zanghezour — https://www.youtube.com/watch?v=S3OcpqXqfYI (4:14).
- [ ] Выяснить причину недоступности полного альбома Fka4O_X-kjc в Studio: videos.list пуст, uploads playlist показывает Deleted video. Повторно не загружать без отдельного решения.
- [ ] Проверить доступ к custom thumbnails и вручную установить обложки: для трёх новых видео API вновь вернул HTTP 403 forbidden.
- Теперь подтверждены 12 публичных отдельных произведений. Неотправленных отдельных треков нет.
- Пакет, утверждение и результаты: C:\Users\gjano\OneDrive\Desktop\Vinyl_Social_Media\353\both\remaining-review-v2 . Общий JSON-журнал обновлён. Прежний пакет, тексты, видео и музейный архив не изменены. Предыдущее защищённое состояние сохранено отдельной DPAPI-записью вне OneDrive; все известные video ID сохранены для защиты от дублей.

## Исторический статус остановки 10.10.2026

Сведения ниже сохранены для истории; три указанные там неотправленные публикации уже завершены.

## Поручения пользователя, перенесённые в TODO

- [ ] **Продолжить публикацию пластинки 353, пакет youtube-review-v1.** По просьбе пользователя остановлено 10.10.2026; продолжать только по его новой команде. Автоматика, расписание и фоновые процессы не созданы.

### Проверенный статус

- YouTube-канал: Karapet Kotoghyan / @karapetkotoghyan / UClW8s5cIHaqw5wtrQnSQmHA.
- Передано и получено YouTube: **10 из 13 видео**. Финально подтверждены **9 обработанных публичных отдельных произведений**. Полную пластинку нельзя считать успешно опубликованной: её ID сейчас отсутствует в videos.list.
- Все 19 архивных файлов повторно проверены по размеру, времени и SHA-256: без изменений.
- Утверждены все 13 материалов точного пакета, **Public**, **selfDeclaredMadeForKids=false**, права подтверждены. Повторно согласовывать неизменные файлы/тексты и эти параметры не нужно. Изменение пакета аннулирует его хеш.
- Параметры и пользовательские ответы сохранены в youtube-public-approval-v1.json. Для загрузки требуются пакет и этот файл утверждения.
- Последние тесты: 87, OK. Реальный dry-run публикации пройден до первой загрузки.

### Блокер и время

- 11-я загрузка (Ankin Yars) остановлена до передачи медиа: **HTTP 400 uploadLimitExceeded**.
- Точное время: 2026-10-10T12:16:12.884726+00:00; время Еревана: 2026-10-10T16:16:12.884726+04:00.
- Ориентир новой попытки через 24 часа: 2026-10-11T16:16:12.884726+04:00. Это ориентир, **не обещание точного сброса**. До новой команды пользователя ничего автоматически не отправлять.
- Google рекомендует повторить попытку через 24 часа: https://support.google.com/youtube/answer/10383400?hl=ru .

### Три неотправленных материала

1. works/D01_B04 — Ankin Yars.
2. works/D01_B05 — Tou Im Hbared Hayaghechik.
3. works/D01_B06 — Im Hayreni Zanghezour.

### Проверка альбома и обложек

- Полная пластинка 40:18: полученный ID **Fka4O_X-kjc**. Первоначально API возвращал public/uploaded/processing. Последняя videos.list не возвращает этот ID. Запрос статуса прежней resumable-сессии вернул тот же ID и первоначальный статус uploaded/public; это **не доказательство завершённой обработки или доступности**.
- Канал вернул **longUploadsStatus=eligible**, а не allowed: владелец должен включить загрузку видео длиннее 15 минут через подтверждение телефона. Документация: https://developers.google.com/youtube/v3/docs/channels#status.longUploadsStatus .
- Ограничение длинных видео — вероятная причина проблемы альбома, но причина его исчезновения из API **не установлена**. Владелец должен проверить карточку альбома в Studio и сообщить показанный статус/причину. Не создавать новый экземпляр и не удалять старый автоматически.
- Установка утверждённой thumbnail.jpg получила **HTTP 403 forbidden** для всех 10 отправленных видео. Подтверждены нужные OAuth scopes; доступ к custom thumbnails на канале нужно проверить в Studio → Настройки → Канал → Доступность функций. Не считать подготовленную миниатюру установленной.
- По правилам проекта уже опубликованное не редактировать без отдельного решения пользователя; TODO не даёт разрешения менять обложки опубликованных видео. Подготовленный файл можно дать владельцу для ручной установки.
- Видео и обложки сохраняются локально. Никакие временные файлы или финалы не удалялись.

### Уже подтверждённые публикации

- works/D01_A01 — [Sirelis](https://www.youtube.com/watch?v=NX1tPzXXUvc) — NX1tPzXXUvc; Public, не для детей, processed/succeeded.
- works/D01_A02 — [Knarakan Zougerk](https://www.youtube.com/watch?v=633cah-btwI) — 633cah-btwI; Public, не для детей, processed/succeeded.
- works/D01_A03 — [Tou Im Moussanes](https://www.youtube.com/watch?v=ArxLgcgBxiM) — ArxLgcgBxiM; Public, не для детей, processed/succeeded.
- works/D01_A04 — [Zour Kertas](https://www.youtube.com/watch?v=87bPOJbPjFc) — 87bPOJbPjFc; Public, не для детей, processed/succeeded.
- works/D01_A05 — [En Ko Serne Yar](https://www.youtube.com/watch?v=dRW02EqJsjo) — dRW02EqJsjo; Public, не для детей, processed/succeeded.
- works/D01_A06 — [Arevachogh Hayasdan](https://www.youtube.com/watch?v=GvML-KdcPa4) — GvML-KdcPa4; Public, не для детей, processed/succeeded.
- works/D01_B01 — [Bardezoum Varde Patzvouel](https://www.youtube.com/watch?v=f9rBBOUK7H4) — f9rBBOUK7H4; Public, не для детей, processed/succeeded.
- works/D01_B02 — [Mi Balas](https://www.youtube.com/watch?v=5PODKmhc03s) — 5PODKmhc03s; Public, не для детей, processed/succeeded.
- works/D01_B03 — [Tou Intz Hamar](https://www.youtube.com/watch?v=QjOod0-sbx0) — QjOod0-sbx0; Public, не для детей, processed/succeeded.

### Файлы и безопасное продолжение

- Пакет: C:\Users\gjano\OneDrive\Desktop\Vinyl_Social_Media\353\both\draft-v1\youtube-public-review-v1.json
- Утверждение: C:\Users\gjano\OneDrive\Desktop\Vinyl_Social_Media\353\both\draft-v1\youtube-public-approval-v1.json
- Результаты каждого видео: C:\Users\gjano\OneDrive\Desktop\Vinyl_Social_Media\353\both\draft-v1\youtube-publication-results-v1.json
- JSON-журнал: C:\Users\gjano\OneDrive\Desktop\Vinyl_Social_Media\353\journal.json
- Рабочее состояние: C:\Users\gjano\OneDrive\Desktop\Vinyl_Social_Media\353\both\draft-v1\state.json
- Обложка: C:\Users\gjano\OneDrive\Desktop\Vinyl_Social_Media\353\both\draft-v1\thumbnail.jpg
- Код: vinyl_codex/youtube_publish.py; CLI: youtube-upload (по умолчанию dry-run), youtube-upload-verify.
- URI resumable-сессий и OAuth-токены только в Windows DPAPI вне OneDrive; не копировать и не выводить их в чат/журнал.
- Сначала читать AGENTS.md, CODEX_MASTER_PLAN.md и этот TODO. Проверить журнал, SHA-256 пакета/материалов, текущий OAuth-канал, API videos.list и uploads playlist.
- Пропустить известные video ID: ни одно из 10 принятых видео повторно не вставлять. Обрабатывать три оставшихся по первоначальному утверждению после снятия лимита и команды пользователя.
- Важно: текущая команда youtube-upload проверяет каждый уже известный video ID и остановится на недоступном ID альбома. Не обходить это созданием новой загрузки. Сначала разрешить неопределённость альбома; при необходимости доработать безопасное продолжение с сохранением известного ID и отдельным статусом unresolved.
- Защищённая запись works/D01_B04 имеет phase=blocked_before_media, error_reason=uploadLimitExceeded, без URI и video ID; media для трёх оставшихся не передавалось.
- Проверить окончательную длительность и обработку альбома и трёх будущих видео; для 9 публикаций они уже подтверждены. Лимиты платформы не обходить.
