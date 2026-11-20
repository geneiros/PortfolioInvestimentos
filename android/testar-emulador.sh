#!/usr/bin/env bash
# Teste da APK no emulador (workflow executavel.yml): instala, abre e espera que o servidor da app arranque.
set -e
APK="$1"
adb install -r "$APK"
adb logcat -c
adb shell am start -n io.github.geneiros.portfolioinvestimentos/.MainActivity
for i in $(seq 1 120); do
  if adb logcat -d | grep -q "Portfolio Investimentos pronto"; then
    adb logcat -d | grep -i "python" | tail -20
    echo "A app arrancou."
    exit 0
  fi
  sleep 2
done
echo "A app não arrancou em 4 minutos. Registo:"
adb logcat -d | grep -iE "python|chaquopy|AndroidRuntime|portfolio" | tail -100
exit 1
