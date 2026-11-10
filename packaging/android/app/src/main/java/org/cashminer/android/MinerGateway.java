package org.cashminer.android;

import android.content.*;
import android.net.Uri;
import android.os.*;
import org.json.JSONObject;
import java.util.*;
import java.util.concurrent.*;

public final class MinerGateway {
    private static Context context;
    private static final Map<String,Session> sessions=new ConcurrentHashMap<>();
    private static final Handler monitor=new Handler(Looper.getMainLooper());
    private static boolean watching;
    private static final Runnable tick=new Runnable(){public void run(){
        boolean active=false;
        for(Session s:sessions.values())if(!s.exited){
            active=true;
            try{context.startService(new Intent(context,s.type).setAction("HEARTBEAT").putExtra("receiver",s.receiver));}
            catch(RuntimeException error){
                Bundle data=new Bundle();data.putInt("code",1);data.putBoolean("forced",true);
                s.receiver.send(2,data);
            }
        }
        if(active)monitor.postDelayed(this,3000);else watching=false;
    }};
    private static final class Session {
        final String run;final Class<?> type;final BlockingQueue<String> queue=new LinkedBlockingQueue<>();
        volatile boolean exited;
        ResultReceiver receiver;
        Session(String id,Class<?> klass){run=id;type=klass;}
    }
    public static void initialize(Context ctx){context=ctx.getApplicationContext();}
    private static Class<?> type(String network) {
        return switch(network) {
            case "mainnet" -> MinerService.Mainnet.class;
            case "testnet3" -> MinerService.Testnet3.class;
            case "testnet4" -> MinerService.Testnet4.class;
            case "chipnet" -> MinerService.Chipnet.class;
            case "tempnet_fablous_2026" -> MinerService.Tempnet.class;
            case "regtest" -> MinerService.Regtest.class;
            default -> throw new IllegalArgumentException("Red desconocida");
        };
    }
    public static synchronized void start(String network,String run,String config) throws Exception {
        Session previous=sessions.get(network);
        if(previous!=null&&!previous.exited)throw new IllegalStateException("Ya hay minería en curso en esta red");
        Session session=new Session(run,type(network));sessions.put(network,session);
        ResultReceiver receiver=new ResultReceiver(new Handler(Looper.getMainLooper())) {
            @Override protected void onReceiveResult(int result,Bundle data) {
                try {
                    JSONObject event=new JSONObject();
                    if(result==1){event.put("type","line");event.put("line",data.getString("line",""));}
                    else {session.exited=true;event.put("type","exit");event.put("code",data.getInt("code",1));event.put("forced",data.getBoolean("forced"));}
                    session.queue.offer(event.toString());
                } catch(Exception ignored){}
            }
        };
        session.receiver=receiver;
        Intent intent=new Intent(context,session.type).setAction("START");
        intent.putExtra("config",config);intent.putExtra("receiver",receiver);
        try {
            if(Build.VERSION.SDK_INT>=26)context.startForegroundService(intent);else context.startService(intent);
        } catch(RuntimeException error) {session.exited=true;throw error;}
        // Monitoring belongs to the application, not to a visible Activity.
        monitor.post(()->{if(!watching){watching=true;monitor.postDelayed(tick,3000);}});
    }
    public static String poll(String network,String run,int millis) throws Exception {
        Session s=sessions.get(network);
        if(s==null||!s.run.equals(run))throw new IllegalArgumentException("Sesión desconocida");
        return s.queue.poll(millis,TimeUnit.MILLISECONDS);
    }
    public static void stop(String network,String run) {
        Session s=sessions.get(network);
        if(s!=null&&s.run.equals(run)&&!s.exited)context.startService(new Intent(context,s.type).setAction("STOP").putExtra("receiver",s.receiver));
    }
    public static void openExternal(String text) {
        Uri uri=Uri.parse(text);
        if(!"https".equals(uri.getScheme())||uri.getHost()==null)throw new IllegalArgumentException("Sólo HTTPS externo");
        context.startActivity(new Intent(Intent.ACTION_VIEW,uri).addCategory(Intent.CATEGORY_BROWSABLE).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
    }
}
