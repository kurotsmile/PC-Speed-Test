#!/usr/bin/env python3
"""CLI tool to inspect system details and run lightweight speed tests."""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except ImportError:  # pragma: no cover - optional GUI path
    tk = None
    filedialog = None
    messagebox = None
    ttk = None

try:
    import psutil  # type: ignore
except ImportError:  # pragma: no cover - fallback path is intentional
    psutil = None


AUTO_REFRESH_MS = 3000


@dataclass
class Benchmarks:
    cpu_loop_seconds: float | None
    cpu_loop_ops_per_sec: float | None
    memory_copy_mb_s: float | None
    disk_write_mb_s: float | None
    disk_read_mb_s: float | None
    file_ops_per_sec: float | None
    tcp_latency_ms: float | None


def run_command(cmd: list[str]) -> str:
    try:
        result = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return ""
    return result.stdout.strip()


def human_bytes(num_bytes: float) -> str:
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    size = float(num_bytes)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} PB"


def format_seconds(seconds: float) -> str:
    seconds = max(0, int(seconds))
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours or days:
        parts.append(f"{hours}h")
    if minutes or hours or days:
        parts.append(f"{minutes}m")
    parts.append(f"{secs}s")
    return " ".join(parts)


def get_cpu_name() -> str:
    system = platform.system()
    if system == "Darwin":
        hardware = run_command(["system_profiler", "SPHardwareDataType"])
        for line in hardware.splitlines():
            stripped = line.strip()
            if stripped.startswith("Chip:"):
                return stripped.split(":", 1)[1].strip()
        value = run_command(["sysctl", "-n", "machdep.cpu.brand_string"])
        if value:
            return value
    if system == "Linux":
        try:
            with open("/proc/cpuinfo", "r", encoding="utf-8") as handle:
                for line in handle:
                    if line.lower().startswith("model name"):
                        return line.split(":", 1)[1].strip()
        except OSError:
            pass
    if system == "Windows":
        value = run_command(["wmic", "cpu", "get", "name"])
        lines = [line.strip() for line in value.splitlines() if line.strip() and "Name" not in line]
        if lines:
            return lines[0]
    return platform.processor() or "Unknown CPU"


def get_gpu_name() -> str:
    system = platform.system()
    if system == "Darwin":
        value = run_command(["system_profiler", "SPDisplaysDataType"])
        for line in value.splitlines():
            stripped = line.strip()
            if stripped.startswith("Chipset Model:"):
                return stripped.split(":", 1)[1].strip()
    if system == "Linux":
        value = run_command(["lspci"])
        for line in value.splitlines():
            lower = line.lower()
            if "vga compatible controller" in lower or "3d controller" in lower:
                return line.split(":", 2)[-1].strip()
    if system == "Windows":
        value = run_command(["wmic", "path", "win32_VideoController", "get", "name"])
        lines = [line.strip() for line in value.splitlines() if line.strip() and "Name" not in line]
        if lines:
            return lines[0]
    return "Unknown GPU"


def get_ip_addresses() -> list[str]:
    addresses: list[str] = []
    hostname = socket.gethostname()
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return addresses
    for info in infos:
        addr = info[4][0]
        if addr not in addresses and not addr.startswith("127.") and addr != "::1":
            addresses.append(addr)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            addr = sock.getsockname()[0]
            if addr not in addresses and not addr.startswith("127."):
                addresses.append(addr)
    except OSError:
        pass
    return addresses


def get_total_memory_fallback() -> int | None:
    system = platform.system()
    if system == "Darwin":
        value = run_command(["sysctl", "-n", "hw.memsize"])
        if value.isdigit():
            return int(value)
    if hasattr(os, "sysconf") and "SC_PAGE_SIZE" in os.sysconf_names and "SC_PHYS_PAGES" in os.sysconf_names:
        try:
            page_size = os.sysconf("SC_PAGE_SIZE")
            total_pages = os.sysconf("SC_PHYS_PAGES")
            if isinstance(page_size, int) and isinstance(total_pages, int):
                return page_size * total_pages
        except (OSError, ValueError):
            pass
    return None


def gather_basic_info() -> dict[str, Any]:
    uname = platform.uname()
    info: dict[str, Any] = {
        "hostname": socket.gethostname(),
        "os": f"{uname.system} {uname.release}",
        "os_version": uname.version,
        "machine": uname.machine,
        "architecture": platform.architecture()[0],
        "python": sys.version.split()[0],
        "cpu": {
            "model": get_cpu_name(),
            "physical_cores": os.cpu_count() or 0,
            "logical_cores": os.cpu_count() or 0,
        },
        "gpu": get_gpu_name(),
        "network": {"ip_addresses": get_ip_addresses()},
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }

    if psutil:
        try:
            freq = psutil.cpu_freq()
        except Exception:
            freq = None
        try:
            info["cpu"]["physical_cores"] = psutil.cpu_count(logical=False) or 0
            info["cpu"]["logical_cores"] = psutil.cpu_count(logical=True) or 0
            info["cpu"]["usage_percent"] = psutil.cpu_percent(interval=0.3)
        except Exception:
            pass
        if freq:
            info["cpu"]["current_freq_mhz"] = round(freq.current, 2)
            info["cpu"]["max_freq_mhz"] = round(freq.max, 2)

        try:
            vm = psutil.virtual_memory()
        except Exception:
            vm = None
        try:
            sm = psutil.swap_memory()
        except Exception:
            sm = None
        if vm:
            info["memory"] = {
                "total": vm.total,
                "available": vm.available,
                "used": vm.used,
                "usage_percent": vm.percent,
                "swap_total": sm.total if sm else 0,
                "swap_used": sm.used if sm else 0,
                "swap_percent": sm.percent if sm else 0,
            }

        try:
            du = psutil.disk_usage(str(Path.home()))
            info["disk"] = {
                "path": str(Path.home()),
                "total": du.total,
                "used": du.used,
                "free": du.free,
                "usage_percent": du.percent,
            }
        except Exception:
            pass

        try:
            net = psutil.net_io_counters()
        except Exception:
            net = None
        if net:
            info["network"].update(
                {
                    "bytes_sent": net.bytes_sent,
                    "bytes_recv": net.bytes_recv,
                    "packets_sent": net.packets_sent,
                    "packets_recv": net.packets_recv,
                }
            )

        try:
            boot_timestamp = psutil.boot_time()
            boot_time = datetime.fromtimestamp(boot_timestamp)
            info["uptime_seconds"] = time.time() - boot_timestamp
            info["boot_time"] = boot_time.isoformat(timespec="seconds")
        except Exception:
            pass
        try:
            info["process_count"] = len(psutil.pids())
        except Exception:
            pass

        try:
            battery = psutil.sensors_battery()
        except Exception:
            battery = None
        if battery:
            info["battery"] = {
                "percent": battery.percent,
                "plugged": battery.power_plugged,
                "time_left_seconds": battery.secsleft if battery.secsleft >= 0 else None,
            }
    else:
        total_memory = get_total_memory_fallback()
        if total_memory:
            info["memory"] = {"total": total_memory}
        usage = shutil.disk_usage(Path.home())
        info["disk"] = {
            "path": str(Path.home()),
            "total": usage.total,
            "used": usage.used,
            "free": usage.free,
            "usage_percent": round((usage.used / usage.total) * 100, 2) if usage.total else 0,
        }

    return info


