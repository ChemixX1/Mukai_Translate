import base64
import hashlib
import html
import json
import logging
import os
import platform
import subprocess
import tempfile
from typing import Any

import requests
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from packaging import version
from PySide6.QtCore import QObject, QStandardPaths, QThread, Signal

from app.release_config import UPDATE_MANIFEST_URL, UPDATE_PUBLIC_KEY
from app.version import __version__


logger = logging.getLogger(__name__)


def canonical_manifest_payload(payload: dict[str, Any]) -> bytes:
    """Serialize a release payload exactly as the WordPress signer does."""
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def validate_release_manifest(data: dict[str, Any], public_key: str) -> dict[str, Any]:
    """Verify and normalize a signed release manifest from Mukai's server."""
    if not isinstance(data, dict):
        raise ValueError("The update server returned an invalid manifest.")

    signature = data.get("signature")
    algorithm = data.get("algorithm")
    payload = data.get("release")
    if algorithm != "RSA-SHA256" or not isinstance(signature, str) or not isinstance(payload, dict):
        raise ValueError("The update manifest is missing its signature.")

    try:
        key_bytes = base64.b64decode(public_key, validate=True)
        signature_bytes = base64.b64decode(signature, validate=True)
        key = serialization.load_pem_public_key(key_bytes)
        if not isinstance(key, rsa.RSAPublicKey) or key.key_size < 3072:
            raise ValueError("The update signing key is not strong enough.")
        key.verify(
            signature_bytes,
            canonical_manifest_payload(payload),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
    except (ValueError, TypeError, InvalidSignature) as exc:
        raise ValueError("The update manifest signature could not be verified.") from exc

    required_fields = ("version", "notes", "installer_url", "sha256", "published_at")
    if any(not isinstance(payload.get(field), str) or not payload[field].strip() for field in required_fields):
        raise ValueError("The signed update manifest is incomplete.")
    if not payload["installer_url"].startswith("https://"):
        raise ValueError("The update installer must use a secure HTTPS URL.")
    if len(payload["sha256"]) != 64 or any(char not in "0123456789abcdefABCDEF" for char in payload["sha256"]):
        raise ValueError("The update manifest contains an invalid installer checksum.")

    try:
        version.parse(payload["version"])
    except Exception as exc:
        raise ValueError("The update manifest contains an invalid version.") from exc

    return {
        "version": payload["version"].strip(),
        "notes": payload["notes"].strip(),
        "installer_url": payload["installer_url"].strip(),
        "sha256": payload["sha256"].lower(),
        "published_at": payload["published_at"].strip(),
    }


class UpdateChecker(QObject):
    """Checks Mukai's signed release feed and runs verified installers."""

    update_available = Signal(str, str, str, str)  # version, notes, URL, SHA-256
    up_to_date = Signal()
    error_occurred = Signal(str)
    download_progress = Signal(int)
    download_finished = Signal(str)  # file path

    def __init__(self):
        super().__init__()
        self._worker_thread = None
        self._worker = None

    @property
    def is_configured(self) -> bool:
        return bool(UPDATE_MANIFEST_URL.strip() and UPDATE_PUBLIC_KEY.strip())

    def _safe_stop_thread(self):
        try:
            if self._worker_thread and self._worker_thread.isRunning():
                self._worker_thread.quit()
                self._worker_thread.wait()
        except RuntimeError:
            pass
        except Exception as exc:
            logger.error("Error stopping update worker: %s", exc)
        self._worker_thread = None

    def check_for_updates(self):
        """Start the signed-feed check in a background thread."""
        if not self.is_configured:
            self.error_occurred.emit("The Mukai update channel has not been configured for this edition yet.")
            return

        self._safe_stop_thread()
        self._worker_thread = QThread()
        self._worker = UpdateWorker(UPDATE_MANIFEST_URL, UPDATE_PUBLIC_KEY, __version__)
        self._worker.moveToThread(self._worker_thread)

        self._worker.finished.connect(self._worker_thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker_thread.finished.connect(self._worker_thread.deleteLater)
        self._worker.update_available.connect(self.update_available)
        self._worker.up_to_date.connect(self.up_to_date)
        self._worker.error.connect(self.error_occurred)
        self._worker_thread.started.connect(self._worker.run)
        self._worker_thread.start()

    def download_installer(self, url: str, filename: str, checksum: str):
        """Download an installer and verify its SHA-256 in a worker thread."""
        self._safe_stop_thread()
        self._worker_thread = QThread()
        self._worker = DownloadWorker(url, filename, checksum)
        self._worker.moveToThread(self._worker_thread)

        self._worker.finished.connect(self._worker_thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker_thread.finished.connect(self._worker_thread.deleteLater)
        self._worker.progress.connect(self.download_progress)
        self._worker.finished_path.connect(self.download_finished)
        self._worker.error.connect(self.error_occurred)
        self._worker_thread.started.connect(self._worker.run)
        self._worker_thread.start()

    def run_installer(self, file_path: str):
        try:
            system = platform.system()
            if system == "Windows":
                os.startfile(file_path)
            elif system == "Darwin":
                subprocess.Popen(["open", file_path])
        except Exception as exc:
            self.error_occurred.emit(f"Failed to launch installer: {exc}")

    def shutdown(self):
        self._safe_stop_thread()
        self._worker_thread = None
        self._worker = None


class UpdateWorker(QObject):
    update_available = Signal(str, str, str, str)
    up_to_date = Signal()
    error = Signal(str)
    finished = Signal()

    def __init__(self, manifest_url: str, public_key: str, current_version: str):
        super().__init__()
        self.manifest_url = manifest_url
        self.public_key = public_key
        self.current_version = current_version

    def run(self):
        try:
            response = requests.get(
                self.manifest_url,
                timeout=10,
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
            release = validate_release_manifest(response.json(), self.public_key)
            if version.parse(release["version"]) > version.parse(self.current_version):
                self.update_available.emit(
                    release["version"],
                    release["notes"],
                    release["installer_url"],
                    release["sha256"],
                )
            else:
                self.up_to_date.emit()
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            self.finished.emit()


class DownloadWorker(QObject):
    progress = Signal(int)
    finished_path = Signal(str)
    error = Signal(str)
    finished = Signal()

    def __init__(self, url: str, filename: str, checksum: str):
        super().__init__()
        self.url = url
        self.filename = filename
        self.checksum = checksum.lower()

    def run(self):
        save_path = ""
        try:
            download_dir = QStandardPaths.writableLocation(QStandardPaths.DownloadLocation)
            if not download_dir:
                download_dir = os.path.join(os.path.expanduser("~"), "Downloads")
            if not os.path.exists(download_dir):
                download_dir = tempfile.gettempdir()

            safe_filename = os.path.basename(self.filename) or "MukaiTranslator-Setup.exe"
            save_path = os.path.join(download_dir, safe_filename)
            digest = hashlib.sha256()
            response = requests.get(self.url, stream=True, timeout=30)
            response.raise_for_status()
            total_size = int(response.headers.get("content-length", 0))
            downloaded_size = 0

            with open(save_path, "wb") as file_handle:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        file_handle.write(chunk)
                        digest.update(chunk)
                        downloaded_size += len(chunk)
                        if total_size > 0:
                            self.progress.emit(int((downloaded_size / total_size) * 100))

            if digest.hexdigest() != self.checksum:
                os.remove(save_path)
                raise ValueError("The downloaded installer failed its security check.")

            self.finished_path.emit(save_path)
        except Exception as exc:
            if save_path and os.path.exists(save_path):
                try:
                    os.remove(save_path)
                except OSError:
                    pass
            self.error.emit(str(exc))
        finally:
            self.finished.emit()


def release_notes_to_html(notes: str) -> str:
    """Render untrusted plain-text notes safely in the Qt update dialog."""
    return html.escape(notes).replace("\n", "<br>")
