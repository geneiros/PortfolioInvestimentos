# App Android

A app leva o Python e a aplicação lá dentro ([Chaquopy](https://chaquo.com/chaquopy/)). Funciona assim:
- arranca o servidor no próprio telemóvel (`portfolio_investimentos/android.py`);
- mostra a aplicação numa janela própria (`MainActivity.java`, uma WebView), sem browser nem Termux;
- guarda os dados na área privada da app.

O workflow **Executável único (PyInstaller)** gera a `PortfolioInvestimentos-android.apk`, experimenta-a num emulador
e junta-a à release.

## Chave de assinatura (uma vez só)

Todas as versões da APK têm de ser assinadas com a mesma chave. Com outra chave, o Android não instala a versão nova
por cima da antiga. A chave fica nos segredos do GitHub, nunca no repositório.

1. Criar a chave (precisa do Java; guarda o ficheiro e as palavras-passe num sítio seguro):
   ```bash
   keytool -genkeypair -v -keystore portfolio-android.jks -alias portfolio -keyalg RSA -keysize 4096 -validity 10000
   ```
2. Converter para base64:
   - Linux/macOS: `base64 -w0 portfolio-android.jks` (no macOS: `base64 -i portfolio-android.jks`);
   - Windows (PowerShell): `[Convert]::ToBase64String([IO.File]::ReadAllBytes("portfolio-android.jks"))`.
3. Em GitHub → Settings → Secrets and variables → Actions → **New repository secret**, criar:

   | Segredo | Valor |
   | --- | --- |
   | `ANDROID_KEYSTORE_B64` | o texto em base64 do passo 2 |
   | `ANDROID_KEYSTORE_PASSWORD` | a palavra-passe do ficheiro |
   | `ANDROID_KEY_ALIAS` | `portfolio` (o `-alias` do passo 1) |
   | `ANDROID_KEY_PASSWORD` | a palavra-passe da chave (a mesma do ficheiro, se não escolheste outra) |

Sem estes segredos:
- as builds de teste usam a chave de depuração;
- uma release falha de propósito, para não publicar uma APK que não se atualiza por cima da anterior.

## Gerar à mão

Precisa do Android SDK, do Java 17, do Gradle 8.7 e do Python 3.12:

```bash
mkdir -p android/app/src/main/python
cp -r portfolio_investimentos android/app/src/main/python/
cd android && DISABLE_SQLALCHEMY_CEXT=1 gradle assembleRelease
```