def run_cpu_benchmark(duration: float = 1.5) -> tuple[float, float]:
    iterations = 0
    start = time.perf_counter()
    while True:
        iterations += 1
        math.sqrt(iterations * 12345.6789)
        if time.perf_counter() - start >= duration:
            break
    elapsed = time.perf_counter() - start
    return elapsed, iterations / elapsed


def run_disk_benchmark(file_size_mb: int = 64) -> tuple[float, float]:
    chunk = b"x" * (1024 * 1024)
    chunks = [chunk] * file_size_mb

    with tempfile.NamedTemporaryFile(delete=False) as handle:
        tmp_path = Path(handle.name)

    try:
        start = time.perf_counter()
        with open(tmp_path, "wb") as handle:
            for data in chunks:
                handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        write_elapsed = time.perf_counter() - start

        start = time.perf_counter()
        with open(tmp_path, "rb") as handle:
            while handle.read(1024 * 1024):
                pass
        read_elapsed = time.perf_counter() - start
    finally:
        tmp_path.unlink(missing_ok=True)

    write_speed = file_size_mb / write_elapsed if write_elapsed else 0.0
    read_speed = file_size_mb / read_elapsed if read_elapsed else 0.0
    return write_speed, read_speed


def run_memory_benchmark(buffer_size_mb: int = 64, rounds: int = 8) -> float:
    source = bytearray(os.urandom(buffer_size_mb * 1024 * 1024))
    start = time.perf_counter()
    for _ in range(rounds):
        target = source[:]
        if target[0] == 256:  # pragma: no cover - impossible guard to keep the copy alive
            raise RuntimeError("Unreachable state")
    elapsed = time.perf_counter() - start
    total_mb = buffer_size_mb * rounds
    return total_mb / elapsed if elapsed else 0.0


def run_file_ops_benchmark(file_count: int = 200) -> float:
    start = time.perf_counter()
    with tempfile.TemporaryDirectory() as tmp_dir:
        base = Path(tmp_dir)
        for index in range(file_count):
            path = base / f"bench_{index}.tmp"
            path.write_text("pc-speed-test", encoding="utf-8")
        for index in range(file_count):
            path = base / f"bench_{index}.tmp"
            path.unlink(missing_ok=True)
    elapsed = time.perf_counter() - start
    total_ops = file_count * 2
    return total_ops / elapsed if elapsed else 0.0


def run_tcp_latency_benchmark(
    host: str = "1.1.1.1",
    port: int = 443,
    timeout: float = 0.35,
) -> float | None:
    start = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            pass
    except OSError:
        return None
    elapsed = time.perf_counter() - start
    return elapsed * 1000.0


def gather_benchmarks(enable: bool) -> Benchmarks:
    if not enable:
        return Benchmarks(None, None, None, None, None, None, None)

    cpu_elapsed, cpu_ops = run_cpu_benchmark()
    memory_speed = run_memory_benchmark()
    disk_write, disk_read = run_disk_benchmark()
    file_ops = run_file_ops_benchmark()
    tcp_latency = run_tcp_latency_benchmark()
    return Benchmarks(
        cpu_loop_seconds=round(cpu_elapsed, 3),
        cpu_loop_ops_per_sec=round(cpu_ops, 2),
        memory_copy_mb_s=round(memory_speed, 2),
        disk_write_mb_s=round(disk_write, 2),
        disk_read_mb_s=round(disk_read, 2),
        file_ops_per_sec=round(file_ops, 2),
        tcp_latency_ms=round(tcp_latency, 2) if tcp_latency is not None else None,
    )


def render_text_report(info: dict[str, Any], benchmarks: Benchmarks) -> str:
    lines: list[str] = []

    lines.append("=== PC SPEED TEST REPORT ===")
    lines.append(f"Time: {info['timestamp']}")
    lines.append(f"Host: {info['hostname']}")
    lines.append(f"OS: {info['os']}")
    lines.append(f"OS Version: {info['os_version']}")
    lines.append(f"Machine: {info['machine']} ({info['architecture']})")
    lines.append(f"Python: {info['python']}")
    lines.append("")

    cpu = info["cpu"]
    lines.append("[CPU]")
    lines.append(f"Model: {cpu['model']}")
    lines.append(f"Cores: {cpu['physical_cores']} physical / {cpu['logical_cores']} logical")
    if "usage_percent" in cpu:
        lines.append(f"Current Usage: {cpu['usage_percent']}%")
    if "current_freq_mhz" in cpu:
        lines.append(f"Frequency: {cpu['current_freq_mhz']} MHz (max {cpu['max_freq_mhz']} MHz)")
    lines.append("")

    lines.append("[GPU]")
    lines.append(f"Model: {info['gpu']}")
    lines.append("")

    if "memory" in info:
        memory = info["memory"]
        lines.append("[MEMORY]")
        if "used" in memory:
            lines.append(
                f"RAM: {human_bytes(memory['used'])} used / {human_bytes(memory['total'])} total "
                f"({memory['usage_percent']}%)"
            )
            lines.append(
                f"Available: {human_bytes(memory['available'])} | "
                f"Swap: {human_bytes(memory['swap_used'])} / {human_bytes(memory['swap_total'])} "
                f"({memory['swap_percent']}%)"
            )
        else:
            lines.append(f"RAM Total: {human_bytes(memory['total'])}")
        lines.append("")

    disk = info["disk"]
    lines.append("[DISK]")
    lines.append(f"Path: {disk['path']}")
    lines.append(
        f"Usage: {human_bytes(disk['used'])} used / {human_bytes(disk['total'])} total "
        f"({disk['usage_percent']}%)"
    )
    lines.append(f"Free: {human_bytes(disk['free'])}")
    lines.append("")

    network = info["network"]
    lines.append("[NETWORK]")
    lines.append("IP: " + (", ".join(network.get("ip_addresses", [])) or "Not detected"))
    if "bytes_sent" in network:
        lines.append(
            f"Traffic: sent {human_bytes(network['bytes_sent'])}, "
            f"received {human_bytes(network['bytes_recv'])}"
        )
        lines.append(
            f"Packets: sent {network['packets_sent']}, received {network['packets_recv']}"
        )
    lines.append("")

    if "boot_time" in info:
        lines.append("[SYSTEM]")
        lines.append(f"Boot Time: {info['boot_time']}")
        lines.append(f"Uptime: {format_seconds(info['uptime_seconds'])}")
        lines.append(f"Processes: {info['process_count']}")
        if "battery" in info:
            battery = info["battery"]
            battery_line = f"Battery: {battery['percent']}% | Plugged in: {battery['plugged']}"
            if battery["time_left_seconds"] is not None:
                battery_line += f" | Time left: {format_seconds(battery['time_left_seconds'])}"
            lines.append(battery_line)
        lines.append("")

    lines.append("[BENCHMARK]")
    if benchmarks.cpu_loop_seconds is None:
        lines.append("Skipped. Run with --benchmark to execute active speed tests.")
    else:
        lines.append(
            f"CPU loop: {benchmarks.cpu_loop_ops_per_sec:,.2f} ops/s "
            f"(sample window {benchmarks.cpu_loop_seconds}s)"
        )
        lines.append(f"Memory copy: {benchmarks.memory_copy_mb_s} MB/s")
        lines.append(f"Disk write: {benchmarks.disk_write_mb_s} MB/s")
        lines.append(f"Disk read: {benchmarks.disk_read_mb_s} MB/s")
        lines.append(f"File ops: {benchmarks.file_ops_per_sec:,.2f} ops/s")
        if benchmarks.tcp_latency_ms is None:
            lines.append("TCP latency: unavailable")
        else:
            lines.append(f"TCP latency: {benchmarks.tcp_latency_ms} ms")

    if not psutil:
        lines.append("")
        lines.append("Note: install 'psutil' for deeper metrics: pip install psutil")

    return "\n".join(lines)


