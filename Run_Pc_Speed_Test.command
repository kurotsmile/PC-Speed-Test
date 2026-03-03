#!/bin/zsh

set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PY_SCRIPT="$SCRIPT_DIR/Pc_speed_test.py"
REQ_FILE="$SCRIPT_DIR/requirements.txt"
LOG_FILE="/tmp/pc_speed_test_gui.log"

print_line() {
  printf '%s\n' "$1"
}

pause_before_exit() {
  print_line ""
  read "?Nhan Enter de dong cua so..."
}

find_python() {
  if command -v python3 >/dev/null 2>&1; then
    command -v python3
    return 0
  fi

  if command -v python >/dev/null 2>&1; then
    local py_bin
    py_bin="$(command -v python)"
    if "$py_bin" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 8) else 1)' >/dev/null 2>&1; then
      print_line "$py_bin"
      return 0
    fi
  fi

  return 1
}

install_python_if_needed() {
  local py_bin
  if py_bin="$(find_python)"; then
    print_line "Da tim thay Python: $py_bin"
    PY_BIN="$py_bin"
    return 0
  fi

  print_line "Khong tim thay Python 3."
  if command -v brew >/dev/null 2>&1; then
    print_line "Dang cai Python bang Homebrew..."
    if brew install python; then
      if py_bin="$(find_python)"; then
        PY_BIN="$py_bin"
        print_line "Da cai Python thanh cong: $PY_BIN"
        return 0
      fi
    fi
    print_line "Homebrew da chay nhung khong tim thay python3 sau cai dat."
  else
    print_line "Khong tim thay Homebrew, khong the tu dong cai Python."
    print_line "Hay cai Homebrew hoac Python 3 roi chay lai."
  fi

  return 1
}

ensure_pip() {
  if "$PY_BIN" -m pip --version >/dev/null 2>&1; then
    return 0
  fi

  print_line "pip chua san sang, dang kich hoat ensurepip..."
  "$PY_BIN" -m ensurepip --upgrade >/dev/null 2>&1 || return 1
  "$PY_BIN" -m pip --version >/dev/null 2>&1
}

install_requirements() {
  if [ ! -f "$REQ_FILE" ]; then
    print_line "Khong co requirements.txt, bo qua buoc cai thu vien."
    return 0
  fi

  if "$PY_BIN" -c 'import psutil' >/dev/null 2>&1; then
    print_line "Thu vien psutil da co san."
    return 0
  fi

  print_line "Dang cai dat thu vien can thiet..."
  if "$PY_BIN" -m pip install --user -r "$REQ_FILE"; then
    return 0
  fi

  print_line "Cai dat voi --user that bai, thu lai voi break-system-packages..."
  if "$PY_BIN" -m pip install --user --break-system-packages -r "$REQ_FILE"; then
    return 0
  fi

  print_line "Khong the cai thu vien luc nay. Tool van se chay voi thong tin co ban."
  return 0
}

can_launch_gui() {
  "$PY_BIN" -c 'import tkinter' >/dev/null 2>&1
}

close_launcher_window() {
  if command -v osascript >/dev/null 2>&1; then
    (
      sleep 0.2
      osascript \
        -e 'tell application "Terminal" to if (count of windows) > 0 then close front window saving no' \
        >/dev/null 2>&1
    ) &
  fi
}

run_tool() {
  print_line ""
  print_line "Khoi dong PC Speed Test GUI..."

  if can_launch_gui; then
    nohup "$PY_BIN" "$PY_SCRIPT" --gui --benchmark >"$LOG_FILE" 2>&1 </dev/null &
    local gui_pid=$!
    sleep 1

    if kill -0 "$gui_pid" >/dev/null 2>&1; then
      close_launcher_window
      return 0
    fi

    print_line "GUI khong mo duoc. Kiem tra log: $LOG_FILE"
  else
    print_line "Tkinter khong san sang, chuyen sang che do terminal."
  fi

  "$PY_BIN" "$PY_SCRIPT" --benchmark
  return 1
}

main() {
  print_line "=== PC Speed Test Launcher ==="
  print_line "Thu muc: $SCRIPT_DIR"

  if [ ! -f "$PY_SCRIPT" ]; then
    print_line "Khong tim thay file $PY_SCRIPT"
    pause_before_exit
    return 1
  fi

  if ! install_python_if_needed; then
    pause_before_exit
    return 1
  fi

  if ! ensure_pip; then
    print_line "Khong the khoi tao pip. Hay cai lai Python 3 day du."
    pause_before_exit
    return 1
  fi

  install_requirements

  if ! run_tool; then
    pause_before_exit
  fi
}

PY_BIN=""
main "$@"
