-- Reel Inbox capture mailbox. Run once in the Supabase SQL editor.
--
-- The phone writes with the publishable (anon) key, which can only INSERT,
-- and only a well-formed Instagram or YouTube link. The laptop reads and
-- deletes with the secret (service-role) key, which bypasses RLS and is kept
-- in Windows Credential Manager. Rows live here only until the app pulls
-- them; the local SQLite store is the source of truth.

create table if not exists public.captures (
  id         uuid primary key default gen_random_uuid(),
  url        text not null,
  note       text,
  created_at timestamptz not null default now(),
  constraint captures_url_shape check (
    char_length(url) <= 500
    and url ~* '^https://([a-z0-9-]+\.)*(instagram\.com|youtube\.com|youtu\.be)/'
  ),
  constraint captures_note_length check (note is null or char_length(note) <= 500)
);

alter table public.captures enable row level security;

-- The anon role may insert the two user-facing columns and nothing else.
-- id and created_at always come from the defaults.
revoke all on public.captures from anon, authenticated;
grant insert (url, note) on public.captures to anon;

-- The laptop's secret key acts as service_role. Newer projects no longer
-- grant it table access by default, so pull would get 403 without this.
grant select, delete on public.captures to service_role;

drop policy if exists "shortcut inserts captures" on public.captures;
create policy "shortcut inserts captures"
  on public.captures
  for insert
  to anon
  with check (true);  -- the table constraints above do the validation

-- No select, update or delete policy exists for anon or authenticated, so
-- with RLS on, a leaked publishable key can add rows but never read them.