def build_sections(info: dict[str, Any], benchmarks: Benchmarks) -> list[tuple[str, list[tuple[str, str]]]]:
    cpu = info["cpu"]
    sections: list[tuple[str, list[tuple[str, str]]]] = [
        (
            "Overview",
            [
                ("Time", info["timestamp"]),
                ("Host", info["hostname"]),
                ("OS", info["os"]),
                ("Machine", f"{info['machine']} ({info['architecture']})"),
                ("Python", info["python"]),
            ],
        ),
        (
            "CPU",
            [
                ("Model", cpu["model"]),
                ("Cores", f"{cpu['physical_cores']} physical / {cpu['logical_cores']} logical"),
            ],
        ),
        ("GPU", [("Model", info["gpu"])]),
    ]

    if "usage_percent" in cpu:
        sections[1][1].append(("Usage", f"{cpu['usage_percent']}%"))
    if "current_freq_mhz" in cpu:
        sections[1][1].append(
            ("Frequency", f"{cpu['current_freq_mhz']} MHz / max {cpu['max_freq_mhz']} MHz")
        )

    if "memory" in info:
        memory = info["memory"]
        memory_rows = [("Total", human_bytes(memory["total"]))]
        if "used" in memory:
            memory_rows.extend(
                [
                    ("Used", f"{human_bytes(memory['used'])} ({memory['usage_percent']}%)"),
                    ("Available", human_bytes(memory["available"])),
                    (
                        "Swap",
                        f"{human_bytes(memory['swap_used'])} / {human_bytes(memory['swap_total'])} "
                        f"({memory['swap_percent']}%)",
                    ),
                ]
            )
        sections.append(("Memory", memory_rows))

    disk = info["disk"]
    sections.append(
        (
            "Disk",
            [
                ("Path", disk["path"]),
                ("Usage", f"{disk['usage_percent']}% used"),
                ("Available Space", human_bytes(disk["free"])),
            ],
        )
    )

    network = info["network"]
    network_rows = [("IP", ", ".join(network.get("ip_addresses", [])) or "Not detected")]
    if "bytes_sent" in network:
        network_rows.extend(
            [
                ("Sent", human_bytes(network["bytes_sent"])),
                ("Received", human_bytes(network["bytes_recv"])),
                ("Packets", f"{network['packets_sent']} sent / {network['packets_recv']} recv"),
            ]
        )
    sections.append(("Network", network_rows))

    if "boot_time" in info:
        system_rows = [
            ("Boot Time", info["boot_time"]),
            ("Uptime", format_seconds(info["uptime_seconds"])),
            ("Processes", str(info["process_count"])),
        ]
        if "battery" in info:
            battery = info["battery"]
            battery_text = f"{battery['percent']}% | Plugged: {battery['plugged']}"
            if battery["time_left_seconds"] is not None:
                battery_text += f" | {format_seconds(battery['time_left_seconds'])} left"
            system_rows.append(("Battery", battery_text))
        sections.append(("System", system_rows))

    benchmark_rows: list[tuple[str, str]]
    if benchmarks.cpu_loop_seconds is None:
        benchmark_rows = [("Status", "Skipped. Run benchmark to collect active speed tests.")]
    else:
        benchmark_rows = [
            (
                "CPU Loop",
                f"{benchmarks.cpu_loop_ops_per_sec:,.2f} ops/s ({benchmarks.cpu_loop_seconds}s)",
            ),
            ("Memory Copy", f"{benchmarks.memory_copy_mb_s} MB/s"),
            ("Disk Write", f"{benchmarks.disk_write_mb_s} MB/s"),
            ("Disk Read", f"{benchmarks.disk_read_mb_s} MB/s"),
            ("File Ops", f"{benchmarks.file_ops_per_sec:,.2f} ops/s"),
            (
                "TCP Latency",
                "Unavailable"
                if benchmarks.tcp_latency_ms is None
                else f"{benchmarks.tcp_latency_ms} ms",
            ),
        ]
    sections.append(("Benchmark", benchmark_rows))

    if not psutil:
        sections.append(
            (
                "Notes",
                [("Optional", "Install psutil for deeper live metrics when network is available.")],
            )
        )

    return sections


