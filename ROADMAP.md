# Ahad Co — Feature Roadmap

A living list of data-save features that can be added next. Each one follows
the existing pattern (one table in `database.py` + a CRUD section in `app.py` +
a dashboard tab in `index.html` / `pro.js`), so any of them can be shipped in a
focused session.

## ✅ Already shipped
- **Vault** — passwords, codes, secrets
- **Cards** — payment cards (masked, reveal, copy, auto brand detection)
- **Notes & diary** — colour-coded notes
- **Bookmarks** — categorised links
- **Tasks** — lightweight to-do with priorities
- **2FA** — TOTP + backup codes
- **Activity log** — live session + security events
- **Login history** — server-side login trail
- **Data export** — full JSON download
- **API keys** — developer access tokens

## 🔜 High-value next features

### 1. Encrypted notes / secrets (client-side AES)
Store secrets **encrypted in the browser** with a master passphrase, so even the
server can't read them. Uses the Web Crypto API (AES-GCM). This is the single
biggest security upgrade — your data becomes truly zero-knowledge.

### 2. Identities
Structured identity records: passport, national ID, driver's licence, address.
Reuses the Cards pattern (typed fields, masked, reveal/copy).

### 3. Secure share links (one-time secrets)
Generate a one-time, expiring link (`/s/<token>`) that reveals a secret once,
then deletes itself. Great for sharing a password with someone safely.

### 4. Documents / encrypted file storage
Upload small files (PDFs, photos of documents), stored as base64 or object
storage (Supabase Storage / S3). With client-side encryption for privacy.

### 5. Recovery phrases (crypto seed vault)
Specialised storage for 12/24-word seed phrases, with a word-count validator
and never-displayed-by-default masking.

### 6. SSH / server credentials
Structured store for host + username + key/password + port, with one-click copy
and a `ssh://` launch helper.

### 7. WiFi passwords vault
SSID + password, grouped by location, QR-code generation for instant sharing
to a phone.

### 8. Calendar / reminders
Date-based reminders on top of tasks, with optional email notifications via
Brevo (already integrated).

### 9. Contacts / address book
Names, emails, phones, addresses — exportable to vCard.

### 10. Trash / undo (soft delete)
Soft-delete deleted items for 30 days with a restore option, so an accidental
delete is never permanent.

## 🎨 UX ideas
- **Command palette** (Cmd/Ctrl+K) to jump between vault items — very Linear.
- **Global search** across vault, notes, bookmarks, cards.
- **Pinned / favourite** items on the overview screen.
- **Biometric unlock** (WebAuthn / FaceID) on supported devices.
- **Offline-first** with a service worker + background sync.
- **Theming** — light mode + accent colour picker (the toggle already exists in
  the schema via `user_preferences.theme`).

## 🏗️ Suggested order
1. **Encrypted secrets** (biggest security win)
2. **Trash / undo** (safety net, low effort)
3. **Global search + command palette** (big perceived-polish win)
4. **Identities / WiFi / SSH** (more vault types, high practical value)
5. **Secure share links** (network-effect feature)
