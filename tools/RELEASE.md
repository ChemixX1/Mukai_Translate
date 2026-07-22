# Publicar Mukai Translator

Este flujo entrega a cada cliente solo un instalador inicial. Las versiones posteriores se detectan dentro de Mukai; el usuario ve las novedades antes de aceptar la descarga.

## Preparacion unica

1. Instala y activa `tools/wordpress/mukai-license-server.zip` en WordPress.
2. Copia la clave publica de **Mukai Licenses** a `app/release_config.py`.
3. En el mismo archivo, configura `UPDATE_MANIFEST_URL` con la URL `https://TU-DOMINIO/wp-json/mukai-license/v1/update`.

## Publicar desde la computadora de desarrollo

El canal de `mangamukai.com` ya está configurado en esta edición. Para construir,
subir el instalador a la carpeta aislada `mukai-updates` y publicar el manifiesto
firmado en WordPress, ejecuta:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\publish_windows_update.ps1 `
  -ReleaseNotes "Describe aquí las mejoras de esta versión"
```

La contraseña SSH se solicita de forma interactiva y nunca se guarda dentro del
proyecto. Usa `-SkipBuild` si el instalador de la versión actual ya fue generado.
4. Ejecuta `tools\build_windows_release.ps1 -Installer` y publica ese instalador inicial.
5. En **Mukai Licenses**, publica la version inicial con la URL HTTPS y el SHA-256 impresos por el script.

No uses el aviso del repositorio original de Comic Translate: Mukai ya no consulta ese repositorio.

## Cada nueva version

1. Cambia `app/version.py`, por ejemplo de `1.0.0` a `1.0.1`.
2. Ejecuta desde PowerShell en la raiz del proyecto:

   ```powershell
   .\tools\build_windows_release.ps1 -Installer
   ```

3. Sube el archivo indicado a Hostinger mediante SFTP o el administrador de archivos. Conserva una URL HTTPS permanente; no reemplaces un instalador ya publicado.
4. En WordPress, abre **Mukai Licenses** y publica la nueva version con la URL, el SHA-256 y las notas de cambios.

Los clientes reciben un aviso en el siguiente inicio. Al aceptar, Mukai descarga el instalador, verifica el hash firmado y abre el instalador de actualizacion.

## Seguridad

El manifiesto de actualizacion se firma en WordPress con Ed25519. La aplicacion rechaza manifiestos sin firma valida, enlaces no HTTPS e instaladores cuyo SHA-256 no coincida. La clave privada permanece exclusivamente en WordPress.
