#!/usr/bin/env python3
"""Tray icon showing whether Tailscale is up, with a window listing tailnet devices.

Run with --hidden to start in the tray only (used by autostart). Launching it
again while it's running just shows the existing window.
"""
import json
import subprocess
import sys
from datetime import datetime, timezone

from PyQt6.QtCore import QTimer, QUrl, Qt
from PyQt6.QtGui import QAction, QBrush, QColor, QDesktopServices, QGuiApplication, QIcon
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import (
    QApplication, QHBoxLayout, QHeaderView, QLabel, QMenu, QPushButton,
    QSystemTrayIcon, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

DASHBOARD_URL = "https://login.tailscale.com/admin/machines"
REFRESH_MS = 10_000
SOCKET_NAME = "tailnet-devices"
ICON_ON = "network-vpn-symbolic"
ICON_OFF = "security-low-symbolic"


def parse_seen(stamp):
    try:
        then = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None
    return then if then.year >= 2000 else None


def ago(then):
    if then is None:
        return "offline"
    secs = int((datetime.now(timezone.utc) - then).total_seconds())
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if secs >= size:
            return f"last seen {secs // size}{unit} ago"
    return "last seen just now"


def load_status():
    """Return (backend_state, devices). Raises if tailscale can't be queried."""
    out = subprocess.run(["tailscale", "status", "--json"],
                         capture_output=True, text=True, timeout=5)
    data = json.loads(out.stdout)
    state = data.get("BackendState", "Unknown")
    rows = []
    me = data.get("Self")
    if me:
        rows.append((me, True))
    rows += [(p, False) for p in (data.get("Peer") or {}).values()]
    devices = []
    for node, is_self in rows:
        name = (node.get("DNSName") or "").split(".")[0] or node.get("HostName", "?")
        ips = node.get("TailscaleIPs") or []
        online = node.get("Online", False) or (is_self and state == "Running")
        seen = parse_seen(node.get("LastSeen"))
        devices.append({
            "name": name + (" (this device)" if is_self else ""),
            "ip": next((ip for ip in ips if "." in ip), ips[0] if ips else ""),
            "os": node.get("OS", ""),
            "online": online,
            "status": "online" if online else ago(seen),
            "seen": seen.timestamp() if seen else 0,
        })
    # Online first (by name), then offline by most recently seen.
    devices.sort(key=lambda d: (not d["online"], 0 if d["online"] else -d["seen"], d["name"].lower()))
    return state, devices


class Window(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Tailscale Devices")
        self.resize(560, 380)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Device", "IP", "OS", "Status"])
        self.tree.setRootIsDecorated(False)
        self.tree.setSortingEnabled(False)
        self.tree.header().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.tree.header().setStretchLastSection(True)
        self.tree.itemDoubleClicked.connect(self.copy_ip)

        self.info = QLabel()
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        dash = QPushButton("Open Dashboard")
        dash.setDefault(True)
        dash.clicked.connect(open_dashboard)

        buttons = QHBoxLayout()
        buttons.addWidget(self.info, 1)
        buttons.addWidget(refresh)
        buttons.addWidget(dash)

        layout = QVBoxLayout(self)
        layout.addWidget(self.tree)
        layout.addLayout(buttons)

        self.tray = QSystemTrayIcon(self)
        self.tray.activated.connect(self.tray_clicked)
        menu = QMenu(self)
        for label, slot in (("Show Devices", self.bring_up),
                            ("Open Dashboard", open_dashboard),
                            (None, None),
                            ("Quit", QApplication.quit)):
            if label is None:
                menu.addSeparator()
            else:
                act = QAction(label, menu)
                act.triggered.connect(slot)
                menu.addAction(act)
        self.tray.setContextMenu(menu)
        self.tray.show()

        self.refresh()
        timer = QTimer(self)
        timer.timeout.connect(self.refresh)
        timer.start(REFRESH_MS)

    def set_tray(self, up, tip):
        self.tray.setIcon(QIcon.fromTheme(ICON_ON if up else ICON_OFF))
        self.tray.setToolTip(tip)

    def refresh(self):
        try:
            state, devices = load_status()
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as e:
            self.set_tray(False, "Tailscale: not running")
            self.info.setText(f"Couldn't read tailscale status: {e}")
            self.tree.clear()
            return
        up = state == "Running"
        online = sum(d["online"] for d in devices)
        self.set_tray(up, f"Tailscale: connected · {online}/{len(devices)} online"
                      if up else f"Tailscale: {state.lower()}")
        if not self.isVisible():
            return
        self.tree.clear()
        grey = QBrush(QColor(self.palette().placeholderText().color()))
        green = QBrush(QColor("#3daa5c"))
        for d in devices:
            item = QTreeWidgetItem([d["name"], d["ip"], d["os"], d["status"]])
            item.setData(1, Qt.ItemDataRole.UserRole, d["ip"])
            if d["online"]:
                item.setForeground(3, green)
            else:
                for col in range(4):
                    item.setForeground(col, grey)
            self.tree.addTopLevelItem(item)
        prefix = "" if up else f"Tailscale is {state.lower()} · "
        self.info.setText(f"{prefix}{online}/{len(devices)} online · double-click to copy IP")

    def copy_ip(self, item):
        QGuiApplication.clipboard().setText(item.data(1, Qt.ItemDataRole.UserRole))
        self.info.setText(f"Copied {item.data(1, Qt.ItemDataRole.UserRole)}")

    def bring_up(self):
        self.show()
        self.refresh()
        self.raise_()
        self.activateWindow()

    def tray_clicked(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            if self.isVisible():
                self.hide()
            else:
                self.bring_up()

    def closeEvent(self, event):
        # Closing the window just tucks it back into the tray.
        event.ignore()
        self.hide()


def open_dashboard():
    QDesktopServices.openUrl(QUrl(DASHBOARD_URL))


def main():
    app = QApplication(sys.argv)
    app.setDesktopFileName("tailnet-devices")
    app.setQuitOnLastWindowClosed(False)

    # Already running? Ask it to show its window and exit.
    sock = QLocalSocket()
    sock.connectToServer(SOCKET_NAME)
    if sock.waitForConnected(300):
        sock.write(b"show")
        sock.waitForBytesWritten(300)
        return 0

    QLocalServer.removeServer(SOCKET_NAME)
    server = QLocalServer()
    server.listen(SOCKET_NAME)

    w = Window()
    server.newConnection.connect(lambda: (server.nextPendingConnection(), w.bring_up()))
    if "--hidden" not in sys.argv:
        w.bring_up()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
