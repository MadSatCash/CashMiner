package org.cashminer.android;

import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

public final class KeyStoreVault {
    private static final String ALIAS="CashMiner.seed.wrapping.v1";
    private static synchronized SecretKey key(boolean create) throws Exception {
        KeyStore ks=KeyStore.getInstance("AndroidKeyStore"); ks.load(null);
        if(!ks.containsAlias(ALIAS)) {
            if(!create) throw new IllegalStateException("Falta la clave de Android Keystore; recuperar la billetera desde su frase");
            KeyGenerator gen=KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES,"AndroidKeyStore");
            gen.init(new KeyGenParameterSpec.Builder(ALIAS,KeyProperties.PURPOSE_ENCRYPT|KeyProperties.PURPOSE_DECRYPT)
                .setKeySize(256).setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build());
            gen.generateKey();
        }
        return ((KeyStore.SecretKeyEntry)ks.getEntry(ALIAS,null)).getSecretKey();
    }
    public static String protect(String plain64,String wallet) throws Exception {
        Cipher cipher=Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.ENCRYPT_MODE,key(true));
        cipher.updateAAD(("CashMiner.Android.v1:"+wallet).getBytes(StandardCharsets.UTF_8));
        return "CMANDROID1:"+Base64.encodeToString(cipher.getIV(),Base64.NO_WRAP)+":"+
            Base64.encodeToString(cipher.doFinal(Base64.decode(plain64,Base64.NO_WRAP)),Base64.NO_WRAP);
    }
    public static String unprotect(String blob,String wallet) throws Exception {
        String[] parts=blob.split(":");
        if(parts.length!=3||!parts[0].equals("CMANDROID1")) throw new IllegalArgumentException("Formato de vault Android inválido");
        Cipher cipher=Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.DECRYPT_MODE,key(false),new GCMParameterSpec(128,Base64.decode(parts[1],Base64.NO_WRAP)));
        cipher.updateAAD(("CashMiner.Android.v1:"+wallet).getBytes(StandardCharsets.UTF_8));
        return Base64.encodeToString(cipher.doFinal(Base64.decode(parts[2],Base64.NO_WRAP)),Base64.NO_WRAP);
    }
}
