# paygles

## Source Management

Sources are managed from `backend/.env` using `TARGET_SITES_JSON`.

Example:

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

After editing `TARGET_SITES_JSON`, restart backend:

```bash
docker compose up -d --build backend
```