def launch_gui(run_benchmark_on_start: bool) -> int:
    if tk is None or ttk is None:
        print("GUI is not available because tkinter is not installed.")
        return 1

    root = tk.Tk()
    root.title("PC Speed Test Dashboard")
    root.geometry("1420x860")
    root.minsize(1220, 720)
    root.configure(bg="#09111f")

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    palette = {
        "bg": "#09111f",
        "panel": "#122033",
        "panel_alt": "#0f1a2b",
        "text": "#eef4ff",
        "muted": "#9fb1c9",
        "accent": "#38bdf8",
        "accent_alt": "#0ea5e9",
        "line": "#1f3550",
    }

    style.configure("App.TFrame", background=palette["bg"])
    style.configure("CardOuter.TFrame", background=palette["panel"])
    style.configure("Card.TFrame", background=palette["panel"])
    style.configure("Header.TFrame", background=palette["bg"])
    style.configure(
        "CardTitle.TLabel",
        background=palette["panel"],
        foreground=palette["accent"],
        font=("Helvetica", 12, "bold"),
    )
    style.configure(
        "Title.TLabel",
        background=palette["bg"],
        foreground=palette["text"],
        font=("Helvetica", 22, "bold"),
    )
    style.configure(
        "Subtitle.TLabel",
        background=palette["bg"],
        foreground=palette["muted"],
        font=("Helvetica", 10),
    )
    style.configure(
        "LabelKey.TLabel",
        background=palette["panel"],
        foreground=palette["muted"],
        font=("Helvetica", 10, "bold"),
    )
    style.configure(
        "LabelValue.TLabel",
        background=palette["panel"],
        foreground=palette["text"],
        font=("Helvetica", 10),
    )
    style.configure(
        "Status.TLabel",
        background=palette["bg"],
        foreground=palette["muted"],
        font=("Helvetica", 10),
    )
    style.configure(
        "Primary.TButton",
        background=palette["accent"],
        foreground="#04111d",
        borderwidth=0,
        focusthickness=0,
        focuscolor=palette["accent"],
        padding=(14, 8),
        font=("Helvetica", 10, "bold"),
    )
    style.map(
        "Primary.TButton",
        background=[("active", palette["accent_alt"]), ("pressed", palette["accent_alt"])],
    )
    style.configure(
        "Secondary.TButton",
        background=palette["panel"],
        foreground=palette["text"],
        borderwidth=1,
        relief="solid",
        padding=(12, 8),
        font=("Helvetica", 10, "bold"),
    )
    style.map(
        "Secondary.TButton",
        background=[("active", palette["panel_alt"]), ("pressed", palette["panel_alt"])],
    )
    style.configure(
        "App.Vertical.TScrollbar",
        background=palette["panel_alt"],
        troughcolor=palette["bg"],
        arrowcolor=palette["accent"],
        bordercolor=palette["bg"],
        darkcolor=palette["bg"],
        lightcolor=palette["bg"],
        gripcount=0,
        relief="flat",
        width=12,
    )
    style.map(
        "App.Vertical.TScrollbar",
        background=[
            ("active", palette["panel"]),
            ("pressed", palette["accent_alt"]),
        ],
    )

    root.columnconfigure(0, weight=1)
    root.rowconfigure(1, weight=1)

    header = ttk.Frame(root, style="Header.TFrame", padding=(20, 18, 20, 8))
    header.grid(row=0, column=0, sticky="ew")
    header.columnconfigure(0, weight=1)

    ttk.Label(header, text="PC Speed Test Dashboard", style="Title.TLabel").grid(
        row=0, column=0, sticky="w"
    )
    subtitle_var = tk.StringVar(value="Grouped hardware panels with live refresh and benchmark.")
    ttk.Label(header, textvariable=subtitle_var, style="Subtitle.TLabel").grid(
        row=1, column=0, sticky="w", pady=(4, 0)
    )

    controls = ttk.Frame(header, style="Header.TFrame")
    controls.grid(row=0, column=1, rowspan=2, sticky="e")

    viewport = ttk.Frame(root, style="App.TFrame", padding=(20, 8, 20, 8))
    viewport.grid(row=1, column=0, sticky="nsew")
    viewport.columnconfigure(0, weight=1)
    viewport.rowconfigure(0, weight=1)

    content_canvas = tk.Canvas(
        viewport,
        bg=palette["bg"],
        highlightthickness=0,
        bd=0,
    )
    content_canvas.grid(row=0, column=0, sticky="nsew")

    auto_refresh_paused_for_scroll = False

    def update_scroll_pause_state() -> None:
        nonlocal auto_refresh_paused_for_scroll
        current_view = content_canvas.yview()
        auto_refresh_paused_for_scroll = bool(current_view and current_view[0] > 0.01)

    def on_scrollbar(*args: str) -> None:
        content_canvas.yview(*args)
        update_scroll_pause_state()

    scroll_bar = ttk.Scrollbar(
        viewport,
        orient="vertical",
        command=on_scrollbar,
        style="App.Vertical.TScrollbar",
    )
    scroll_bar.grid(row=0, column=1, sticky="ns")
    content_canvas.configure(yscrollcommand=scroll_bar.set)

    content = ttk.Frame(content_canvas, style="App.TFrame")
    content_window = content_canvas.create_window((0, 0), window=content, anchor="nw")
    for column in range(2):
        content.columnconfigure(column, weight=1)

    def sync_content_width(event: tk.Event) -> None:
        content_canvas.itemconfigure(content_window, width=max(event.width, 1160))

    def update_scroll_region() -> None:
        content_canvas.configure(scrollregion=content_canvas.bbox("all"))

    content_canvas.bind("<Configure>", sync_content_width)
    content.bind("<Configure>", lambda _event: update_scroll_region())

    def on_mousewheel(event: tk.Event) -> None:
        if getattr(event, "delta", 0):
            raw_delta = int(event.delta)
            step = -1 if raw_delta > 0 else 1
            if abs(raw_delta) >= 120:
                step = int(-raw_delta / 120)
            content_canvas.yview_scroll(step, "units")
            update_scroll_pause_state()
            return
        if getattr(event, "num", None) == 4:
            content_canvas.yview_scroll(-1, "units")
        elif getattr(event, "num", None) == 5:
            content_canvas.yview_scroll(1, "units")
        update_scroll_pause_state()

    content_canvas.bind_all("<MouseWheel>", on_mousewheel)
    content_canvas.bind_all("<Button-4>", on_mousewheel)
    content_canvas.bind_all("<Button-5>", on_mousewheel)

    def capture_screenshot() -> None:
        if filedialog is None or messagebox is None:
            status_var.set("Screenshot dialogs are unavailable in this environment.")
            return

        default_name = f"pc_speed_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        selected_path = filedialog.asksaveasfilename(
            title="Save Dashboard Screenshot",
            defaultextension=".png",
            initialfile=default_name,
            filetypes=[("PNG image", "*.png")],
        )
        if not selected_path:
            return

        target_path = Path(selected_path)
        if target_path.suffix.lower() != ".png":
            target_path = target_path.with_suffix(".png")

        root.update_idletasks()
        x = root.winfo_rootx()
        y = root.winfo_rooty()
        width = root.winfo_width()
        height = root.winfo_height()

        system = platform.system()
        error_message = ""
        success = False
        try:
            if system == "Darwin":
                result = subprocess.run(
                    [
                        "screencapture",
                        "-x",
                        f"-R{x},{y},{width},{height}",
                        str(target_path),
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                success = result.returncode == 0
                error_message = result.stderr.strip()
            else:
                error_message = "Screenshot capture is currently implemented for macOS."
        except OSError as exc:
            error_message = str(exc)

        if success:
            status_var.set(f"Screenshot saved: {target_path}")
            messagebox.showinfo("Screenshot Saved", f"Saved to:\n{target_path}")
        else:
            status_var.set("Failed to save screenshot.")
            messagebox.showerror("Screenshot Failed", error_message or "Could not save screenshot.")

    status_var = tk.StringVar(value="Ready.")
    ttk.Label(root, textvariable=status_var, style="Status.TLabel").grid(
        row=2, column=0, sticky="ew", padx=20, pady=(0, 16)
    )

    panel_frames: list[ttk.Frame] = []
    memory_history: list[float] = []
    refresh_in_progress = False
    auto_refresh_job: str | None = None

    def render_disk_panel(
        panel_body: ttk.Frame,
        rows: list[tuple[str, str]],
        disk_info: dict[str, Any],
    ) -> None:
        panel_body.columnconfigure(1, weight=1)

        chart_wrap = ttk.Frame(panel_body, style="Card.TFrame")
        chart_wrap.grid(row=0, column=0, sticky="nw", padx=(0, 16), pady=2)
        chart_wrap.columnconfigure(1, weight=1)

        canvas = tk.Canvas(
            chart_wrap,
            width=180,
            height=180,
            bg=palette["panel"],
            highlightthickness=0,
            bd=0,
        )
        canvas.grid(row=0, column=0, sticky="n")

        used = float(disk_info.get("used", 0))
        free = float(disk_info.get("free", 0))
        total = float(disk_info.get("total", 0))
        if total <= 0:
            total = max(used + free, 1.0)

        used_extent = max(0.0, min(359.9, (used / total) * 360.0))
        radius_box = (18, 18, 162, 162)
        arc_width = 26
        used_color = "#38bdf8"
        free_color = "#22c55e"
        total_color = "#94a3b8"

        canvas.create_oval(*radius_box, outline=palette["line"], width=arc_width)
        if free > 0:
            canvas.create_arc(
                *radius_box,
                start=90,
                extent=-(360.0 - used_extent),
                style="arc",
                outline=free_color,
                width=arc_width,
            )
        if used > 0:
            canvas.create_arc(
                *radius_box,
                start=90,
                extent=-used_extent,
                style="arc",
                outline=used_color,
                width=arc_width,
            )

        canvas.create_text(
            90,
            78,
            text="TOTAL",
            fill=palette["muted"],
            font=("Helvetica", 10, "bold"),
        )
        canvas.create_text(
            90,
            102,
            text=human_bytes(total),
            fill=palette["text"],
            font=("Helvetica", 13, "bold"),
        )

        legend = ttk.Frame(chart_wrap, style="Card.TFrame")
        legend.grid(row=0, column=1, sticky="nw", padx=(14, 0), pady=(8, 0))
        legend_items = [
            ("Used", used_color, f"{human_bytes(used)} ({disk_info.get('usage_percent', 0)}%)"),
            ("Free", free_color, human_bytes(free)),
            ("Total", total_color, human_bytes(total)),
        ]
        for row_index, (label, color, value) in enumerate(legend_items):
            dot = tk.Canvas(
                legend,
                width=10,
                height=10,
                bg=palette["panel"],
                highlightthickness=0,
                bd=0,
            )
            dot.grid(row=row_index, column=0, sticky="w", padx=(0, 8), pady=3)
            dot.create_oval(1, 1, 9, 9, fill=color, outline=color)
            ttk.Label(legend, text=label, style="LabelKey.TLabel").grid(
                row=row_index, column=1, sticky="w", pady=3
            )
            ttk.Label(legend, text=value, style="LabelValue.TLabel").grid(
                row=row_index, column=2, sticky="w", padx=(10, 0), pady=3
            )

        details = ttk.Frame(panel_body, style="Card.TFrame")
        details.grid(row=0, column=1, sticky="nsew")
        details.columnconfigure(1, weight=1)
        for row_index, (key, value) in enumerate(rows):
            ttk.Label(details, text=key, style="LabelKey.TLabel").grid(
                row=row_index,
                column=0,
                sticky="nw",
                padx=(0, 12),
                pady=4,
            )
            ttk.Label(
                details,
                text=value,
                style="LabelValue.TLabel",
                justify="left",
                wraplength=340,
            ).grid(row=row_index, column=1, sticky="nw", pady=4)

    def render_key_value_rows(
        parent: ttk.Frame,
        rows: list[tuple[str, str]],
        wraplength: int = 340,
    ) -> None:
        parent.columnconfigure(1, weight=1)
        for row_index, (key, value) in enumerate(rows):
            ttk.Label(parent, text=key, style="LabelKey.TLabel").grid(
                row=row_index,
                column=0,
                sticky="nw",
                padx=(0, 12),
                pady=4,
            )
            ttk.Label(
                parent,
                text=value,
                style="LabelValue.TLabel",
                justify="left",
                wraplength=wraplength,
            ).grid(row=row_index, column=1, sticky="nw", pady=4)

    def draw_meter(
        canvas: tk.Canvas,
        y: float,
        label: str,
        ratio: float,
        value_text: str,
        fill_color: str,
        width: int = 300,
    ) -> None:
        ratio = max(0.0, min(ratio, 1.0))
        x1 = 16
        x2 = x1 + width
        canvas.create_text(x1, y - 10, text=label, fill=palette["muted"], font=("Helvetica", 9, "bold"), anchor="w")
        canvas.create_rectangle(x1, y, x2, y + 14, fill=palette["panel_alt"], outline=palette["line"], width=1)
        canvas.create_rectangle(x1, y, x1 + (width * ratio), y + 14, fill=fill_color, outline=fill_color, width=1)
        canvas.create_text(x2, y - 10, text=value_text, fill=palette["text"], font=("Helvetica", 9), anchor="e")

    def render_memory_panel(
        panel_body: ttk.Frame,
        rows: list[tuple[str, str]],
        memory_info: dict[str, Any],
    ) -> None:
        panel_body.columnconfigure(1, weight=1)

        chart_wrap = ttk.Frame(panel_body, style="Card.TFrame")
        chart_wrap.grid(row=0, column=0, sticky="nw", padx=(0, 16), pady=2)

        chart = tk.Canvas(
            chart_wrap,
            width=320,
            height=180,
            bg=palette["panel"],
            highlightthickness=0,
            bd=0,
        )
        chart.grid(row=0, column=0, sticky="n")

        chart_width = 320
        chart_height = 180
        left_pad = 18
        right_pad = 10
        top_pad = 12
        bottom_pad = 24
        plot_width = chart_width - left_pad - right_pad
        plot_height = chart_height - top_pad - bottom_pad

        chart.create_rectangle(
            left_pad,
            top_pad,
            left_pad + plot_width,
            top_pad + plot_height,
            outline=palette["line"],
            width=1,
        )

        for marker in (25, 50, 75):
            y = top_pad + plot_height - (marker / 100.0) * plot_height
            chart.create_line(
                left_pad,
                y,
                left_pad + plot_width,
                y,
                fill=palette["line"],
                width=1,
                dash=(3, 3),
            )
            chart.create_text(
                10,
                y,
                text=f"{marker}%",
                fill=palette["muted"],
                font=("Helvetica", 8),
            )

        if len(memory_history) >= 2:
            points: list[float] = []
            denominator = max(len(memory_history) - 1, 1)
            for index, value in enumerate(memory_history):
                x = left_pad + (index / denominator) * plot_width
                y = top_pad + plot_height - (max(0.0, min(value, 100.0)) / 100.0) * plot_height
                points.extend([x, y])
            chart.create_line(
                *points,
                fill=palette["accent"],
                width=3,
                smooth=True,
            )

        if memory_history:
            latest = memory_history[-1]
            marker_x = left_pad + plot_width
            marker_y = top_pad + plot_height - (max(0.0, min(latest, 100.0)) / 100.0) * plot_height
            chart.create_oval(
                marker_x - 4,
                marker_y - 4,
                marker_x + 4,
                marker_y + 4,
                fill=palette["accent"],
                outline=palette["accent"],
            )
            chart.create_text(
                marker_x - 8,
                marker_y - 12,
                text=f"{latest:.1f}%",
                fill=palette["text"],
                font=("Helvetica", 9, "bold"),
                anchor="e",
            )

        chart.create_text(
            left_pad,
            chart_height - 8,
            text=f"Last {len(memory_history)} samples",
            fill=palette["muted"],
            font=("Helvetica", 8),
            anchor="w",
        )

        details = ttk.Frame(panel_body, style="Card.TFrame")
        details.grid(row=0, column=1, sticky="nsew")
        render_key_value_rows(details, rows)

    def render_overview_panel(
        panel_body: ttk.Frame,
        rows: list[tuple[str, str]],
        info: dict[str, Any],
    ) -> None:
        panel_body.columnconfigure(1, weight=1)
        chart_wrap = ttk.Frame(panel_body, style="Card.TFrame")
        chart_wrap.grid(row=0, column=0, sticky="nw", padx=(0, 16), pady=2)

        chart = tk.Canvas(chart_wrap, width=332, height=172, bg=palette["panel"], highlightthickness=0, bd=0)
        chart.grid(row=0, column=0, sticky="n")
        cpu_ratio = float(info.get("cpu", {}).get("usage_percent", 0.0)) / 100.0
        mem_ratio = float(info.get("memory", {}).get("usage_percent", 0.0)) / 100.0 if "memory" in info else 0.0
        disk_ratio = float(info.get("disk", {}).get("usage_percent", 0.0)) / 100.0
        draw_meter(chart, 36, "CPU Load", cpu_ratio, f"{cpu_ratio * 100:.1f}%", "#38bdf8")
        draw_meter(chart, 84, "Memory Use", mem_ratio, f"{mem_ratio * 100:.1f}%", "#22c55e")
        draw_meter(chart, 132, "Disk Use", disk_ratio, f"{disk_ratio * 100:.1f}%", "#f59e0b")

        details = ttk.Frame(panel_body, style="Card.TFrame")
        details.grid(row=0, column=1, sticky="nsew")
        render_key_value_rows(details, rows)

    def render_cpu_panel(
        panel_body: ttk.Frame,
        rows: list[tuple[str, str]],
        cpu_info: dict[str, Any],
    ) -> None:
        panel_body.columnconfigure(1, weight=1)
        chart_wrap = ttk.Frame(panel_body, style="Card.TFrame")
        chart_wrap.grid(row=0, column=0, sticky="nw", padx=(0, 16), pady=2)

        chart = tk.Canvas(chart_wrap, width=332, height=172, bg=palette["panel"], highlightthickness=0, bd=0)
        chart.grid(row=0, column=0, sticky="n")

        usage = float(cpu_info.get("usage_percent", 0.0))
        freq = float(cpu_info.get("current_freq_mhz", 0.0))
        max_freq = float(cpu_info.get("max_freq_mhz", 0.0))
        freq_ratio = (freq / max_freq) if max_freq > 0 else 0.0

        chart.create_oval(26, 20, 146, 140, outline=palette["line"], width=14)
        chart.create_arc(
            26,
            20,
            146,
            140,
            start=90,
            extent=-(usage * 3.6),
            style="arc",
            outline=palette["accent"],
            width=14,
        )
        chart.create_text(86, 68, text="CPU", fill=palette["muted"], font=("Helvetica", 10, "bold"))
        chart.create_text(86, 92, text=f"{usage:.1f}%", fill=palette["text"], font=("Helvetica", 16, "bold"))
        draw_meter(chart, 56, "Frequency", freq_ratio, f"{freq:.0f}/{max_freq:.0f} MHz" if max_freq else f"{freq:.0f} MHz", "#22c55e", width=140)
        draw_meter(
            chart,
            104,
            "Threads",
            min(float(cpu_info.get("logical_cores", 0)) / max(float(cpu_info.get("physical_cores", 1)) * 2.0, 1.0), 1.0),
            f"{cpu_info.get('logical_cores', 0)} logical",
            "#f59e0b",
            width=140,
        )

        details = ttk.Frame(panel_body, style="Card.TFrame")
        details.grid(row=0, column=1, sticky="nsew")
        render_key_value_rows(details, rows)

    def render_gpu_panel(
        panel_body: ttk.Frame,
        rows: list[tuple[str, str]],
        gpu_name: str,
    ) -> None:
        panel_body.columnconfigure(1, weight=1)
        chart_wrap = ttk.Frame(panel_body, style="Card.TFrame")
        chart_wrap.grid(row=0, column=0, sticky="nw", padx=(0, 16), pady=2)
        chart = tk.Canvas(chart_wrap, width=332, height=172, bg=palette["panel"], highlightthickness=0, bd=0)
        chart.grid(row=0, column=0, sticky="n")

        gpu_lower = gpu_name.lower()
        mode = "Unified" if "apple" in gpu_lower or "m1" in gpu_lower or "m2" in gpu_lower or "m3" in gpu_lower or "m4" in gpu_lower else "Integrated" if "intel" in gpu_lower or "iris" in gpu_lower or "uhd" in gpu_lower else "Discrete"
        segments = [("Integrated", "#38bdf8"), ("Discrete", "#f97316"), ("Unified", "#22c55e")]
        chart.create_text(16, 20, text="Graphics Class", fill=palette["muted"], font=("Helvetica", 9, "bold"), anchor="w")
        start_x = 16
        for label, color in segments:
            width = 96
            fill = color if label == mode else palette["panel_alt"]
            text_color = "#03111d" if label == mode else palette["muted"]
            chart.create_rectangle(start_x, 36, start_x + width, 68, fill=fill, outline=palette["line"], width=1)
            chart.create_text(start_x + (width / 2), 52, text=label, fill=text_color, font=("Helvetica", 9, "bold"))
            start_x += width + 8
        chart.create_rectangle(16, 92, 316, 142, fill=palette["panel_alt"], outline=palette["line"], width=1)
        chart.create_text(166, 108, text="GPU Identity", fill=palette["muted"], font=("Helvetica", 9, "bold"))
        chart.create_text(166, 128, text=gpu_name, fill=palette["text"], font=("Helvetica", 11, "bold"), width=280)

        details = ttk.Frame(panel_body, style="Card.TFrame")
        details.grid(row=0, column=1, sticky="nsew")
        render_key_value_rows(details, rows)

    def render_network_panel(
        panel_body: ttk.Frame,
        rows: list[tuple[str, str]],
        network_info: dict[str, Any],
    ) -> None:
        panel_body.columnconfigure(1, weight=1)
        chart_wrap = ttk.Frame(panel_body, style="Card.TFrame")
        chart_wrap.grid(row=0, column=0, sticky="nw", padx=(0, 16), pady=2)
        chart = tk.Canvas(chart_wrap, width=332, height=172, bg=palette["panel"], highlightthickness=0, bd=0)
        chart.grid(row=0, column=0, sticky="n")

        sent = float(network_info.get("bytes_sent", 0.0))
        recv = float(network_info.get("bytes_recv", 0.0))
        total = max(sent + recv, 1.0)
        packets_sent = float(network_info.get("packets_sent", 0.0))
        packets_recv = float(network_info.get("packets_recv", 0.0))
        packet_total = max(packets_sent + packets_recv, 1.0)
        draw_meter(chart, 36, "Traffic Sent", sent / total, human_bytes(sent), "#38bdf8")
        draw_meter(chart, 84, "Traffic Recv", recv / total, human_bytes(recv), "#22c55e")
        draw_meter(chart, 132, "Packet Mix", packets_recv / packet_total, f"{int(packets_recv)} recv", "#f59e0b")

        details = ttk.Frame(panel_body, style="Card.TFrame")
        details.grid(row=0, column=1, sticky="nsew")
        render_key_value_rows(details, rows)

    def render_system_panel(
        panel_body: ttk.Frame,
        rows: list[tuple[str, str]],
        info: dict[str, Any],
    ) -> None:
        panel_body.columnconfigure(1, weight=1)
        chart_wrap = ttk.Frame(panel_body, style="Card.TFrame")
        chart_wrap.grid(row=0, column=0, sticky="nw", padx=(0, 16), pady=2)
        chart = tk.Canvas(chart_wrap, width=332, height=172, bg=palette["panel"], highlightthickness=0, bd=0)
        chart.grid(row=0, column=0, sticky="n")

        uptime_seconds = float(info.get("uptime_seconds", 0.0))
        uptime_days = uptime_seconds / 86400.0
        uptime_ratio = min(uptime_days / 30.0, 1.0)
        draw_meter(chart, 36, "Uptime Window", uptime_ratio, f"{uptime_days:.1f} days", "#38bdf8")
        process_ratio = min(float(info.get("process_count", 0)) / 500.0, 1.0)
        draw_meter(chart, 84, "Process Load", process_ratio, str(info.get("process_count", 0)), "#22c55e")
        battery = info.get("battery")
        battery_ratio = (float(battery.get("percent", 0.0)) / 100.0) if isinstance(battery, dict) else 0.0
        battery_text = f"{battery.get('percent', 0)}%" if isinstance(battery, dict) else "N/A"
        draw_meter(chart, 132, "Battery", battery_ratio, battery_text, "#f59e0b")

        details = ttk.Frame(panel_body, style="Card.TFrame")
        details.grid(row=0, column=1, sticky="nsew")
        render_key_value_rows(details, rows)

    def render_benchmark_panel(
        panel_body: ttk.Frame,
        rows: list[tuple[str, str]],
        benchmarks: Benchmarks,
    ) -> None:
        panel_body.columnconfigure(1, weight=1)
        chart_wrap = ttk.Frame(panel_body, style="Card.TFrame")
        chart_wrap.grid(row=0, column=0, sticky="nw", padx=(0, 16), pady=2)
        chart = tk.Canvas(chart_wrap, width=332, height=206, bg=palette["panel"], highlightthickness=0, bd=0)
        chart.grid(row=0, column=0, sticky="n")

        metrics = [
            ("CPU", benchmarks.cpu_loop_ops_per_sec or 0.0, "#38bdf8"),
            ("Mem", benchmarks.memory_copy_mb_s or 0.0, "#22c55e"),
            ("Write", benchmarks.disk_write_mb_s or 0.0, "#f59e0b"),
            ("Read", benchmarks.disk_read_mb_s or 0.0, "#a78bfa"),
            ("Files", benchmarks.file_ops_per_sec or 0.0, "#f97316"),
        ]
        max_value = max((value for _, value, _ in metrics), default=1.0) or 1.0
        base_y = 182
        bar_width = 44
        gap = 16
        start_x = 18
        chart.create_line(14, base_y, 318, base_y, fill=palette["line"], width=1)
        for index, (label, value, color) in enumerate(metrics):
            x1 = start_x + index * (bar_width + gap)
            x2 = x1 + bar_width
            height = (value / max_value) * 128 if max_value else 0.0
            y1 = base_y - height
            chart.create_rectangle(x1, y1, x2, base_y, fill=color, outline=color)
            chart.create_text((x1 + x2) / 2, y1 - 10, text=f"{value:.0f}", fill=palette["muted"], font=("Helvetica", 8))
            chart.create_text((x1 + x2) / 2, base_y + 12, text=label, fill=palette["text"], font=("Helvetica", 8, "bold"))
        latency = "n/a" if benchmarks.tcp_latency_ms is None else f"{benchmarks.tcp_latency_ms} ms"
        chart.create_text(16, 18, text=f"TCP latency: {latency}", fill=palette["muted"], font=("Helvetica", 9), anchor="w")

        details = ttk.Frame(panel_body, style="Card.TFrame")
        details.grid(row=0, column=1, sticky="nsew")
        render_key_value_rows(details, rows)

    def render_payload(payload: dict[str, Any]) -> None:
        current_scroll = content_canvas.yview()
        top_pixel = max(content_canvas.canvasy(0), 0.0)
        for frame in panel_frames:
            frame.destroy()
        panel_frames.clear()

        info = payload["info"]
        benchmarks = Benchmarks(**payload["benchmarks"])
        sections = build_sections(info, benchmarks)
        memory = info.get("memory")
        if memory and "usage_percent" in memory:
            memory_history.append(float(memory["usage_percent"]))
            del memory_history[:-60]
        column_count = 2
        for column in range(2):
            content.columnconfigure(column, weight=1 if column < column_count else 0)

        for index, (title, rows) in enumerate(sections):
            panel = ttk.Frame(content, style="CardOuter.TFrame", padding=(14, 12))
            panel.grid(
                row=index // column_count,
                column=index % column_count,
                sticky="nsew",
                padx=8,
                pady=8,
            )
            content.rowconfigure(index // column_count, weight=1)
            panel_frames.append(panel)
            panel.columnconfigure(0, weight=1)
            panel.rowconfigure(1, weight=1)

            ttk.Label(panel, text=title, style="CardTitle.TLabel").grid(
                row=0,
                column=0,
                sticky="w",
                pady=(0, 10),
            )

            panel_body = ttk.Frame(panel, style="Card.TFrame")
            panel_body.grid(row=1, column=0, sticky="nsew")
            panel_body.columnconfigure(1, weight=1)

            if title == "Overview":
                render_overview_panel(panel_body, rows, info)
                continue
            if title == "CPU":
                render_cpu_panel(panel_body, rows, info["cpu"])
                continue
            if title == "GPU":
                render_gpu_panel(panel_body, rows, info["gpu"])
                continue
            if title == "Disk":
                render_disk_panel(panel_body, rows, info["disk"])
                continue
            if title == "Memory" and memory and "usage_percent" in memory:
                render_memory_panel(panel_body, rows, memory)
                continue
            if title == "Network":
                render_network_panel(panel_body, rows, info["network"])
                continue
            if title == "System":
                render_system_panel(panel_body, rows, info)
                continue
            if title == "Benchmark":
                render_benchmark_panel(panel_body, rows, benchmarks)
                continue

            render_key_value_rows(panel_body, rows, wraplength=420)

        update_scroll_region()

        def restore_scroll_position() -> None:
            bbox = content_canvas.bbox("all")
            if not bbox:
                return
            content_height = max(float(bbox[3] - bbox[1]), 0.0)
            viewport_height = float(content_canvas.winfo_height())
            scrollable_height = max(content_height - viewport_height, 0.0)
            if scrollable_height <= 0:
                content_canvas.yview_moveto(0.0)
                return

            if top_pixel > 0:
                target_fraction = min(top_pixel / scrollable_height, 1.0)
            elif current_scroll:
                target_fraction = min(max(current_scroll[0], 0.0), 1.0)
            else:
                target_fraction = 0.0
            content_canvas.yview_moveto(target_fraction)
            update_scroll_pause_state()

        root.after_idle(lambda: root.after_idle(restore_scroll_position))
        subtitle_var.set(
            f"Last update: {info['timestamp']} | psutil: {'yes' if payload['psutil_available'] else 'no'}"
        )

    def load_payload(include_benchmark: bool) -> None:
        nonlocal refresh_in_progress
        if refresh_in_progress:
            return
        refresh_in_progress = True

        def worker() -> None:
            action = "benchmark" if include_benchmark else "refresh"
            root.after(0, lambda: status_var.set(f"Running {action}..."))
            try:
                payload = build_output(include_benchmark=include_benchmark)
            except Exception as exc:  # pragma: no cover - defensive GUI path
                def show_error() -> None:
                    nonlocal refresh_in_progress
                    refresh_in_progress = False
                    status_var.set(f"Failed: {exc}")

                root.after(0, show_error)
                return

            def apply_result() -> None:
                nonlocal refresh_in_progress
                render_payload(payload)
                if include_benchmark:
                    status_var.set("Benchmark completed.")
                else:
                    status_var.set("System info refreshed.")
                refresh_in_progress = False

            root.after(0, apply_result)

        threading.Thread(target=worker, daemon=True).start()

    def schedule_auto_refresh() -> None:
        nonlocal auto_refresh_job
        if auto_refresh_job is not None:
            root.after_cancel(auto_refresh_job)
        update_scroll_pause_state()
        if not auto_refresh_paused_for_scroll:
            load_payload(False)
        elif not refresh_in_progress:
            status_var.set("Auto refresh paused while scrolling. Return near the top to resume.")
        auto_refresh_job = root.after(AUTO_REFRESH_MS, schedule_auto_refresh)

    ttk.Button(
        controls,
        text="Refresh",
        style="Secondary.TButton",
        command=lambda: load_payload(False),
    ).grid(row=0, column=0, padx=(0, 10))
    ttk.Button(
        controls,
        text="Capture",
        style="Secondary.TButton",
        command=capture_screenshot,
    ).grid(row=0, column=1, padx=(0, 10))
    ttk.Button(
        controls,
        text="Run Benchmark",
        style="Primary.TButton",
        command=lambda: load_payload(True),
    ).grid(row=0, column=2)

    if run_benchmark_on_start:
        load_payload(True)
    else:
        load_payload(False)
    auto_refresh_job = root.after(AUTO_REFRESH_MS, schedule_auto_refresh)
    root.mainloop()
    return 0


def build_output(include_benchmark: bool) -> dict[str, Any]:
    info = gather_basic_info()
    benchmarks = gather_benchmarks(include_benchmark)
    return {
        "info": info,
        "benchmarks": asdict(benchmarks),
        "psutil_available": bool(psutil),
    }


def print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def print_text(payload: dict[str, Any]) -> None:
    info = payload["info"]
    benchmarks = Benchmarks(**payload["benchmarks"])
    print(render_text_report(info, benchmarks))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inspect system details and run lightweight speed tests."
    )
    parser.add_argument(
        "--benchmark",
        action="store_true",
        help="Run active CPU and disk benchmarks (takes a few seconds).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print structured JSON instead of a human-readable report.",
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="Open a desktop GUI dashboard with grouped panels.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.gui:
        return launch_gui(run_benchmark_on_start=args.benchmark)
    payload = build_output(include_benchmark=args.benchmark)
    if args.json:
        print_json(payload)
    else:
        print_text(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
