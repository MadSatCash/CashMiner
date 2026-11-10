"""Registro de la aplicación, *separado* del motor y Peer Explorer.

Una sola sesión -> un archivo cashminer_app_<epoch_ms>.log. No se registran
peticiones HTTP, semillas, claves privadas ni saldos; los logs del motor son
archivos distintos bajo el control de su propio subsistema.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
import time
from pathlib import Path

from cashminer.config import data_home

LOG_NAME = "cashminer.application"


def start_logging() -> tuple[logging.Logger, Path]:
    """Abre un archivo nuevo por sesión sin sobrescribir registros existentes."""
    folder = data_home() / "logs" / "application"
    folder.mkdir(parents=True, exist_ok=True)
    # Exclusive creation even if two processes launch within the same millisecond.
    stamp = time.time_ns() // 1_000_000
    while True:
        path = folder / f"cashminer_app_{stamp}.log"
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            break
        except FileExistsError:
            stamp += 1
    logger = logging.getLogger(LOG_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    handler = logging.StreamHandler(os.fdopen(fd, "w", encoding="utf-8", buffering=1))
    handler.setFormatter(logging.Formatter("%(asctime)s UTC | %(levelname)s | %(threadName)s | %(message)s"))
    handler.formatter.converter = time.gmtime
    logger.addHandler(handler)
    return logger, path


def run_gui(*, show_error_dialog: bool = False):
    """Lanzador común a pythonw (sin consola) y CLI de diagnóstico.

    Los errores de Python van al log de aplicación. No se redirige stdout ni
    stderr del subprocess minero: conserva su registro separado e intacto.
    """
    logger, path = start_logging()
    old_thread_hook = threading.excepthook
    old_sys_hook = sys.excepthook

    def thread_exception(args):
        logger.error("Excepción no controlada en hilo %s (%s)",
                     args.thread.name if args.thread else "?",
                     args.exc_type.__name__,
                     exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
        if not show_error_dialog and sys.__stderr__ is not None:
            old_thread_hook(args)

    def system_exception(etype, value, tb):
        logger.error("Excepción no controlada (%s)", etype.__name__,
                     exc_info=(etype, value, tb))
        if not show_error_dialog and sys.__stderr__ is not None:
            old_sys_hook(etype, value, tb)

    threading.excepthook = thread_exception
    sys.excepthook = system_exception
    logger.info("Arrancando CashMiner; este registro corresponde sólo a la aplicación")
    try:
        from cashminer.app.server import launch_app
        launch_app()
        logger.info("Cierre normal de CashMiner")
    except BaseException as exc:
        logger.error("Fallo en el proceso principal (%s)",type(exc).__name__,exc_info=True)
        if show_error_dialog and sys.platform == "win32":
            # No mostrar los secretos ni contenido de excepciones en el cuadro.
            try:
                import ctypes
                ctypes.windll.user32.MessageBoxW(None,
                    "CashMiner no pudo continuar. Revisá el registro de aplicación:\n" + str(path),
                    "CashMiner: error al iniciar", 0x10)
            except (OSError, AttributeError):
                pass
        else:
            raise
    finally:
        logger.info("Fin del registro de aplicación")
        threading.excepthook = old_thread_hook
        sys.excepthook = old_sys_hook
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()
