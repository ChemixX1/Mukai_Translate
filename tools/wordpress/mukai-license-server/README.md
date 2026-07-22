# Mukai License Server for WordPress

1. Zip the `mukai-license-server` folder and upload it in **WordPress -> Plugins -> Add New -> Upload Plugin**.
2. Activate it. The server must have the PHP OpenSSL extension enabled.
3. Open **Mukai Control** in the private WordPress administration menu.
4. Use **Licencias** to generate up to 50 codes at once, search and filter them, revoke or reactivate access, extend validity, and release registered devices.
5. Use **Actualizaciones** to publish the signed update manifest and **Conexión y seguridad** to consult the endpoint and public key.

The plugin does not create a public WordPress page. Its control panel is available only in `/wp-admin` to users with the `manage_options` capability.

## GitHub release notifications

The plugin checks the public `ChemixX1/Mukai-Translator` GitHub repository every four hours. A newer GitHub Release produces a private WordPress admin notice. The administrator must review the imported version, installer URL, SHA-256 digest, and release notes before signing and publishing it to desktop clients.

The GitHub Release must include an asset named `MukaiTranslator-Setup-<version>.exe`. WordPress reads the SHA-256 digest returned by GitHub's release API; source-code commits and tags without a published release are intentionally ignored.

The plugin stores only a password hash of each activation code. It stores a 3072-bit RSA private signing key in WordPress options and must never be exported or shared. The desktop app embeds only the public key and verifies every license and update response with RSA-SHA256.

## Publishing an application update

1. Increase `__version__` in `app/version.py`.
2. Run `tools\build_windows_release.ps1 -Installer`. It prints the installer path and its SHA-256 hash.
3. Upload that single `.exe` installer to a stable HTTPS URL on Hostinger, for example `https://your-domain.com/downloads/MukaiTranslator-Setup-1.0.1.exe`.
4. In **Mukai Control -> Actualizaciones**, paste the version, HTTPS URL, SHA-256, and concise release notes, then publish.

At startup, Mukai compares only against this signed release record. When a newer version exists, it shows the release notes before downloading anything. The installer is downloaded only after the user accepts and its SHA-256 is verified before it can be opened. The installer uses a fixed Inno Setup `AppId`, so it upgrades the existing installation instead of requiring users to receive a folder.

Before making the first customer installer, set these public values in `app/release_config.py` and rebuild it:

- `UPDATE_MANIFEST_URL`: `https://your-domain.com/wp-json/mukai-license/v1/update`
- `UPDATE_PUBLIC_KEY`: the value shown by the plugin in **Mukai Control -> Conexión y seguridad**.

Never put a WordPress password, private signing key, or Hostinger credential into `release_config.py`.

Endpoints:

- `POST /wp-json/mukai-license/v1/activate`
- `POST /wp-json/mukai-license/v1/validate`
- `GET /wp-json/mukai-license/v1/public-key`
- `GET /wp-json/mukai-license/v1/update`
