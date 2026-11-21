# Capturing reels from the phone

An iOS Shortcut posts `{url, note}` to a Supabase table. The Learning OS app pulls waiting rows into its local store each time it starts, or when you click Process now, and then deletes them from Supabase. No key is stored in this repository.

## 1. Supabase (once)

1. Create a free Supabase project.
2. Open **SQL Editor**, paste [`supabase.sql`](supabase.sql) and run it. That creates the `captures` table with row-level security: the publishable key can **insert** an Instagram or YouTube link and nothing else, so it can't read, change or delete rows.
3. Open **Project Settings → API Keys** and note:
   - the **Project URL**, for example `https://abcd1234.supabase.co`;
   - the **publishable** key (formerly *anon*), which goes into the Shortcut;
   - the **secret** key (formerly *service_role*), which goes into Windows Credential Manager only (step 3).

## 2. The iOS Shortcut

Create a new Shortcut named **Save to Reel Inbox** and add these actions in order.

1. **Receive** *URLs* and *Text* **input from** *Share Sheet*. *If there's no input:* **Ask For** *URLs*.
   (Shortcut settings → **Show in Share Sheet** on.)
2. **Ask for Input**: type *Text*, prompt `Note (optional)`, *Allow Multiple Lines* off. Leave it empty to skip the note.
3. **Get Contents of URL**
   - URL: `https://<your-project>.supabase.co/rest/v1/captures`
   - Method: **POST**
   - Headers:
     - `apikey`: *your publishable key*
     - `Content-Type`: `application/json`
     - `Prefer`: `return=minimal`
   - Request Body: **JSON**
     - `url` (Text): *Shortcut Input*
     - `note` (Text): *Provided Input*
4. **Show Notification**: `Saved to Reel Inbox`.

To use it, tap **Share** on a reel in Instagram, then **Save to Reel Inbox**. `Prefer: return=minimal` is required: the publishable key isn't allowed to read the row back. Don't add an `Authorization: Bearer` header with an `sb_publishable_` key: Supabase drops the request and the Shortcut reports "The network connection was lost". Only a legacy `eyJ…` anon key goes there as well.

The publishable key in the Shortcut can only add Instagram or YouTube links to the table. If it leaks, someone can fill your inbox but not read it.

## 3. The laptop (once)

Store the project URL and the secret key in Windows Credential Manager:

```bash
uv run python -m reel_inbox set-secret supabase-url
uv run python -m reel_inbox set-secret supabase-key
```

Each command prompts for the value without echoing it. To check:

```bash
uv run python -m reel_inbox pull
```

## Replacing Supabase

The app reads captures through `reel_inbox.sources.CaptureSource`: `pull()` returns waiting captures and `ack(ids)` removes them. A Telegram bot, or anything else that can list and delete messages, can replace Supabase by implementing those two methods.
