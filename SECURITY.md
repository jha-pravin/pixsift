# Security

PixSift handles private pictures and face data, so it is built to keep both on your computer.

## Design

- **Local only.** The engine listens on `127.0.0.1` only. Requests with any other `Host` header are refused,
  which blocks DNS-rebinding attacks.
- **Access token.** Every launch creates a random token. The desktop app passes it to its own window; browser
  mode prints a `/?token=…` link. The token is kept in an HTTP-only, `SameSite=Strict` cookie, and every API
  request needs it. Other programs, other user accounts and web pages can't read your library without it.
- **No cross-site requests.** Browser requests that aren't same-origin (`Sec-Fetch-Site`) are refused, so other
  websites can't embed your pictures or plant a token. Every action also needs an `X-PixSift` header, which
  cross-origin pages can't send.
- **Files are served by id.** The API never accepts a file path for reading, so path traversal isn't possible.
  Scan folders are chosen by you.
- **Originals are safe.** Edits are saved as new copies by default. "Replace original" asks you to confirm and
  keeps a backup in the data folder.
- **Verified models.** The AI models are downloaded over HTTPS once, and each file is checked against a
  SHA-256 hash pinned in the source (`backend/pixsift/models.py`). Nothing else is downloaded, and no
  pictures, faces or usage data are ever sent anywhere.
- **Private data folder.** The library (database, thumbnails, face crops, backups) is created owner-only
  (`0700` on macOS/Linux).

## Known limits

- The library isn't encrypted at rest. Anyone with access to your user account, or to a backup of it, can read
  it. Use FileVault or BitLocker.
- Builds are unsigned for now. Only download releases from this repository.
- Image decoding relies on Pillow and libheif. Keep PixSift updated to get their security fixes.

## Reporting a vulnerability

Please report security issues privately through GitHub's **Security → Report a vulnerability** on this
repository rather than in a public issue. Include the steps to reproduce it.
