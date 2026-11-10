package org.cashminer.android;

import android.app.Service;
import android.content.Intent;
import android.os.Binder;
import android.os.IBinder;

/** Keeps the shared Python app/log receiver alive while its miner is foreground. */
public final class AppHostService extends Service {
    private final Binder binder=new Binder();
    @Override public IBinder onBind(Intent intent){return binder;}
}
