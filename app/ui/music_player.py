"""Compact theme-adaptive music player for the editor sidebar.

Unified music player for local audio files and Windows media playback (Spotify, etc.).
Features collapsible header accordion, vector SVG program logo cover, real-time title & seconds progress syncing,
and theme-adaptive controls.
"""

from __future__ import annotations

import asyncio
import ctypes
import random
import sys
import threading
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtMultimedia import QAudioOutput, QMediaMetaData, QMediaPlayer
from PySide6.QtSvg import QSvgRenderer


_AUDIO_EXTENSIONS = {
    ".aac",
    ".flac",
    ".m4a",
    ".mp3",
    ".ogg",
    ".opus",
    ".wav",
    ".wma",
}

_EXCLUDE_WINDOW_KEYWORDS = (
    "program manager",
    "connecting windows media player",
    "mukai-translator",
    "explorador de archivos",
    "file explorer",
    "administrador de tareas",
    "task manager",
    "windows input experience",
    "microsoft support",
    "google search",
    "nueva pestaña",
    "new tab",
    "cmd.exe",
    "powershell",
    ".ctpr",
)


class MusicPlayerWidget(QtWidgets.QFrame):
    """Collapsible theme-adaptive music player for local files and system media."""

    systemMediaStatusReady = QtCore.Signal(dict)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("musicPlayerCard")
        self.setAcceptDrops(True)

        self._expanded = False  # Start collapsed by default
        self.setMinimumHeight(34)
        self.setMaximumHeight(36)

        self._settings = QtCore.QSettings("ComicLabs", "ComicTranslate")
        self._tracks: list[str] = []
        self._current_index = -1
        self._seeking = False
        self._duration = 0
        self._is_dark = True
        self._theme_variant = ""
        self._system_media_active = False
        self._system_elapsed_seconds = 0
        self._system_estimated_duration = 210  # 3:30 estimation for system media
        self._system_is_playing = True
        self._system_polling = False

        # Theme color defaults
        self._control_icon_color = "#AAB4C1"
        self._accent_color = "#168FF7"  # Default celeste
        self._accent_pressed_color = "#0F76DE"
        self._primary_icon_color = "#FFFFFF"

        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_output)

        self.system_timer = QtCore.QTimer(self)
        self.system_timer.setInterval(1200)
        self.system_timer.timeout.connect(self._refresh_system_media_status)
        self.systemMediaStatusReady.connect(self._apply_system_media_status)

        self.seconds_ticker = QtCore.QTimer(self)
        self.seconds_ticker.setInterval(1000)
        self.seconds_ticker.timeout.connect(self._on_seconds_tick)

        self._build_ui()
        self._connect_player()
        self._restore_settings()
        self._auto_discover_music()

        self.apply_theme(True, "blue")
        self.system_timer.start()
        self.seconds_ticker.start()

    def _standard_icon(
        self,
        pixmap: QtWidgets.QStyle.StandardPixmap,
    ) -> QtGui.QIcon:
        return self.style().standardIcon(pixmap)

    def _make_control(
        self,
        icon: QtWidgets.QStyle.StandardPixmap,
        tooltip: str,
        *,
        prominent: bool = False,
        checkable: bool = False,
    ) -> QtWidgets.QToolButton:
        button = QtWidgets.QToolButton(self)
        button.setObjectName("musicPrimaryControl" if prominent else "musicControl")
        button.setIcon(self._standard_icon(icon))
        button.setIconSize(QtCore.QSize(20 if prominent else 16, 20 if prominent else 16))
        button.setFixedSize(36 if prominent else 28, 36 if prominent else 28)
        button.setToolTip(tooltip)
        button.setCheckable(checkable)
        button.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        button.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        return button

    def _build_ui(self) -> None:
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(10, 5, 10, 6)
        root.setSpacing(4)

        # Header Row (Clickable accordion header)
        header_widget = QtWidgets.QWidget(self)
        header_widget.setObjectName("musicHeaderWidget")
        header_widget.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        
        header = QtWidgets.QHBoxLayout(header_widget)
        header.setContentsMargins(0, 2, 0, 2)
        header.setSpacing(6)

        self.toggle_arrow = QtWidgets.QLabel("▸", self)
        self.toggle_arrow.setObjectName("musicToggleArrow")
        
        title = QtWidgets.QLabel(self.tr("MÚSICA"), self)
        title.setObjectName("musicSectionTitle")
        
        header.addWidget(self.toggle_arrow)
        header.addWidget(title)
        header.addStretch()

        self.add_button = self._make_control(
            QtWidgets.QStyle.StandardPixmap.SP_FileDialogNewFolder,
            self.tr("Agregar música"),
        )
        self.add_button.setObjectName("musicAddButton")
        self.queue_button = self._make_control(
            QtWidgets.QStyle.StandardPixmap.SP_FileDialogListView,
            self.tr("Lista de reproducción"),
        )
        header.addWidget(self.add_button)
        header.addWidget(self.queue_button)

        root.addWidget(header_widget)

        # Player Body Container (Hidden when collapsed)
        self.player_body = QtWidgets.QWidget(self)
        self.player_body.setObjectName("musicPlayerBody")
        body_layout = QtWidgets.QVBoxLayout(self.player_body)
        body_layout.setContentsMargins(0, 4, 0, 2)
        body_layout.setSpacing(6)

        # Track Info Row
        now_playing = QtWidgets.QHBoxLayout()
        now_playing.setSpacing(9)
        self.cover_label = QtWidgets.QLabel(self)
        self.cover_label.setObjectName("musicCover")
        self.cover_label.setFixedSize(42, 42)
        self.cover_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        now_playing.addWidget(self.cover_label)

        track_text = QtWidgets.QVBoxLayout()
        track_text.setContentsMargins(0, 1, 0, 1)
        track_text.setSpacing(1)
        self.track_title = QtWidgets.QLabel(self.tr("Elige una canción"), self)
        self.track_title.setObjectName("musicTrackTitle")
        self.track_artist = QtWidgets.QLabel(self.tr("Reproductor local"), self)
        self.track_artist.setObjectName("musicTrackArtist")
        track_text.addWidget(self.track_title)
        track_text.addWidget(self.track_artist)
        now_playing.addLayout(track_text, 1)

        body_layout.addLayout(now_playing)

        # Progress / Seconds Slider Row
        progress_row = QtWidgets.QHBoxLayout()
        progress_row.setSpacing(6)
        self.elapsed_label = QtWidgets.QLabel("0:00", self)
        self.elapsed_label.setObjectName("musicTime")
        self.progress_slider = QtWidgets.QSlider(
            QtCore.Qt.Orientation.Horizontal,
            self,
        )
        self.progress_slider.setObjectName("musicProgress")
        self.progress_slider.setRange(0, 100)
        self.remaining_label = QtWidgets.QLabel("0:00", self)
        self.remaining_label.setObjectName("musicTime")
        self.remaining_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        progress_row.addWidget(self.elapsed_label)
        progress_row.addWidget(self.progress_slider, 1)
        progress_row.addWidget(self.remaining_label)
        body_layout.addLayout(progress_row)

        # Centered Playback Controls Row (Repeat on left, Shuffle on right)
        controls = QtWidgets.QHBoxLayout()
        controls.setContentsMargins(0, 2, 0, 2)
        controls.setSpacing(0)

        playback_box = QtWidgets.QHBoxLayout()
        playback_box.setContentsMargins(0, 0, 0, 0)
        playback_box.setSpacing(14)  # Wide spacing between control buttons

        self.repeat_button = self._make_control(
            QtWidgets.QStyle.StandardPixmap.SP_BrowserReload,
            self.tr("Repetir canción"),
            checkable=True,
        )
        self.previous_button = self._make_control(
            QtWidgets.QStyle.StandardPixmap.SP_MediaSkipBackward,
            self.tr("Anterior"),
        )
        self.play_button = self._make_control(
            QtWidgets.QStyle.StandardPixmap.SP_MediaPlay,
            self.tr("Reproducir o pausar"),
            prominent=True,
        )
        self.next_button = self._make_control(
            QtWidgets.QStyle.StandardPixmap.SP_MediaSkipForward,
            self.tr("Siguiente"),
        )
        self.shuffle_button = self._make_control(
            QtWidgets.QStyle.StandardPixmap.SP_BrowserReload,
            self.tr("Reproducción aleatoria"),
            checkable=True,
        )
        self.shuffle_button.setText("⇄")
        self.shuffle_button.setToolButtonStyle(
            QtCore.Qt.ToolButtonStyle.ToolButtonTextOnly
        )

        playback_box.addWidget(self.repeat_button)
        playback_box.addWidget(self.previous_button)
        playback_box.addWidget(self.play_button)
        playback_box.addWidget(self.next_button)
        playback_box.addWidget(self.shuffle_button)

        controls.addStretch(1)
        controls.addLayout(playback_box)
        controls.addStretch(1)

        body_layout.addLayout(controls)

        # Start collapsed by default
        self.player_body.hide()
        root.addWidget(self.player_body)

        # Signals
        header_widget.mousePressEvent = lambda _event: self._toggle_expanded()
        self.add_button.clicked.connect(self.add_files)
        self.queue_button.clicked.connect(self._show_queue_menu)
        self.previous_button.clicked.connect(self.previous)
        self.play_button.clicked.connect(self.toggle_playback)
        self.next_button.clicked.connect(self.next)
        self.repeat_button.toggled.connect(self._save_playback_options)
        self.shuffle_button.toggled.connect(self._save_playback_options)
        self.repeat_button.toggled.connect(self._refresh_control_icons)
        self.shuffle_button.toggled.connect(self._refresh_control_icons)
        self.progress_slider.sliderPressed.connect(self._begin_seek)
        self.progress_slider.sliderReleased.connect(self._finish_seek)
        self.progress_slider.sliderMoved.connect(self._preview_seek)

    def _toggle_expanded(self) -> None:
        self._expanded = not self._expanded
        self.player_body.setVisible(self._expanded)
        self.toggle_arrow.setText("▾" if self._expanded else "▸")
        if self._expanded:
            self.setMinimumHeight(188)
            self.setMaximumHeight(214)
        else:
            self.setMinimumHeight(34)
            self.setMaximumHeight(36)
        self.updateGeometry()

    def _connect_player(self) -> None:
        self.player.positionChanged.connect(self._position_changed)
        self.player.durationChanged.connect(self._duration_changed)
        self.player.playbackStateChanged.connect(self._playback_state_changed)
        self.player.mediaStatusChanged.connect(self._media_status_changed)
        self.player.metaDataChanged.connect(self._metadata_changed)
        self.player.errorOccurred.connect(self._playback_error)

    @staticmethod
    def _normalise_setting_list(value: object) -> list[str]:
        if isinstance(value, (list, tuple)):
            return [str(item) for item in value]
        if isinstance(value, str) and value:
            return [value]
        return []

    def _restore_settings(self) -> None:
        self._settings.beginGroup("music_player")
        stored_tracks = self._normalise_setting_list(
            self._settings.value("local_tracks", [])
        )
        self._tracks = [
            str(Path(track))
            for track in stored_tracks
            if Path(track).is_file()
            and Path(track).suffix.casefold() in _AUDIO_EXTENSIONS
        ]
        index = int(self._settings.value("current_index", 0))
        repeat = str(self._settings.value("repeat", "false")).lower() == "true"
        shuffle = str(self._settings.value("shuffle", "false")).lower() == "true"
        self._settings.endGroup()

        self.repeat_button.setChecked(repeat)
        self.shuffle_button.setChecked(shuffle)
        if self._tracks:
            self._load_index(max(0, min(index, len(self._tracks) - 1)), autoplay=False)

    def _auto_discover_music(self) -> None:
        """Auto discover audio files from user's Music folder if library is empty."""
        if self._tracks:
            return
        music_dir = Path.home() / "Music"
        found: list[str] = []
        if music_dir.exists() and music_dir.is_dir():
            for path in music_dir.rglob("*"):
                if path.is_file() and path.suffix.casefold() in _AUDIO_EXTENSIONS:
                    found.append(str(path.resolve()))
                    if len(found) >= 50:
                        break
        if found:
            self._tracks = sorted(found)
            self._save_library()
            self._load_index(0, autoplay=False)

    def _save_library(self) -> None:
        self._settings.beginGroup("music_player")
        self._settings.setValue("local_tracks", self._tracks)
        self._settings.setValue("current_index", max(0, self._current_index))
        self._settings.endGroup()

    def _save_playback_options(self, *_args) -> None:
        self._settings.beginGroup("music_player")
        self._settings.setValue("repeat", self.repeat_button.isChecked())
        self._settings.setValue("shuffle", self.shuffle_button.isChecked())
        self._settings.endGroup()

    def add_files(self) -> None:
        filters = self.tr(
            "Audio (*.mp3 *.m4a *.flac *.wav *.ogg *.opus *.aac *.wma)"
        )
        files, _selected = QtWidgets.QFileDialog.getOpenFileNames(
            self,
            self.tr("Agregar música"),
            str(Path.home() / "Music"),
            filters,
        )
        self._append_tracks(files, autoplay=True)

    def add_folder(self) -> None:
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            self.tr("Agregar carpeta de música"),
            str(Path.home() / "Music"),
        )
        if not folder:
            return
        paths = sorted(
            (
                path
                for path in Path(folder).rglob("*")
                if path.is_file() and path.suffix.casefold() in _AUDIO_EXTENSIONS
            ),
            key=lambda path: str(path).casefold(),
        )
        self._append_tracks([str(path) for path in paths], autoplay=True)

    def _append_tracks(self, paths: list[str], *, autoplay: bool) -> None:
        valid: list[str] = []
        known = {str(Path(track).resolve()).casefold() for track in self._tracks}
        for raw_path in paths:
            path = Path(raw_path)
            if not path.is_file() or path.suffix.casefold() not in _AUDIO_EXTENSIONS:
                continue
            resolved = str(path.resolve())
            if resolved.casefold() in known:
                continue
            known.add(resolved.casefold())
            valid.append(resolved)
        if not valid:
            return
        first_new = len(self._tracks)
        self._tracks.extend(valid)
        self._save_library()
        self._load_index(first_new, autoplay=autoplay)

    def _load_index(self, index: int, *, autoplay: bool = True) -> None:
        if not 0 <= index < len(self._tracks):
            return
        self._current_index = index
        path = Path(self._tracks[index])
        self.player.setSource(QtCore.QUrl.fromLocalFile(str(path)))
        self.track_title.setText(path.stem)
        self.track_artist.setText(self.tr("Archivo local"))
        self._update_cover_placeholder()
        self._save_library()
        if autoplay:
            self.player.play()

    def _update_local_track_labels(self) -> None:
        if not 0 <= self._current_index < len(self._tracks):
            self.track_title.setText(self.tr("Elige una canción"))
            self.track_artist.setText(self.tr("Archivos locales"))
            return
        path = Path(self._tracks[self._current_index])
        metadata = self.player.metaData()
        title = metadata.value(QMediaMetaData.Key.Title) or path.stem
        artist = metadata.value(QMediaMetaData.Key.ContributingArtist)
        if isinstance(artist, (list, tuple)):
            artist = ", ".join(str(value) for value in artist if value)
        self.track_title.setText(str(title))
        self.track_artist.setText(str(artist or self.tr("Archivo local")))
        self.track_title.setToolTip(str(title))
        self.track_artist.setToolTip(str(artist or path))

    def _update_play_pause_button_icon(self) -> None:
        """Update play/pause icon: shows two vertical bars ('||') during playback."""
        is_playing = (
            self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
            or (self._system_media_active and self._system_is_playing)
        )
        icon_kind = "pause" if is_playing else "play"
        self.play_button.setIcon(
            self._paint_music_icon(
                icon_kind,
                self._primary_icon_color,
                22,
            )
        )
        self.play_button.setToolTip(
            self.tr("Pausar") if is_playing else self.tr("Reproducir")
        )

    def toggle_playback(self) -> None:
        """Play or pause playback normally."""
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        elif self._system_media_active:
            self._send_media_key(0xB3)  # VK_MEDIA_PLAY_PAUSE
            self._system_is_playing = not self._system_is_playing
        elif self._tracks:
            if self.player.source().isEmpty() or self._current_index < 0:
                self._load_index(0, autoplay=True)
            else:
                self.player.play()
        else:
            self._send_media_key(0xB3)  # VK_MEDIA_PLAY_PAUSE
            self._system_is_playing = not self._system_is_playing

        self._update_play_pause_button_icon()

    def previous(self) -> None:
        """Play previous track natively."""
        if self._system_media_active and self.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
            self._send_media_key(0xB1)  # VK_MEDIA_PREV_TRACK
            self._system_elapsed_seconds = 0
            self._update_play_pause_button_icon()
            return
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState or self._tracks:
            if not self._tracks:
                return
            if self.player.position() > 4000:
                self.player.setPosition(0)
            else:
                self._load_index((self._current_index - 1) % len(self._tracks))
            return
        self._send_media_key(0xB1)  # VK_MEDIA_PREV_TRACK
        self._system_elapsed_seconds = 0
        self._update_play_pause_button_icon()

    def next(self) -> None:
        """Play next track natively."""
        if self._system_media_active and self.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
            self._send_media_key(0xB0)  # VK_MEDIA_NEXT_TRACK
            self._system_elapsed_seconds = 0
            self._update_play_pause_button_icon()
            return
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState or self._tracks:
            if not self._tracks:
                return
            if self.shuffle_button.isChecked() and len(self._tracks) > 1:
                choices = [i for i in range(len(self._tracks)) if i != self._current_index]
                self._load_index(random.choice(choices))
            else:
                self._load_index((self._current_index + 1) % len(self._tracks))
            return
        self._send_media_key(0xB0)  # VK_MEDIA_NEXT_TRACK
        self._system_elapsed_seconds = 0
        self._update_play_pause_button_icon()

    def _begin_seek(self) -> None:
        self._seeking = True

    def _finish_seek(self) -> None:
        self._seeking = False
        if not self._system_media_active:
            self.player.setPosition(self.progress_slider.value())

    def _preview_seek(self, position: int) -> None:
        self.elapsed_label.setText(self._format_time(position))

    def _position_changed(self, position: int) -> None:
        if not self._seeking:
            self.progress_slider.setValue(position)
        self.elapsed_label.setText(self._format_time(position))
        remaining = max(0, self._duration - position)
        self.remaining_label.setText(self._format_time(remaining))

    def _duration_changed(self, duration: int) -> None:
        self._duration = max(0, duration)
        self.progress_slider.setRange(0, self._duration)
        remaining = max(0, self._duration - self.player.position())
        self.remaining_label.setText(self._format_time(remaining))

    def _on_seconds_tick(self) -> None:
        """Tick seconds and advance progress bar smoothly when Spotify/system media is active."""
        if self._system_media_active and self.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState and self._system_is_playing:
            self._system_elapsed_seconds += 1
            seconds = self._system_elapsed_seconds
            dur = max(60, self._system_estimated_duration)
            
            if not self._seeking:
                self.progress_slider.setRange(0, dur)
                self.progress_slider.setValue(seconds % dur)
            
            self.elapsed_label.setText(f"{seconds // 60}:{seconds % 60:02d}")
            rem = max(0, dur - (seconds % dur))
            self.remaining_label.setText(f"{rem // 60}:{rem % 60:02d}")

    @staticmethod
    def _format_time(milliseconds: int) -> str:
        seconds = max(0, int(milliseconds) // 1000)
        return f"{seconds // 60}:{seconds % 60:02d}"

    def _playback_state_changed(
        self,
        _state: QMediaPlayer.PlaybackState,
    ) -> None:
        self._update_play_pause_button_icon()

    def _media_status_changed(self, status: QMediaPlayer.MediaStatus) -> None:
        if status != QMediaPlayer.MediaStatus.EndOfMedia:
            return
        if self.repeat_button.isChecked():
            self.player.setPosition(0)
            self.player.play()
        else:
            self.next()

    def _metadata_changed(self) -> None:
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState or not self._system_media_active:
            self._update_local_track_labels()
            metadata = self.player.metaData()
            cover = metadata.value(QMediaMetaData.Key.CoverArtImage)
            if isinstance(cover, QtGui.QImage) and not cover.isNull():
                self._set_cover_pixmap(QtGui.QPixmap.fromImage(cover))
            elif isinstance(cover, QtGui.QPixmap) and not cover.isNull():
                self._set_cover_pixmap(cover)

    def _playback_error(
        self,
        _error: QMediaPlayer.Error,
        error_string: str,
    ) -> None:
        if error_string and not self._system_media_active:
            self.track_artist.setText(self.tr("No se pudo reproducir este archivo"))
            self.track_artist.setToolTip(error_string)

    def _show_queue_menu(self) -> None:
        menu = QtWidgets.QMenu(self)
        add_files_action = menu.addAction(self.tr("Agregar archivos…"))
        add_folder_action = menu.addAction(self.tr("Agregar carpeta…"))
        add_files_action.triggered.connect(self.add_files)
        add_folder_action.triggered.connect(self.add_folder)
        if self._tracks:
            menu.addSeparator()
            for index, track in enumerate(self._tracks[:30]):
                action = menu.addAction(Path(track).stem)
                action.setCheckable(True)
                action.setChecked(index == self._current_index)
                action.triggered.connect(
                    lambda _checked=False, row=index: self._load_index(row)
                )
            if len(self._tracks) > 30:
                more = menu.addAction(
                    self.tr("+ {count} canciones más").format(
                        count=len(self._tracks) - 30
                    )
                )
                more.setEnabled(False)
            menu.addSeparator()
            remove_action = menu.addAction(self.tr("Quitar canción actual"))
            clear_action = menu.addAction(self.tr("Vaciar lista"))
            remove_action.triggered.connect(self._remove_current_track)
            clear_action.triggered.connect(self._clear_tracks)
        menu.exec(self.queue_button.mapToGlobal(self.queue_button.rect().bottomRight()))

    def _remove_current_track(self) -> None:
        if not 0 <= self._current_index < len(self._tracks):
            return
        self.player.stop()
        self._tracks.pop(self._current_index)
        if self._tracks:
            self._load_index(min(self._current_index, len(self._tracks) - 1), autoplay=False)
        else:
            self._current_index = -1
            self.player.setSource(QtCore.QUrl())
            self._update_local_track_labels()
            self._update_cover_placeholder()
        self._save_library()

    def _clear_tracks(self) -> None:
        self.player.stop()
        self.player.setSource(QtCore.QUrl())
        self._tracks.clear()
        self._current_index = -1
        self._update_local_track_labels()
        self._update_cover_placeholder()
        self._save_library()

    @staticmethod
    def _send_media_key(virtual_key: int) -> None:
        if sys.platform != "win32":
            return
        key_up = 0x0002
        user32 = ctypes.windll.user32
        user32.keybd_event(virtual_key, 0, 0, 0)
        user32.keybd_event(virtual_key, 0, key_up, 0)

    @staticmethod
    async def _read_windows_media_status() -> dict:
        """Read the real Windows media session used by Spotify."""
        from winrt.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionManager,
        )

        manager = await GlobalSystemMediaTransportControlsSessionManager.request_async()
        sessions = list(manager.get_sessions())
        current = manager.get_current_session()
        spotify_sessions = [
            session
            for session in sessions
            if "spotify" in session.source_app_user_model_id.casefold()
        ]
        candidates = spotify_sessions or ([current] if current is not None else [])
        for session in candidates:
            if session is None:
                continue
            properties = await session.try_get_media_properties_async()
            title = str(properties.title or "").strip()
            artist = str(properties.artist or properties.album_artist or "").strip()
            if not title:
                continue
            playback = session.get_playback_info()
            timeline = session.get_timeline_properties()
            position = max(0, int(timeline.position.total_seconds()))
            duration = max(0, int(timeline.end_time.total_seconds()))
            return {
                "album": str(properties.album_title or "").strip(),
                "artist": artist,
                "duration": duration,
                "playing": getattr(playback.playback_status, "name", "") == "PLAYING",
                "position": position,
                "source": str(session.source_app_user_model_id or ""),
                "title": title,
            }
        return {}

    @staticmethod
    def _detect_windows_media_title() -> tuple[str, str]:
        """Detect title and artist from Spotify or active Windows media applications."""
        if sys.platform != "win32":
            return "", ""
        
        user32 = ctypes.windll.user32
        found_titles: list[str] = []

        callback_type = ctypes.WINFUNCTYPE(
            ctypes.c_bool,
            ctypes.c_void_p,
            ctypes.c_void_p,
        )

        def visit(hwnd, _lparam) -> bool:
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            title = buffer.value.strip()
            title_lower = title.casefold()

            # Ignore OS system windows, file explorers, and Mukai app windows
            if any(ex in title_lower for ex in _EXCLUDE_WINDOW_KEYWORDS):
                return True
            
            found_titles.append(title)
            return True

        user32.EnumWindows(callback_type(visit), 0)
        if not found_titles:
            return "", ""

        # Prioritize window titles containing " - " (Artist - Track Name)
        for raw in found_titles:
            clean = raw
            for suffix in (" - Google Chrome", " - Microsoft Edge", " - Mozilla Firefox", " - Brave"):
                if clean.endswith(suffix):
                    clean = clean[:-len(suffix)].strip()
            
            if clean.casefold().endswith(" - spotify"):
                clean = clean[:-10].strip()

            if " - " in clean:
                parts = clean.split(" - ", 1)
                first = parts[0].strip()
                second = parts[1].strip()
                if first.casefold() in ("spotify", "spotify free", "spotify premium"):
                    return second, "Spotify"
                return second, first  # Return (Song Title, Artist)

        # Fallback to non-generic window title
        for raw in found_titles:
            if raw.casefold() not in ("spotify", "spotify free", "spotify premium", "vlc media player", "media player"):
                return raw, "Windows"

        return "", ""

    def _refresh_system_media_status(self) -> None:
        """Fetch Spotify metadata without blocking the editor UI."""
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._system_media_active = False
            self._update_play_pause_button_icon()
            return
        if self._system_polling:
            return
        self._system_polling = True

        def read_status() -> None:
            try:
                status = asyncio.run(self._read_windows_media_status())
            except Exception as exc:
                status = {"error": str(exc)}
            self.systemMediaStatusReady.emit(status)

        threading.Thread(
            target=read_status,
            name="MukaiWindowsMediaStatus",
            daemon=True,
        ).start()

    def _apply_system_media_status(self, status: dict) -> None:
        self._system_polling = False
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            return

        title = str(status.get("title") or "").strip()
        if title:
            artist = str(status.get("artist") or status.get("album") or "Spotify")
            position = max(0, int(status.get("position") or 0))
            duration = max(0, int(status.get("duration") or 0))
            self._system_media_active = True
            self._system_is_playing = bool(status.get("playing"))
            self._system_elapsed_seconds = position
            if duration:
                self._system_estimated_duration = duration

            self.track_title.setText(title)
            self.track_artist.setText(artist)
            self.track_title.setToolTip(title)
            self.track_artist.setToolTip(
                str(status.get("album") or status.get("source") or artist)
            )
            if not self._seeking:
                self.progress_slider.setRange(0, max(1, self._system_estimated_duration))
                self.progress_slider.setValue(
                    min(position, max(1, self._system_estimated_duration))
                )
            self.elapsed_label.setText(f"{position // 60}:{position % 60:02d}")
            remaining = max(0, self._system_estimated_duration - position)
            self.remaining_label.setText(f"{remaining // 60}:{remaining % 60:02d}")
            self._update_play_pause_button_icon()
            return

        self._system_media_active = False
        if self._tracks and 0 <= self._current_index < len(self._tracks):
            self._update_local_track_labels()
        elif status.get("error"):
            self.track_title.setText("Spotify")
            self.track_artist.setText(self.tr("No se pudo leer el reproductor de Windows"))
            self.track_artist.setToolTip(str(status["error"]))
        self._update_play_pause_button_icon()

    def _set_cover_pixmap(self, pixmap: QtGui.QPixmap) -> None:
        scaled = pixmap.scaled(
            self.cover_label.size(),
            QtCore.Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            QtCore.Qt.TransformationMode.SmoothTransformation,
        )
        self.cover_label.setPixmap(scaled)

    @staticmethod
    def _paint_music_icon(
        kind: str,
        colour: str,
        size: int = 20,
    ) -> QtGui.QIcon:
        pixmap = QtGui.QPixmap(24, 24)
        pixmap.fill(QtCore.Qt.GlobalColor.transparent)
        painter = QtGui.QPainter(pixmap)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        color = QtGui.QColor(colour)
        painter.setPen(
            QtGui.QPen(
                color,
                1.8,
                QtCore.Qt.PenStyle.SolidLine,
                QtCore.Qt.PenCapStyle.RoundCap,
                QtCore.Qt.PenJoinStyle.RoundJoin,
            )
        )
        painter.setBrush(color)

        if kind == "play":
            painter.drawPolygon(
                QtGui.QPolygonF(
                    (
                        QtCore.QPointF(8, 5),
                        QtCore.QPointF(19, 12),
                        QtCore.QPointF(8, 19),
                    )
                )
            )
        elif kind == "pause":
            painter.drawRoundedRect(QtCore.QRectF(7, 5, 3.5, 14), 1, 1)
            painter.drawRoundedRect(QtCore.QRectF(13.5, 5, 3.5, 14), 1, 1)
        elif kind in {"previous", "next"}:
            if kind == "previous":
                painter.drawLine(QtCore.QPointF(6, 6), QtCore.QPointF(6, 18))
                points = (
                    QtCore.QPointF(18, 6),
                    QtCore.QPointF(8, 12),
                    QtCore.QPointF(18, 18),
                )
            else:
                painter.drawLine(QtCore.QPointF(18, 6), QtCore.QPointF(18, 18))
                points = (
                    QtCore.QPointF(6, 6),
                    QtCore.QPointF(16, 12),
                    QtCore.QPointF(6, 18),
                )
            painter.drawPolygon(QtGui.QPolygonF(points))
        elif kind == "add":
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            painter.drawLine(QtCore.QPointF(12, 5), QtCore.QPointF(12, 19))
            painter.drawLine(QtCore.QPointF(5, 12), QtCore.QPointF(19, 12))
        elif kind == "queue":
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            for y in (7, 12, 17):
                painter.drawEllipse(QtCore.QPointF(5, y), 1, 1)
                painter.drawLine(QtCore.QPointF(9, y), QtCore.QPointF(20, y))
        elif kind == "shuffle":
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            first = QtGui.QPainterPath(QtCore.QPointF(4, 7))
            first.lineTo(8, 7)
            first.cubicTo(12, 7, 12, 17, 17, 17)
            painter.drawPath(first)
            second = QtGui.QPainterPath(QtCore.QPointF(4, 17))
            second.lineTo(8, 17)
            second.cubicTo(12, 17, 12, 7, 17, 7)
            painter.drawPath(second)
            painter.setBrush(color)
            painter.drawPolygon(
                QtGui.QPolygonF(
                    (
                        QtCore.QPointF(17, 4.5),
                        QtCore.QPointF(21, 7),
                        QtCore.QPointF(17, 9.5),
                    )
                )
            )
            painter.drawPolygon(
                QtGui.QPolygonF(
                    (
                        QtCore.QPointF(17, 14.5),
                        QtCore.QPointF(21, 17),
                        QtCore.QPointF(17, 19.5),
                    )
                )
            )
        elif kind == "repeat":
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            painter.drawArc(QtCore.QRectF(4, 5, 16, 13), 35 * 16, 145 * 16)
            painter.drawArc(QtCore.QRectF(4, 6, 16, 13), 215 * 16, 145 * 16)
            painter.setBrush(color)
            painter.drawPolygon(
                QtGui.QPolygonF(
                    (
                        QtCore.QPointF(17, 3.5),
                        QtCore.QPointF(21, 6.5),
                        QtCore.QPointF(16, 8),
                    )
                )
            )
            painter.drawPolygon(
                QtGui.QPolygonF(
                    (
                        QtCore.QPointF(7, 20.5),
                        QtCore.QPointF(3, 17.5),
                        QtCore.QPointF(8, 16),
                    )
                )
            )
        painter.end()
        icon = QtGui.QIcon()
        icon.addPixmap(
            pixmap.scaled(
                size,
                size,
                QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                QtCore.Qt.TransformationMode.SmoothTransformation,
            )
        )
        return icon

    def _refresh_control_icons(self, *_args) -> None:
        self.add_button.setIcon(
            self._paint_music_icon("add", self._control_icon_color, 17)
        )
        self.queue_button.setIcon(
            self._paint_music_icon("queue", self._control_icon_color, 17)
        )
        self.previous_button.setIcon(
            self._paint_music_icon("previous", self._control_icon_color, 16)
        )
        self.next_button.setIcon(
            self._paint_music_icon("next", self._control_icon_color, 16)
        )
        self.shuffle_button.setText("")
        self.shuffle_button.setToolButtonStyle(
            QtCore.Qt.ToolButtonStyle.ToolButtonIconOnly
        )
        self.shuffle_button.setIcon(
            self._paint_music_icon(
                "shuffle",
                self._accent_color
                if self.shuffle_button.isChecked()
                else self._control_icon_color,
                16,
            )
        )
        self.repeat_button.setIcon(
            self._paint_music_icon(
                "repeat",
                self._accent_color
                if self.repeat_button.isChecked()
                else self._control_icon_color,
                16,
            )
        )
        self._update_play_pause_button_icon()

    def _update_cover_placeholder(self) -> None:
        size = self.cover_label.size()
        pixmap = QtGui.QPixmap(size)
        pixmap.fill(QtCore.Qt.GlobalColor.transparent)
        painter = QtGui.QPainter(pixmap)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform, True)
        
        # Rounded container border path
        path = QtGui.QPainterPath()
        path.addRoundedRect(QtCore.QRectF(pixmap.rect()), 8, 8)
        painter.setClipPath(path)
        
        # Background gradient based on theme accent
        gradient = QtGui.QLinearGradient(0, 0, size.width(), size.height())
        accent_color = QtGui.QColor(self._accent_color)
        darker_color = accent_color.darker(140)
        gradient.setColorAt(0, accent_color)
        gradient.setColorAt(1, darker_color)
        painter.fillPath(path, gradient)
        
        # Render the canonical packaged application logo.
        root_dir = Path(__file__).resolve().parents[2]
        logo_svg = root_dir / "resources" / "icons" / "logo_mt.svg"
        logo_png = root_dir / "resources" / "icons" / "logo_mt.png"
        
        svg_rendered = False
        if logo_svg.is_file():
            try:
                renderer = QSvgRenderer(str(logo_svg))
                if renderer.isValid():
                    padding = 5
                    target_rect = QtCore.QRectF(
                        padding,
                        padding,
                        size.width() - (padding * 2),
                        size.height() - (padding * 2),
                    )
                    renderer.render(painter, target_rect)
                    svg_rendered = True
            except Exception:
                svg_rendered = False

        if not svg_rendered and logo_png.is_file():
            logo_pix = QtGui.QPixmap(str(logo_png))
            if not logo_pix.isNull():
                padded_size = QtCore.QSize(size.width() - 8, size.height() - 8)
                scaled_logo = logo_pix.scaled(
                    padded_size,
                    QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                    QtCore.Qt.TransformationMode.SmoothTransformation,
                )
                lx = (size.width() - scaled_logo.width()) // 2
                ly = (size.height() - scaled_logo.height()) // 2
                painter.drawPixmap(lx, ly, scaled_logo)

        painter.end()
        self.cover_label.setPixmap(pixmap)

    def apply_theme(self, is_dark: bool, variant: str = "") -> None:
        self._is_dark = bool(is_dark)
        self._theme_variant = str(variant).lower() if variant else ("dark" if is_dark else "light")
        
        if not self._is_dark or self._theme_variant == "light":
            # Modo Claro: Selección / Acento Rosa
            card = "#FFFFFF"
            inset = "#F1F3F6"
            border = "#D9DEE5"
            text = "#16191F"
            muted = "#6A7280"
            hover = "#FCE4EC"
            accent = "#D13655"
            accent_pressed = "#B82E49"
            primary_icon_color = "#FFFFFF"
        elif self._theme_variant == "black":
            # Modo Oscuro (Black): Selección / Acento Blanco tipo Gris
            card = "#070707"
            inset = "#111111"
            border = "#262626"
            text = "#FFFFFF"
            muted = "#A7A7A7"
            hover = "#252525"
            accent = "#E0E0E0"
            accent_pressed = "#CCCCCC"
            primary_icon_color = "#111111"
        else:
            # Modo Azul (Dark / Blue / Celeste): Selección / Acento Azul Celeste
            card = "#111722"
            inset = "#161C27"
            border = "#1D2430"
            text = "#FFFFFF"
            muted = "#AAB4C1"
            hover = "#1A314F"
            accent = "#168FF7"
            accent_pressed = "#0F76DE"
            primary_icon_color = "#FFFFFF"

        self._control_icon_color = muted
        self._accent_color = accent
        self._accent_pressed_color = accent_pressed
        self._primary_icon_color = primary_icon_color

        self.setStyleSheet(f"""
            QFrame#musicPlayerCard {{
                background: {card};
                border-top: 1px solid {border};
                color: {text};
            }}
            QWidget#musicHeaderWidget:hover {{
                background: {hover};
                border-radius: 4px;
            }}
            QLabel#musicToggleArrow {{
                color: {accent};
                font-size: 13px;
                font-weight: 700;
            }}
            QLabel#musicSectionTitle {{
                color: {text};
                font-size: 11px;
                font-weight: 700;
                letter-spacing: 1px;
                border: none;
                background: transparent;
            }}
            QToolButton#musicAddButton,
            QToolButton#musicControl {{
                color: {muted};
                background: transparent;
                border: none;
                border-radius: 7px;
            }}
            QToolButton#musicAddButton:hover,
            QToolButton#musicControl:hover {{
                color: {text};
                background: {hover};
            }}
            QToolButton#musicControl:checked {{
                color: {accent};
                background: {hover};
            }}
            QToolButton#musicPrimaryControl {{
                color: {primary_icon_color};
                background: {accent};
                border: none;
                border-radius: 18px;
            }}
            QToolButton#musicPrimaryControl:hover {{
                background: {accent_pressed};
            }}
            QLabel#musicCover {{
                background: transparent;
                border: none;
            }}
            QLabel#musicTrackTitle {{
                color: {text};
                font-size: 11px;
                font-weight: 700;
                border: none;
                background: transparent;
            }}
            QLabel#musicTrackArtist,
            QLabel#musicTime {{
                color: {muted};
                font-size: 9px;
                border: none;
                background: transparent;
            }}
            QSlider#musicProgress::groove:horizontal {{
                height: 3px;
                background: {border};
                border-radius: 1px;
            }}
            QSlider#musicProgress::sub-page:horizontal {{
                background: {accent};
                border-radius: 1px;
            }}
            QSlider#musicProgress::handle:horizontal {{
                width: 10px;
                margin: -4px 0;
                background: {text};
                border: none;
                border-radius: 5px;
            }}
            QSlider:disabled {{
                opacity: 0.45;
            }}
            QMenu {{
                background: {card};
                color: {text};
                border: 1px solid {border};
                padding: 5px;
            }}
            QMenu::item {{
                padding: 6px 22px 6px 8px;
                border-radius: 4px;
            }}
            QMenu::item:selected {{
                background: {hover};
            }}
            QMenu::indicator:checked {{
                background: {accent};
                border-radius: 4px;
            }}
        """)
        self._refresh_control_icons()
        self._update_cover_placeholder()

    def dragEnterEvent(self, event: QtGui.QDragEnterEvent) -> None:  # noqa: N802
        if any(
            url.isLocalFile()
            and Path(url.toLocalFile()).suffix.casefold() in _AUDIO_EXTENSIONS
            for url in event.mimeData().urls()
        ):
            event.acceptProposedAction()

    def dropEvent(self, event: QtGui.QDropEvent) -> None:  # noqa: N802
        paths = [
            url.toLocalFile()
            for url in event.mimeData().urls()
            if url.isLocalFile()
        ]
        self._append_tracks(paths, autoplay=True)
        event.acceptProposedAction()
