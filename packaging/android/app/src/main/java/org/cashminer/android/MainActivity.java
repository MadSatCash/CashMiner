package org.cashminer.android;

import android.Manifest;
import android.app.*;
import android.content.*;
import android.net.Uri;
import android.os.*;
import android.view.*;
import android.webkit.*;
import android.widget.TextView;
import android.widget.FrameLayout;
import com.chaquo.python.*;
import com.chaquo.python.android.AndroidPlatform;
import java.io.File;
import java.util.concurrent.*;

public final class MainActivity extends Activity {
    private WebView view;private String origin;
    private final Handler handler=new Handler(Looper.getMainLooper());
    private final ExecutorService backend=Executors.newSingleThreadExecutor();
    private volatile boolean ready;
    private void content(View child){
        FrameLayout root=new FrameLayout(this);
        root.setBackgroundColor(0xff101719);
        root.setOnApplyWindowInsetsListener((v,insets)->{
            v.setPadding(insets.getSystemWindowInsetLeft(),insets.getSystemWindowInsetTop(),
                         insets.getSystemWindowInsetRight(),insets.getSystemWindowInsetBottom());
            return insets.consumeSystemWindowInsets();
        });
        root.addView(child,new FrameLayout.LayoutParams(-1,-1));setContentView(root);root.requestApplyInsets();
    }
    @Override public void onCreate(Bundle state){
        super.onCreate(state);
        TextView text=new TextView(this);text.setText("CashMiner\nPreparando / Starting…");text.setPadding(24,48,24,24);content(text);
        MinerGateway.initialize(this);
        if(Build.VERSION.SDK_INT>=33)requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS},1);
        backend.submit(()->{
            try {
                if(!Python.isStarted())Python.start(new AndroidPlatform(this));
                File root=AppFiles.prepare(this);
                if(getIntent().getBooleanExtra("selftest",false)) {
                    String test=Python.getInstance().getModule("android_entry").callAttr("diagnostics",this,root.getAbsolutePath()).toString();
                    android.util.Log.i("CashMinerSelfTest",test);
                }
                String url=Python.getInstance().getModule("android_entry").callAttr("start_app",this,root.getAbsolutePath()).toString();
                android.util.Log.i("CashMinerStartup","UI "+url);
                runOnUiThread(()->open(url));
            }catch(Throwable e){android.util.Log.e("CashMinerStartup","Startup failed",e);runOnUiThread(()->text.setText("No se pudo iniciar CashMiner\n"+e.getMessage()));}
        });
    }
    private void open(String url){
        origin=url.substring(0,url.length()-1);
        view=new WebView(this);view.setBackgroundColor(0xff101719);
        WebSettings settings=view.getSettings();settings.setJavaScriptEnabled(true);settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(false);settings.setAllowContentAccess(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        view.setWebViewClient(new WebViewClient(){
            @Override public boolean shouldOverrideUrlLoading(WebView v,WebResourceRequest req){
                Uri u=req.getUrl();
                if((origin+"/").equals(u.toString())||u.toString().startsWith(origin+"/"))return false;
                if("https".equals(u.getScheme()))MinerGateway.openExternal(u.toString());
                return true;
            }
        });
        view.setWebChromeClient(new WebChromeClient(){
            @Override public boolean onJsConfirm(WebView v,String page,String message,JsResult result){
                new AlertDialog.Builder(MainActivity.this).setMessage(message)
                    .setPositiveButton("Aceptar / OK",(d,w)->result.confirm())
                    .setNegativeButton("Cancelar / Cancel",(d,w)->result.cancel())
                    .setOnCancelListener(d->result.cancel()).show();return true;
            }
        });content(view);view.loadUrl(url);ready=true;
        handler.post(new Runnable(){public void run(){
            if(isFinishing())return;
            MinerGateway.heartbeat();
            if(ready)backend.submit(()->{
                try {if(!Python.getInstance().getModule("android_entry").callAttr("alive").toBoolean())runOnUiThread(()->finish());}catch(Throwable ignored){}
            });
            handler.postDelayed(this,2000);
        }});
    }
    @Override protected void onResume(){super.onResume();MinerGateway.visible=true;}
    @Override protected void onStop(){
        MinerGateway.visible=false;
        if(ready)backend.submit(()->{try{Python.getInstance().getModule("android_entry").callAttr("pause_mining");}catch(Throwable ignored){}});
        super.onStop();
    }
    @Override public void onBackPressed(){
        new AlertDialog.Builder(this).setMessage("¿Cerrar CashMiner y detener la minería? / Close and stop mining?")
            .setPositiveButton("Cerrar / Close",(dialog,which)->finish()).setNegativeButton("Cancelar / Cancel",null).show();
    }
    @Override protected void onDestroy(){
        handler.removeCallbacksAndMessages(null);
        if(isFinishing()&&ready)backend.submit(()->{try{Python.getInstance().getModule("android_entry").callAttr("stop_app");}catch(Throwable ignored){}});
        backend.shutdown();if(view!=null)view.destroy();super.onDestroy();
    }
}
