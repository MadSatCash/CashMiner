"""Initial mining candidates; the explorer remains the discovery/evidence owner."""
from cashminer.network.endpoints import endpoint
from cashminer.network.p2p import discover_dns
from cashminer.network.policy import choose_mining_peers, select_ranked_peers
from cashminer.network.peer_rankings import read_ranking

PEER_SOURCES = ('dns', 'sqlite', 'combined')
LEGACY_PEER_SOURCE = 'legacy'


def initial_mining_peers(network, source, store, *, ranking_root=None, request_ranking=None):
    if source not in (*PEER_SOURCES, LEGACY_PEER_SOURCE):
        raise ValueError('Fuente de peers P2P inválida')
    # Preserve the existing score, healthy/flaky policy and shared 80-peer cap.
    # Explicit choices never inject static bootstrap or cross-source fallbacks.
    cached = (read_ranking(ranking_root,network.name) if ranking_root is not None and source!='dns' else None)
    # A saved empty list must not hide peers learned since its calculation.
    if cached is not None and not cached['peers']:cached=None
    rows = store.peers(limit=10000, sort_by_score=False) if source != 'dns' and cached is None else []
    if cached is None and source!='dns' and request_ranking is not None:
        request_ranking(network.name)
    def select(bootstrap):
        if cached is not None:
            return select_ranked_peers(cached['peers'],bootstrap,healthy=cached['healthy'],flaky=cached['flaky'])
        return choose_mining_peers(rows,bootstrap,limit=80)
    if source == LEGACY_PEER_SOURCE:
        return select(list(network.bootstrap))
    dns = []
    if source in ('dns', 'combined'):
        dns = list(dict.fromkeys(endpoint(ip, port)
            for ip, port, _ in discover_dns(network, limit=80)))
    decision = select(dns)
    decision.update(source=source, dns_candidates=len(dns))
    if not decision['peers']:
        note = (' Esta red no tiene DNS seeds configuradas.'
                if source == 'dns' and not network.seeds else '')
        raise ValueError('No hay candidatos P2P en la fuente elegida (' + source + ').' + note)
    return decision
