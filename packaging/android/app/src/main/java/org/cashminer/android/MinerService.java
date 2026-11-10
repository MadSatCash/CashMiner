package org.cashminer.android;

import android.app.*;
import android.content.*;
import android.os.*;
import com.chaquo.python.*;
import com.chaquo.python.android.AndroidPlatform;
import java.io.File;

public class MinerService extends Service {
    private final Handler handler=new Handler(Looper.getMainLooper());
    private ResultReceiver receiver;
    private Thread worker;
    private volatile boolean emittedExit;
    private PowerManager.WakeLock wakeLock;
    private boolean hostBound,stopping;
    private final ServiceConnection host=new ServiceConnection(){
        @Override public void onServiceConnected(ComponentName name,IBinder binder){}
        @Override public void onServiceDisconnected(ComponentName name){requestStop();}
    };
    public static class Mainnet extends MinerService{}
    public static class Testnet3 extends MinerService{}
    public static class Testnet4 extends MinerService{}
    public static class Chipnet extends MinerService{}
    public static class Tempnet extends MinerService{}
    public static class Regtest extends MinerService{}
    private int networkIndex(){return switch(getClass().getSimpleName()){
        case "Mainnet" -> 0;case "Testnet3" -> 1;case "Testnet4" -> 2;
        case "Chipnet" -> 3;case "Tempnet" -> 4;case "Regtest" -> 5;
        default -> throw new IllegalStateException("Red desconocida");
    };}

    @Override public IBinder onBind(Intent intent){return null;}
    @Override public void onCreate(){
        super.onCreate();
        if(Build.VERSION.SDK_INT>=26){
            NotificationChannel channel=new NotificationChannel("mining","CashMiner CPU",NotificationManager.IMPORTANCE_LOW);
            getSystemService(NotificationManager.class).createNotificationChannel(channel);
        }
        Intent stop=new Intent(this,getClass()).setAction("STOP");
        PendingIntent action=PendingIntent.getService(this,1,stop,PendingIntent.FLAG_IMMUTABLE|PendingIntent.FLAG_UPDATE_CURRENT);
        PendingIntent open=PendingIntent.getActivity(this,2,new Intent(this,MainActivity.class)
            .addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP|Intent.FLAG_ACTIVITY_CLEAR_TOP),
            PendingIntent.FLAG_IMMUTABLE|PendingIntent.FLAG_UPDATE_CURRENT);
        Notification.Builder builder=Build.VERSION.SDK_INT>=26?new Notification.Builder(this,"mining"):new Notification.Builder(this);
        String label=new String[]{"Mainnet","Testnet3","Testnet4","Chipnet","FABLOUS Tempnet","Regtest"}[networkIndex()];
        builder.setContentTitle("CashMiner · "+label).setContentText("Minería CPU · Detener / Stop")
            .setSmallIcon(android.R.drawable.ic_menu_compass).setOngoing(true).setContentIntent(open)
            .addAction(new Notification.Action.Builder(null,"Detener / Stop",action).build());
        startForeground(21+networkIndex(),builder.build());
    }
    @Override public int onStartCommand(Intent intent,int flags,int startId){
        if(intent==null){stopSelf();return START_NOT_STICKY;}
        if(receiver==null)receiver=intent.getParcelableExtra("receiver");
        if("HEARTBEAT".equals(intent.getAction())&&worker==null){
            emitLine("[android] El proceso minero se interrumpió; podés volver a iniciarlo.");
            emitExit(1,true);handler.post(()->{stopSelf();android.os.Process.killProcess(android.os.Process.myPid());});
            return START_NOT_STICKY;
        }
        if("STOP".equals(intent.getAction())){requestStop();return START_NOT_STICKY;}
        if(!"START".equals(intent.getAction())||worker!=null)return START_NOT_STICKY;
        receiver=intent.getParcelableExtra("receiver");
        String config=intent.getStringExtra("config");
        hostBound=bindService(new Intent(this,AppHostService.class),host,BIND_AUTO_CREATE|BIND_IMPORTANT);
        if(!hostBound){emitLine("[android] No se pudo mantener el servicio de la aplicación");emitExit(1,false);stopSelf();return START_NOT_STICKY;}
        wakeLock=((PowerManager)getSystemService(POWER_SERVICE)).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK,"CashMiner:MiningCPU");
        wakeLock.setReferenceCounted(false);wakeLock.acquire();
        worker=new Thread(()->{
            int code=1;
            try {
                if(!Python.isStarted())Python.start(new AndroidPlatform(this));
                File root=AppFiles.prepare(this);
                code=Python.getInstance().getModule("android_entry").callAttr("run_miner",this,root.getAbsolutePath(),config,this).toInt();
            } catch(Throwable e){emitLine("[android] "+e.getClass().getSimpleName()+": "+e.getMessage());}
            finally {releasePower();emitExit(code,false);handler.post(()->{stopSelf();android.os.Process.killProcess(android.os.Process.myPid());});}
        },"CashMiner-CPU");
        worker.start();return START_NOT_STICKY;
    }
    public void emitLine(String line){
        if(receiver!=null){Bundle b=new Bundle();b.putString("line",line);receiver.send(1,b);}
    }
    private synchronized void emitExit(int code,boolean forced){
        if(emittedExit)return;emittedExit=true;
        if(receiver!=null){Bundle b=new Bundle();b.putInt("code",code);b.putBoolean("forced",forced);receiver.send(2,b);}
    }
    private synchronized void releasePower(){if(wakeLock!=null&&wakeLock.isHeld())wakeLock.release();}
    private synchronized void requestStop(){
        if(stopping)return;stopping=true;
        new Thread(()->{
            try {if(Python.isStarted())Python.getInstance().getModule("android_entry").callAttr("stop_miner");}catch(Throwable ignored){}
        }).start();
        handler.postDelayed(()->{releasePower();emitExit(0,true);stopSelf();android.os.Process.killProcess(android.os.Process.myPid());},6000);
    }
    @Override public void onDestroy(){
        handler.removeCallbacksAndMessages(null);releasePower();
        if(hostBound){unbindService(host);hostBound=false;}
        super.onDestroy();
    }
}
