"""Small Chaquopy entry; all application Python comes from the shared source payload."""
import os
import sys

def setup(context, root):
    root = str(root)
    os.environ['CASHMINER_ANDROID'] = '1'
    os.environ['CASHMINER_ANDROID_APP_ROOT'] = root
    os.environ['CASHMINER_DATA_DIR'] = str(context.getFilesDir().getAbsolutePath())+'/data'
    os.environ['CASHMINER_ANDROID_NATIVE'] = str(context.getApplicationInfo().nativeLibraryDir)
    sys.path[:0] = [root+'/src', root+'/mining_engine']
    sys.dont_write_bytecode = True

def start_app(context, root):
    setup(context, root)
    from cashminer.platform.android_runtime import start_app
    return start_app(context)

def stop_app():
    from cashminer.platform.android_runtime import stop_app
    stop_app()

def pause_mining():
    from cashminer.platform.android_runtime import pause_mining
    pause_mining()

def alive():
    from cashminer.platform.android_runtime import app_alive
    return app_alive()

def run_miner(context, root, config, sink):
    setup(context, root)
    from cashminer.platform.android_runtime import run_miner
    return run_miner(str(config), sink)

def stop_miner():
    from cashminer.platform.android_runtime import request_miner_stop
    request_miner_stop()

def diagnostics(context, root):
    setup(context, root)
    from cashminer.platform.android_runtime import diagnostics
    return diagnostics()
