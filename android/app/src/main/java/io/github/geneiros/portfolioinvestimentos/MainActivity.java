package io.github.geneiros.portfolioinvestimentos;

import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.ClipData;
import android.content.Intent;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.view.View;
import android.view.Window;
import android.webkit.CookieManager;
import android.webkit.JavascriptInterface;
import android.webkit.URLUtil;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Toast;

import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;

import org.json.JSONObject;

import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;

/**
 * A app: arranca o servidor da aplicação (Python, portfolio_investimentos/android.py) dentro do telemóvel e mostra-o
 * numa WebView, com o ecrã de arranque, a escolha de ficheiros (importar extratos), os downloads (cópias de
 * segurança, CSV) e as barras do sistema na cor do tema.
 */
public class MainActivity extends Activity {
    private static final int REQ_FILE = 1;
    private static final int REQ_SAVE = 2;
    private static volatile String serverUrl;  // o servidor vive enquanto o processo viver

    private WebView web;
    private ValueCallback<Uri[]> fileCallback;
    private String pendingDownload;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        web = new WebView(this);
        setContentView(web);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        CookieManager.getInstance().setAcceptCookie(true);
        web.addJavascriptInterface(new Bridge(), "pmAndroid");
        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                Uri u = request.getUrl();
                if ("127.0.0.1".equals(u.getHost()) || "file".equals(u.getScheme())) return false;
                try {  // links externos (notícias, GitHub) abrem no browser
                    startActivity(new Intent(Intent.ACTION_VIEW, u));
                } catch (ActivityNotFoundException e) {
                    // sem browser: fica como está
                }
                return true;
            }
        });
        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback, FileChooserParams params) {
                if (fileCallback != null) fileCallback.onReceiveValue(null);
                fileCallback = callback;
                Intent i = new Intent(Intent.ACTION_GET_CONTENT);
                i.addCategory(Intent.CATEGORY_OPENABLE);
                i.setType("*/*");
                if (params.getMode() == FileChooserParams.MODE_OPEN_MULTIPLE) {
                    i.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true);
                }
                try {
                    startActivityForResult(i, REQ_FILE);
                } catch (ActivityNotFoundException e) {
                    fileCallback = null;
                    return false;
                }
                return true;
            }
        });
        web.setDownloadListener((url, userAgent, contentDisposition, mimeType, length) -> {
            pendingDownload = url;
            Intent i = new Intent(Intent.ACTION_CREATE_DOCUMENT);
            i.addCategory(Intent.CATEGORY_OPENABLE);
            i.setType(mimeType == null || mimeType.isEmpty() ? "application/octet-stream" : mimeType);
            i.putExtra(Intent.EXTRA_TITLE, URLUtil.guessFileName(url, contentDisposition, mimeType));
            try {
                startActivityForResult(i, REQ_SAVE);
            } catch (ActivityNotFoundException e) {
                Toast.makeText(this, "Não foi possível guardar o ficheiro.", Toast.LENGTH_LONG).show();
            }
        });

        if (serverUrl != null) {
            web.loadUrl(serverUrl);
            return;
        }
        web.loadUrl("file:///android_asset/splash.html");
        new Thread(this::startServer, "arranque").start();
    }

    private void startServer() {
        try {
            if (!Python.isStarted()) Python.start(new AndroidPlatform(this));
            String data = getFilesDir().getAbsolutePath() + "/dados";
            String url = Python.getInstance().getModule("portfolio_investimentos.android")
                    .callAttr("start", data).toString();
            serverUrl = url;
            runOnUiThread(() -> web.loadUrl(url));
        } catch (Throwable t) {
            String msg = "Não foi possível arrancar a aplicação:\n" + t.getMessage();
            runOnUiThread(() -> web.evaluateJavascript(
                    "window.pmSplash && pmSplash(" + JSONObject.quote(msg) + ", true)", null));
        }
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == REQ_FILE && fileCallback != null) {
            Uri[] result = null;
            if (resultCode == RESULT_OK && data != null) {
                ClipData clip = data.getClipData();
                if (clip != null) {
                    result = new Uri[clip.getItemCount()];
                    for (int i = 0; i < clip.getItemCount(); i++) result[i] = clip.getItemAt(i).getUri();
                } else if (data.getData() != null) {
                    result = new Uri[]{data.getData()};
                }
            }
            fileCallback.onReceiveValue(result);
            fileCallback = null;
        } else if (requestCode == REQ_SAVE) {
            String url = pendingDownload;
            pendingDownload = null;
            if (resultCode == RESULT_OK && data != null && data.getData() != null && url != null) {
                Uri target = data.getData();
                new Thread(() -> save(url, target), "download").start();
            }
        }
    }

    /** Descarrega do servidor da app (com a sessão da WebView) para o ficheiro escolhido. */
    private void save(String url, Uri target) {
        String message = "Ficheiro guardado.";
        HttpURLConnection c = null;
        try {
            c = (HttpURLConnection) new URL(url).openConnection();
            String cookies = CookieManager.getInstance().getCookie(url);
            if (cookies != null) c.setRequestProperty("Cookie", cookies);
            try (InputStream in = c.getInputStream();
                 OutputStream out = getContentResolver().openOutputStream(target)) {
                byte[] buf = new byte[65536];
                int n;
                while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
            }
        } catch (Exception e) {
            message = "Não foi possível guardar o ficheiro: " + e.getMessage();
        } finally {
            if (c != null) c.disconnect();
        }
        String m = message;
        runOnUiThread(() -> Toast.makeText(this, m, Toast.LENGTH_LONG).show());
    }

    @Override
    @SuppressWarnings("deprecation")
    public void onBackPressed() {
        if (web != null && web.canGoBack()) {
            web.goBack();
        } else {
            super.onBackPressed();
        }
    }

    /** Chamado pelas páginas (pm.js): as barras do sistema ficam da cor do fundo do tema. */
    private class Bridge {
        @JavascriptInterface
        public void setTheme(String color, boolean dark) {
            runOnUiThread(() -> {
                try {
                    int c = Color.parseColor(color);
                    Window w = getWindow();
                    w.setStatusBarColor(c);
                    w.setNavigationBarColor(c);
                    View d = w.getDecorView();
                    int flags = d.getSystemUiVisibility();
                    int light = View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR;
                    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) light |= View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR;
                    d.setSystemUiVisibility(dark ? flags & ~light : flags | light);
                } catch (IllegalArgumentException e) {
                    // cor inválida: fica como está
                }
            });
        }
    }
}
