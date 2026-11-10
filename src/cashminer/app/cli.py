"""Herramientas CLI y acceso a interfaz gráfica de CashMiner 2.0."""
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

from cashminer import __version__
from cashminer.config import network_db_path
from cashminer.network.endpoints import endpoint, split_endpoint
from cashminer.network.import_legacy_peers import inspect_dump, migrate_network
from cashminer.network.networks import NETWORKS
from cashminer.network.p2p import discover_dns, probe_peer
from cashminer.network.scoring import operational_score
from cashminer.network.peer_store import PeerStore


def _print_peers(store,limit=15):
    print(f"{'SCORE':>6}  {'PEER':<48} {'OK':>5} {'FAIL':>5} ESTADO")
    for row in store.peers(limit):
        fail=(row['tcp_fail_count'] or 0)+(row['handshake_fail_count'] or 0)
        print(f"{operational_score(row):6.1f}  {endpoint(row['ip'],row['port']):<48} "
              f"{row['handshake_ok_count']:>5} {fail:>5} {str(row['last_status'] or '-')[:30]}")


def _record_probe(store, network, ip, port, *, timeout, getaddr, limit):
    store.record(ip,port,'connect_attempt')
    result=probe_peer(network,ip,port,timeout=timeout,getaddr=getaddr,limit=limit)
    if result.connected:
        store.record(ip,port,'tcp_ok')
    else:
        store.record(ip,port,'tcp_fail',result=result.error)
    if result.handshake:
        store.record(ip,port,'handshake_ok',latency_ms=result.latency_ms,details=result.metadata)
    elif result.connected:
        store.record(ip,port,'handshake_fail',result=result.error)
    if getaddr:
        store.record(ip,port,'addr_ok' if result.addr_received else 'addr_fail',result=result.error)
        for candidate_ip,candidate_port in result.candidates or []:
            store.add_peer(candidate_ip,candidate_port,
                           source_type='peer',source_value=endpoint(ip,port))
    print(f"{endpoint(ip,port)} TCP={result.connected} handshake={result.handshake} "
          f"addr={len(result.candidates or [])} {result.error or ''}")
    print('  Cadena: NO verificada. El handshake no es una prueba de consenso.')
    return result


def _seed(store,network, limit):
    found=[]
    for ip,port,seed in discover_dns(network,limit=limit):
        store.add_peer(ip,port,source_type='seed',source_value=seed)
        found.append((ip,port))
    for peer in network.bootstrap:
        ip,port=split_endpoint(peer)
        store.add_peer(ip,port,source_type='bootstrap',source_value=peer)
        if (ip,port) not in found:found.append((ip,port))
    print(f"Candidatos DNS/bootstrap: {len(found)} (no validados)")
    return found


def _dashboard(store,network):
    while True:
        print('\n'+'='*65)
        print(f'CASHMINER 2.0 - HERRAMIENTAS P2P  |  Red: {network.name}  |  v{__version__}')
        print('Herramientas de peers: la minería FABLOUS se controla desde la interfaz gráfica.')
        print('Peers:',store.counts(),' | DB:',round(store.size_bytes()/1024**2,2),'MiB')
        print('1 - Lista de peers   2 - Agregar peer   3 - Probar un peer')
        print('4 - Buscar seeds    5 - Probar y pedir getaddr  6 - Integridad')
        print('7 - Mantenimiento   0 - Salir')
        choice=input('> ').strip()
        if choice=='0':return
        try:
            if choice=='1':_print_peers(store)
            elif choice=='2':
                ip,port=split_endpoint(input('IP:puerto> '),network.default_port)
                store.add_peer(ip,port,source_type='manual',source_value='interfaz')
            elif choice in ('3','5'):
                ip,port=split_endpoint(input('IP:puerto> '),network.default_port)
                _record_probe(store,network,ip,port,timeout=4,getaddr=choice=='5',limit=100)
            elif choice=='4':_seed(store,network,40)
            elif choice=='6':print(store.integrity())
            elif choice=='7':print(store.cleanup())
        except (ValueError,KeyboardInterrupt,EOFError,RuntimeError) as err:
            print('Aviso:',err)


