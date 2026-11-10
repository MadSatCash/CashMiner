package org.cashminer.android;

import android.content.Context;
import java.io.*;
import java.util.zip.*;
import java.security.MessageDigest;

final class AppFiles {
    static synchronized File prepare(Context context) throws Exception {
        MessageDigest digest=MessageDigest.getInstance("SHA-256");
        try(InputStream input=context.getAssets().open("cashminer_payload.zip")) {
            byte[] buf=new byte[65536];int n;while((n=input.read(buf))!=-1)digest.update(buf,0,n);
        }
        StringBuilder hex=new StringBuilder();for(byte b:digest.digest())hex.append(String.format("%02x",b&255));
        File root=new File(context.getFilesDir(),"application-"+hex.substring(0,12));
        File marker=new File(root,".complete");
        if(marker.isFile()) return root;
        root.mkdirs();
        try(ZipInputStream zip=new ZipInputStream(context.getAssets().open("cashminer_payload.zip"))) {
            ZipEntry entry;byte[] buffer=new byte[65536];
            while((entry=zip.getNextEntry())!=null) {
                File target=new File(root,entry.getName());
                if(!target.getCanonicalPath().startsWith(root.getCanonicalPath()+File.separator))
                    throw new IOException("Invalid payload path");
                if(entry.isDirectory()){target.mkdirs();continue;}
                target.getParentFile().mkdirs();
                try(FileOutputStream out=new FileOutputStream(target)) {
                    int count;while((count=zip.read(buffer))!=-1)out.write(buffer,0,count);
                }
            }
        }
        marker.createNewFile();return root;
    }
}
