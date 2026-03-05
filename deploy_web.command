#!/bin/zsh

set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WEB_DIR="$SCRIPT_DIR/web"
PROJECT_ID="pcspeedtool"
FIREBASE_ACCOUNT="nguyennhung2672@gmail.com"

print_line() {
  printf '%s\n' "$1"
}

pause_before_exit() {
  print_line ""
  read "?Nhan Enter de dong cua so..."
}

check_firebase_cli() {
  if command -v firebase >/dev/null 2>&1; then
    return 0
  fi

  print_line "Khong tim thay Firebase CLI."
  print_line "Hay cai dat bang lenh: npm install -g firebase-tools"
  return 1
}

check_web_dir() {
  if [ -d "$WEB_DIR" ]; then
    return 0
  fi

  print_line "Khong tim thay thu muc web: $WEB_DIR"
  return 1
}

ensure_account_login() {
  if firebase login:list 2>/dev/null | grep -Fq "$FIREBASE_ACCOUNT"; then
    print_line "Da tim thay tai khoan Firebase: $FIREBASE_ACCOUNT"
    return 0
  fi

  print_line "Tai khoan $FIREBASE_ACCOUNT chua duoc them vao Firebase CLI."
  print_line "Dang mo dang nhap lai de them tai khoan..."
  if ! firebase login --reauth --no-localhost; then
    print_line "Dang nhap that bai."
    return 1
  fi

  if firebase login:list 2>/dev/null | grep -Fq "$FIREBASE_ACCOUNT"; then
    print_line "Da them tai khoan thanh cong: $FIREBASE_ACCOUNT"
    return 0
  fi

  print_line "Van chua thay tai khoan $FIREBASE_ACCOUNT sau khi dang nhap."
  print_line "Hay dang nhap dung email roi chay lai."
  return 1
}

deploy_hosting() {
  cd "$WEB_DIR" || return 1

  print_line "Dang deploy Firebase Hosting..."
  firebase deploy --only hosting --project "$PROJECT_ID" --account "$FIREBASE_ACCOUNT"
}

main() {
  print_line "=== Firebase Web Deploy ==="
  print_line "Project: $PROJECT_ID"
  print_line "Account: $FIREBASE_ACCOUNT"

  if ! check_firebase_cli; then
    pause_before_exit
    return 1
  fi

  if ! check_web_dir; then
    pause_before_exit
    return 1
  fi

  if ! ensure_account_login; then
    pause_before_exit
    return 1
  fi

  if deploy_hosting; then
    print_line ""
    print_line "Deploy thanh cong."
    return 0
  fi

  print_line ""
  print_line "Deploy that bai. Kiem tra loi o phan tren."
  pause_before_exit
  return 1
}

main "$@"
