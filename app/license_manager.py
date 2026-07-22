"""Signed first-run licensing for distributed Mukai Translator builds."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import platform
import re
import socket
import sys
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import requests
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from PySide6 import QtCore, QtGui, QtWidgets

from app.account.auth.token_storage import delete_token, get_token, set_token
from app.release_config import LICENSE_API_BASE, UPDATE_PUBLIC_KEY


_CERTIFICATE_TOKEN = "mukai_license_certificate_v1"
_OFFLINE_GRACE = timedelta(days=3)


def _canonical_payload(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _parse_server_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _device_id() -> str:
    """Return a stable, non-reversible identifier without sending raw machine data."""
    parts = [platform.system(), platform.machine()]
    stable_machine_values: list[str] = []
    try:
        machine_unique_id = QtCore.QSysInfo.machineUniqueId().data().decode("utf-8", "ignore")
        if machine_unique_id:
            stable_machine_values.append(machine_unique_id)
    except Exception:
        pass
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Cryptography",
                0,
                winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
            ) as key:
                stable_machine_values.append(str(winreg.QueryValueEx(key, "MachineGuid")[0]))
        except OSError:
            pass
    parts.extend(stable_machine_values or [socket.gethostname()])
    digest = hashlib.sha256(("mukai-license-v1|" + "|".join(parts)).encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _device_name() -> str:
    return (platform.node() or socket.gethostname() or "Windows PC")[:120]


def _format_code(value: str) -> str:
    compact = re.sub(r"[^A-Z0-9]", "", value.upper())[:25]
    return "-".join(compact[index : index + 5] for index in range(0, len(compact), 5))


@dataclass(frozen=True)
class LicenseStatus:
    valid: bool
    message: str = ""
    certificate: dict[str, Any] | None = None


def _run_with_qt_events(callback):
    """Run blocking license I/O without starving the Windows message queue.

    License decisions and server timeouts remain unchanged; only the network
    and credential-vault work moves off the GUI thread. A small nested Qt
    event loop keeps startup and the activation dialog responsive meanwhile.
    """
    app = QtWidgets.QApplication.instance()
    if app is None:
        return callback()

    completed = threading.Event()
    result: list[Any] = []
    error: list[BaseException] = []

    def _work() -> None:
        try:
            result.append(callback())
        except BaseException as exc:
            error.append(exc)
        finally:
            completed.set()

    worker = threading.Thread(target=_work, name="MukaiLicenseRequest", daemon=True)
    worker.start()

    loop = QtCore.QEventLoop()
    poll = QtCore.QTimer()
    poll.setInterval(25)
    poll.timeout.connect(lambda: loop.quit() if completed.is_set() else None)
    poll.start()
    if not completed.is_set():
        loop.exec()
    poll.stop()
    worker.join()

    if error:
        raise error[0]
    return result[0]


class LicenseManager:
    def __init__(self) -> None:
        self.device_id = _device_id()
        self.device_name = _device_name()

    def _verify_certificate(self, certificate: dict[str, Any]) -> dict[str, Any]:
        if certificate.get("algorithm") != "RSA-SHA256":
            raise ValueError("El certificado usa una firma no compatible.")
        payload = certificate.get("license")
        signature_text = certificate.get("signature")
        if not isinstance(payload, dict) or not isinstance(signature_text, str):
            raise ValueError("El certificado de licencia está incompleto.")

        try:
            key = serialization.load_pem_public_key(base64.b64decode(UPDATE_PUBLIC_KEY, validate=True))
            if not isinstance(key, rsa.RSAPublicKey) or key.key_size < 3072:
                raise ValueError("La clave pública de licencia no es válida.")
            key.verify(
                base64.b64decode(signature_text, validate=True),
                _canonical_payload(payload),
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
        except (InvalidSignature, TypeError, ValueError) as exc:
            raise ValueError("No se pudo comprobar la firma de la licencia.") from exc

        expected_device = hashlib.sha256(self.device_id.encode("utf-8")).hexdigest()
        if payload.get("device_hash") != expected_device:
            raise ValueError("Esta licencia pertenece a otro equipo.")

        now = datetime.now(timezone.utc)
        expires_at = _parse_server_datetime(str(payload.get("expires_at") or ""))
        issued_at = _parse_server_datetime(str(payload.get("issued_at") or ""))
        if now >= expires_at:
            raise ValueError("La licencia ha vencido.")
        if now < issued_at - timedelta(minutes=10):
            raise ValueError("La fecha del equipo no coincide con la licencia.")
        return payload

    @staticmethod
    def _server_message(response: requests.Response) -> str:
        try:
            data = response.json()
            code = str(data.get("code") or "")
            localized = {
                "invalid_license": "El código de activación no es válido o la licencia fue revocada.",
                "expired_license": "La licencia ha vencido.",
                "unknown_device": "Este equipo no está registrado para la licencia.",
                "device_limit": "La licencia ya alcanzó el límite de equipos permitidos.",
                "invalid_request": "Los datos de activación no son válidos.",
            }
            if code in localized:
                return localized[code]
            message = data.get("message")
            if message:
                return str(message)
        except Exception:
            pass
        return f"El servidor rechazó la solicitud ({response.status_code})."

    def _post(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = requests.post(
            f"{LICENSE_API_BASE.rstrip('/')}/{endpoint}",
            json=payload,
            timeout=(5, 12),
            headers={"Accept": "application/json", "User-Agent": "MukaiTranslator/1"},
        )
        if response.status_code >= 500:
            raise requests.RequestException("El servidor de licencias no está disponible temporalmente.")
        if not response.ok:
            raise ValueError(self._server_message(response))
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("El servidor devolvió una respuesta de licencia inválida.")
        return data

    def activate(self, code: str) -> LicenseStatus:
        normalized = _format_code(code)
        if len(normalized.replace("-", "")) != 25:
            return LicenseStatus(False, "Escribe los 25 caracteres del código de activación.")
        try:
            certificate = self._post(
                "activate",
                {
                    "code": normalized,
                    "device_id": self.device_id,
                    "device_name": self.device_name,
                },
            )
            self._verify_certificate(certificate)
            set_token(_CERTIFICATE_TOKEN, json.dumps(certificate, separators=(",", ":")))
            return LicenseStatus(True, certificate=certificate)
        except requests.RequestException:
            return LicenseStatus(False, "No se pudo conectar con el servidor de licencias. Revisa tu conexión.")
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            return LicenseStatus(False, str(exc))

    def validate_saved(self) -> LicenseStatus:
        raw = get_token(_CERTIFICATE_TOKEN)
        if not raw:
            return LicenseStatus(False)
        try:
            certificate = json.loads(raw)
            payload = self._verify_certificate(certificate)
        except Exception as exc:
            delete_token(_CERTIFICATE_TOKEN)
            return LicenseStatus(False, str(exc))

        try:
            refreshed = self._post(
                "validate",
                {
                    "license_id": int(payload["license_id"]),
                    "device_id": self.device_id,
                    "device_name": self.device_name,
                },
            )
            self._verify_certificate(refreshed)
            set_token(_CERTIFICATE_TOKEN, json.dumps(refreshed, separators=(",", ":")))
            return LicenseStatus(True, certificate=refreshed)
        except requests.RequestException:
            server_time = _parse_server_datetime(str(payload.get("server_time") or ""))
            if datetime.now(timezone.utc) - server_time <= _OFFLINE_GRACE:
                return LicenseStatus(True, "Modo sin conexión", certificate=certificate)
            return LicenseStatus(False, "Conecta este equipo a Internet para validar la licencia.")
        except Exception as exc:
            delete_token(_CERTIFICATE_TOKEN)
            return LicenseStatus(False, str(exc))


class LicenseActivationDialog(QtWidgets.QDialog):
    def __init__(self, manager: LicenseManager, message: str = "", parent=None) -> None:
        super().__init__(parent)
        self.manager = manager
        self.activated = False
        self.setWindowTitle("Activar Mukai Translator")
        self.setModal(True)
        self.setFixedWidth(500)
        self.setWindowFlag(QtCore.Qt.WindowType.WindowContextHelpButtonHint, False)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(30, 26, 30, 26)
        root.setSpacing(14)

        heading = QtWidgets.QLabel("Activar Mukai Translator")
        heading.setObjectName("licenseHeading")
        detail = QtWidgets.QLabel(
            "Introduce el código de 25 caracteres. La licencia tendrá una vigencia de 90 días "
            "desde su primera activación."
        )
        detail.setWordWrap(True)
        detail.setObjectName("licenseDetail")
        root.addWidget(heading)
        root.addWidget(detail)

        self.code_edit = QtWidgets.QLineEdit()
        self.code_edit.setInputMask(">NNNNN-NNNNN-NNNNN-NNNNN-NNNNN;_")
        self.code_edit.setPlaceholderText("XXXXX-XXXXX-XXXXX-XXXXX-XXXXX")
        self.code_edit.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.code_edit.setObjectName("licenseCode")
        self.code_edit.returnPressed.connect(self._activate)
        root.addWidget(self.code_edit)

        self.status_label = QtWidgets.QLabel(message)
        self.status_label.setWordWrap(True)
        self.status_label.setObjectName("licenseStatus")
        self.status_label.setVisible(bool(message))
        root.addWidget(self.status_label)

        buttons = QtWidgets.QHBoxLayout()
        buttons.addStretch()
        cancel = QtWidgets.QPushButton("Salir")
        cancel.clicked.connect(self.reject)
        activate = QtWidgets.QPushButton("Activar")
        activate.setObjectName("licenseActivate")
        activate.setDefault(True)
        activate.clicked.connect(self._activate)
        buttons.addWidget(cancel)
        buttons.addWidget(activate)
        root.addLayout(buttons)

        self.setStyleSheet("""
            QDialog { background: #17171c; color: #f4f4f6; }
            QLabel#licenseHeading { font-size: 24px; font-weight: 700; color: #ffffff; }
            QLabel#licenseDetail { color: #b7b7c2; font-size: 13px; }
            QLabel#licenseStatus { color: #ff8da3; }
            QLineEdit#licenseCode {
                background: #24242b; border: 1px solid #474752; border-radius: 8px;
                color: #ffffff; padding: 12px; font-size: 17px; font-weight: 600;
                letter-spacing: 1px;
            }
            QLineEdit#licenseCode:focus { border: 1px solid #ef5575; }
            QPushButton { background: #2b2b33; border: 1px solid #44444e; color: #eeeeF2;
                border-radius: 7px; padding: 9px 20px; }
            QPushButton#licenseActivate { background: #d13655; border-color: #ef6d88; color: white; }
            QPushButton#licenseActivate:hover { background: #e24665; }
        """)

    def _activate(self) -> None:
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
        try:
            status = _run_with_qt_events(lambda: self.manager.activate(self.code_edit.text()))
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        if status.valid:
            self.activated = True
            self.accept()
            return
        self.status_label.setText(status.message or "No se pudo activar la licencia.")
        self.status_label.show()
        self.code_edit.setFocus()
        self.code_edit.selectAll()


def ensure_application_license(parent=None) -> bool:
    """Gate frozen customer builds while keeping source development frictionless."""
    force_gate = os.environ.get("MUKAI_FORCE_LICENSE") == "1"
    if not getattr(sys, "frozen", False) and not force_gate:
        return True
    if not LICENSE_API_BASE.strip() or not UPDATE_PUBLIC_KEY.strip():
        QtWidgets.QMessageBox.critical(
            parent,
            "Licencia no configurada",
            "Esta edición de Mukai Translator no tiene configurado su servidor de licencias.",
        )
        return False

    manager = LicenseManager()
    status = _run_with_qt_events(manager.validate_saved)
    if status.valid:
        return True
    dialog = LicenseActivationDialog(manager, status.message, parent)
    return dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted and dialog.activated