def build_parser():
    p=argparse.ArgumentParser(prog='cashminer',description='CashMiner - billeteras, minería FABLOUS y P2P')
    p.add_argument('--network',choices=sorted(NETWORKS),default='tempnet_fablous_2026')
    p.add_argument('--db-mib',type=int,default=100,help='Presupuesto SQLite en MiB (por red)')
    sub=p.add_subparsers(dest='command')
    sub.add_parser('gui',help='Iniciar interfaz local de CashMiner')
    sub.add_parser('menu',help='Herramientas P2P en consola')
    sub.add_parser('status',help='Estado local de peers')
    l=sub.add_parser('peers',help='Listado priorizado por conectividad')
    l.add_argument('--limit',type=int,default=20)
    a=sub.add_parser('add',help='Agregar endpoint IP:puerto sin verificar')
    a.add_argument('endpoint')
    b=sub.add_parser('probe',help='Handshake P2P saliente con un endpoint')
    b.add_argument('endpoint');b.add_argument('--getaddr',action='store_true')
    b.add_argument('--timeout',type=float,default=4.0)
    d=sub.add_parser('discover',help='Seeds y exploración limitada')
    d.add_argument('--probe',action='store_true',help='También probar candidatos por P2P')
    d.add_argument('--max-probes',type=int,default=10)
    d.add_argument('--timeout',type=float,default=4.0)
    m=sub.add_parser('import-pgdump',help='Importar backup de PostgreSQL con COPY ASCII')
    m.add_argument('dump');m.add_argument('--apply',action='store_true',help='Importar (sin esto solo vista previa)')
    m.add_argument('--merge',action='store_true',help='Agregar solo peers no existentes')
    sub.add_parser('integrity',help='Comprobar SQLite')
    c=sub.add_parser('cleanup',help='Consolidar historial y liberar espacio')
    c.add_argument('--days',type=int,default=30);c.add_argument('--max-events',type=int,default=10000)
    return p


def main(argv=None):
    args=build_parser().parse_args(argv)
    if args.command in (None,'gui'):
        from cashminer.app.logging_setup import run_gui
        run_gui()
        return 0
    network=NETWORKS[args.network]
    if args.command == 'import-pgdump' and not args.apply:
        print('Vista previa del respaldo (NINGUNA ESCRITURA):')
        print(json.dumps(inspect_dump(args.dump),indent=2))
        return 0
    store=PeerStore(network_db_path(args.network),max_mib=args.db_mib)
    cmd=args.command or 'menu'
    if cmd=='status':
        print('Red:',network.identifier,'| Ruta:',store.path)
        print('Estadísticas:',store.counts(),'| Bytes:',store.size_bytes())
        print('IMPORTANTE: la base contiene observaciones, no consenso verificado.')
    elif cmd=='peers':_print_peers(store,args.limit)
    elif cmd=='add':
        ip,port=split_endpoint(args.endpoint,network.default_port)
        store.add_peer(ip,port,source_type='manual',source_value='CLI')
        print('Agregado:',endpoint(ip,port),'(sin validar)')
    elif cmd=='probe':
        ip,port=split_endpoint(args.endpoint,network.default_port)
        store.add_peer(ip,port,source_type='manual',source_value='CLI probe')
        _record_probe(store,network,ip,port,timeout=max(1,min(20,args.timeout)),
                      getaddr=args.getaddr,limit=100)
    elif cmd=='discover':
        found=_seed(store,network,60)
        if args.probe:
            targets=list(dict.fromkeys(found+[(r['ip'],r['port']) for r in store.peers(50)]))
            targets=targets[:max(1,min(args.max_probes,32))]
            with ThreadPoolExecutor(max_workers=min(4,len(targets) or 1)) as pool:
                futures={pool.submit(_record_probe,store,network,ip,port,
                                     timeout=max(1,min(20,args.timeout)),getaddr=True,limit=100):(ip,port)
                         for ip,port in targets}
                for f in as_completed(futures):
                    try:f.result()
                    except Exception as e:print('Error explorador:',e)
    elif cmd=='import-pgdump':
        print(migrate_network(args.dump,args.network,store,allow_merge=args.merge))
        print('Conteo actual:',store.counts())
    elif cmd=='integrity':print(store.integrity())
    elif cmd=='cleanup':print(store.cleanup(days=args.days,max_events=args.max_events))
    elif cmd=='menu':_dashboard(store,network)
    else:raise AssertionError(cmd)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
