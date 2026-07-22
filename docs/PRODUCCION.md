# Producción y distribución de Mukai Translator

## Qué archivo usar

### Desarrollo local

Abre `MukaiTranslator-Developer.exe` desde la raíz del proyecto. Este lanzador ejecuta directamente el código actual mediante `.venv`, por lo que los cambios en archivos Python se aplican al siguiente inicio sin reinstalar ni recompilar.

La configuración inicial solo se repite cuando cambia Python o `requirements*.txt`:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tools\setup_development.ps1
```

El lanzador de desarrollo y la carpeta completa del proyecto no se entregan a clientes.

### Usuarios finales

Comparte únicamente:

```text
releases\<versión>\MukaiTranslator-Setup-<versión>.exe
```

Ese instalador incluye el programa y sus dependencias de escritorio, registra el icono y los proyectos `.mtpr`, conserva la instalación anterior al actualizar y activa el sistema de licencia. Los modelos grandes se validan y descargan automáticamente en el perfil local del usuario cuando son necesarios.

La alternativa sin instalación es:

```text
releases\<versión>\MukaiTranslator-Portable-<versión>.zip
```

Para clientes se recomienda el instalador. La versión portátil se conserva para pruebas, soporte técnico o uso controlado.

## Cuándo se solicita la licencia

La ventana **Activar Mukai Translator** aparece al abrir por primera vez el EXE instalado o la versión portátil, antes de la pantalla de carga y antes de iniciar los motores. El usuario introduce allí el código de 25 caracteres y pulsa **Activar**. Si el servidor acepta el código, el certificado firmado queda vinculado a ese equipo y la aplicación continúa abriéndose.

En los inicios siguientes el programa valida el certificado guardado automáticamente. Si el servidor no está disponible, permite hasta tres días de uso sin conexión desde la última validación correcta. Al vencer o revocarse la licencia vuelve a aparecer la ventana de activación.

`MukaiTranslator-Developer.exe` no muestra esa ventana: el lanzador de desarrollo ejecuta el código fuente y omite intencionalmente el bloqueo. Para probar el flujo desde desarrollo se puede iniciar con la variable `MUKAI_FORCE_LICENSE=1`.

## Crear una versión comprobada

1. Cambia `app/version.py` a una versión superior.
2. Ejecuta:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tools\build_windows_release.ps1 -Installer
```

3. El proceso valida el código, genera la carpeta portátil, comprueba el EXE congelado, crea el instalador y escribe las huellas SHA-256 en:

```text
releases\<versión>\release-manifest.json
```

No distribuyas un instalador si cualquiera de las comprobaciones falla.

Para una validación profunda de los motores locales antes de etiquetar una versión, ejecuta:

```powershell
.venv\Scripts\python.exe tools\smoke_test_engines.py
```

La prueba carga y ejecuta RT-DETR, Manga OCR, Pororo, las cinco variantes PP-OCR, LaMa, AOT y MI-GAN en CPU. Los modelos que todavía no estén presentes se descargan desde sus fuentes HTTPS registradas y se validan mediante su huella.

La deformación de texto conserva el contenido editable y ofrece los 15 estilos
nativos compatibles con Photoshop. Su composición se genera a resolución
adaptativa (4× a 8×) y se remuestrea con OpenCV/Lanczos; si una instalación de
Windows no puede cargar el módulo nativo, el programa conserva un respaldo
NumPy para no impedir el inicio.

La sección **3D y perspectiva** añade diez ajustes editables de perspectiva por
cuatro esquinas, expansión de extremos, diagonales, trapecio y extrusión. Se
puede combinar con degradados, resplandor, bisel y las deformaciones de texto;
el proyecto conserva los parámetros y el render final usa el mismo muestreo
OpenCV/Lanczos de alta resolución.

## GitHub y WordPress

El workflow `.github/workflows/release-windows.yml` se ejecuta al subir una etiqueta `vX.Y.Z`. La etiqueta debe coincidir exactamente con `app/version.py`. GitHub compila Windows, ejecuta las comprobaciones y crea un GitHub Release con:

- instalador;
- versión portátil;
- manifiesto y huellas SHA-256.

WordPress consulta el último GitHub Release cada cuatro horas. Cuando detecta una versión superior, muestra un aviso privado en `/wp-admin`. Desde **Mukai Control → Actualizaciones** se revisan los datos y se publica manualmente el manifiesto firmado para los programas instalados.

WordPress nunca publica automáticamente una versión de GitHub: se requiere confirmación del administrador.

## Firma de Windows

Los paquetes se construyen con icono y metadatos de versión, pero para distribución comercial conviene firmar tanto `MukaiTranslate.exe` como el instalador con un certificado de firma de código válido. Sin esa firma Windows SmartScreen puede mostrar una advertencia de editor desconocido aunque la huella SHA-256 sea correcta.

## Archivos que no se comparten

- raíz completa del proyecto;
- `.venv`, `build`, `dist` o código fuente;
- `MukaiTranslator-Developer.exe`;
- archivo `env` o credenciales de proveedores;
- acceso SSH, contraseñas de WordPress o clave RSA privada;
- plugin de WordPress junto con el instalador del cliente.

La clave pública RSA y el endpoint HTTPS sí están incorporados en el programa porque se utilizan únicamente para verificar firmas y licencias.
