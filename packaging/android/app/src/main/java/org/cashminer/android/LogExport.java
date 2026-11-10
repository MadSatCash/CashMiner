package org.cashminer.android;

import android.app.Activity;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.webkit.JavascriptInterface;
import android.widget.Toast;
import java.io.*;
import java.net.*;

/** Native Save As for the existing authenticated log download, streamed to SAF. */
public final class LogExport {
    private static final int REQUEST=320;
    private final Activity activity;
    private String name,token,origin;
    LogExport(Activity host,Bundle state){
        activity=host;
        if(state!=null){name=state.getString("export.name");token=state.getString("export.token");origin=state.getString("export.origin");}
    }
    void saveState(Bundle state){
        state.putString("export.name",name);state.putString("export.token",token);state.putString("export.origin",origin);
    }
    Object bridge(String localOrigin){return new Bridge(localOrigin);}
    public final class Bridge {
        private final String localOrigin;
        Bridge(String value){localOrigin=value;}
        @JavascriptInterface public void saveLog(String file,String session){
            activity.runOnUiThread(()->{
                if(activity.isDestroyed()||activity.isFinishing())return;
                if(file==null||!file.matches("[A-Za-z0-9._-]{1,200}\\.log")||session==null||!session.matches("[A-Za-z0-9_-]{40,100}")){
                    toast("Registro inválido / Invalid log");return;
                }
                if(name!=null){toast("Ya hay una exportación en curso / Export in progress");return;}
                name=file;token=session;origin=localOrigin;
                try{activity.startActivityForResult(new Intent(Intent.ACTION_CREATE_DOCUMENT)
                    .addCategory(Intent.CATEGORY_OPENABLE).setType("text/plain").putExtra(Intent.EXTRA_TITLE,file),REQUEST);}
                catch(RuntimeException error){clear();toast("No se pudo abrir Guardar como / Save dialog unavailable");}
            });
        }
    }
    boolean onResult(int request,int result,Intent data){
        if(request!=REQUEST)return false;
        String file=name,session=token,base=origin;clear();
        if(result!=Activity.RESULT_OK||data==null||data.getData()==null)return true;
        Uri destination=data.getData();
        if(file==null||session==null||base==null){toast("Volvé a exportar el log / Please export again");return true;}
        new Thread(()->{
            HttpURLConnection connection=null;
            try{
                URL source=new URL(base+"/api/logs/download?name="+URLEncoder.encode(file,"UTF-8"));
                if(!source.getProtocol().equals("http")||!source.getHost().equals("127.0.0.1"))throw new IOException("Invalid origin");
                connection=(HttpURLConnection)source.openConnection();connection.setInstanceFollowRedirects(false);
                connection.setConnectTimeout(15000);connection.setReadTimeout(30000);
                connection.setRequestProperty("X-CashMiner-Session",session);
                if(connection.getResponseCode()!=200)throw new IOException("Log HTTP "+connection.getResponseCode());
                try(InputStream in=connection.getInputStream();OutputStream out=activity.getContentResolver().openOutputStream(destination,"w")){
                    if(out==null)throw new IOException("Destination unavailable");
                    byte[] buffer=new byte[65536];int count;while((count=in.read(buffer))!=-1)out.write(buffer,0,count);
                }
                toast("Log guardado / Log saved: "+file);
            }catch(Exception error){toast("No se pudo guardar el log / Could not save log");}
            finally{if(connection!=null)connection.disconnect();}
        },"CashMiner-log-export").start();
        return true;
    }
    private void clear(){name=null;token=null;origin=null;}
    private void toast(String text){activity.runOnUiThread(()->Toast.makeText(activity.getApplicationContext(),text,Toast.LENGTH_LONG).show());}
}
