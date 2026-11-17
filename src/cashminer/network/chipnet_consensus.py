"""Chipnet Faster Blocks rules shared by wallet, headers and mining.

BCHN reference: 3e6827e95c7a17497e09ac15556debd116dea1d0 (preview 29.2.1),
pow.cpp, validation.cpp, consensus/tx_verify.cpp. No network or wallet I/O.
An activation height belongs to a branch. Mining obtains it from validated
headers; the wallet uses the schedule of the explicitly pinned Mina branch.
"""
from __future__ import annotations
from dataclasses import dataclass

ACTIVATION_MTP = 1794744000
LEGACY_INTERVAL = 600
FAST_INTERVAL = 60
COINBASE_MATURITY_TICKS = 60000
ANCHOR_HEIGHT = 16844
ANCHOR_BITS = 0x1D00FFFF
ANCHOR_PARENT_TIME = 1605451779
HALFLIFE = 3600
POW_LIMIT = (1 << 224) - 1
POW_LIMIT_BITS = 0x1D00FFFF
HISTORICAL_CHECKPOINT = (325627, '000000002bb8a32bd6b1022e5370b10e7dc139770d626e1a0911e6b596cf3069')
# Independently matched on BCH Ninja, Imaginary Cash and C3 Soft on 2026-11-17.
PINNED_ACTIVATION_HEIGHT = 332450
ACTIVATION_HASH = '00000000000015fed5ba357ba4baa1f9a283e9446b6ebc12de63152421764051'
POST_UPGRADE_CHECKPOINTS = (
    (332451, '00000000000ecc7187034ddaa4327af300c23fd57bfd2557af6ca2392a022671'),
    (333223, '000000000000ab0a03d5c47c207b0ace38cb7589ece53e3aaf4b3e40e62167f2'),
)


def ticks_at_height(height: int, activation_height: int | None) -> int:
    if height < 0 or (activation_height is not None and activation_height < 0):
        raise ValueError('Altura de ticks inválida')
    if activation_height is None or height <= activation_height:
        return height * LEGACY_INTERVAL
    return activation_height * LEGACY_INTERVAL + (height-activation_height) * FAST_INTERVAL


def interval_at_height(height: int, activation_height: int | None) -> int:
    return FAST_INTERVAL if activation_height is not None and height > activation_height else LEGACY_INTERVAL


@dataclass(frozen=True)
class ChipnetContext:
    parent_height: int
    parent_hash: str
    parent_time: int
    parent_mtp: int
    activation_height: int | None

    @property
    def parent_ticks(self):
        return ticks_at_height(self.parent_height, self.activation_height)

    @property
    def next_interval(self):
        return interval_at_height(self.parent_height+1, self.activation_height)

    @property
    def next_ticks(self):
        return self.parent_ticks+self.next_interval


def context_for_parent(parent: dict, history: list[dict], *, activation_time=ACTIVATION_MTP) -> ChipnetContext:
    if len(history) != 11 or history[-1]['hash'] != parent['hash']:
        raise ValueError('Chipnet requiere once cabeceras consecutivas del padre')
    mtp=sorted(h['time'] for h in history)[5]
    activation=parent.get('activation_height')
    if activation is None and mtp >= activation_time:
        if ticks_at_height(parent['height'], None) % LEGACY_INTERVAL:
            raise ValueError('Activación fuera de la grilla de ticks')
        activation=parent['height']
    return ChipnetContext(parent['height'],parent['hash'],parent['time'],mtp,activation)


def bits_to_target(bits: int) -> int:
    size=bits >> 24
    word=bits & 0x007fffff
    if not word or bits & 0x00800000 or size > 34:
        raise ValueError('nBits inválido')
    value=word >> (8*(3-size)) if size <= 3 else word << (8*(size-3))
    if not 0 < value < (1 << 256):
        raise ValueError('Target inválido')
    return value


def target_to_bits(target: int) -> int:
    if target <= 0:raise ValueError('Target no positivo')
    size=(target.bit_length()+7)//8
    word=target << (8*(3-size)) if size <= 3 else target >> (8*(size-3))
    if word & 0x00800000:word >>= 8;size += 1
    return (size << 24) | word


def expected_bits(parent_height: int, parent_time: int, candidate_time: int, context: ChipnetContext) -> int:
    if (not isinstance(context,ChipnetContext) or context.parent_height != parent_height
            or context.parent_time != parent_time):
        raise ValueError('El contexto de Chipnet no corresponde al padre del trabajo')
    if candidate_time > parent_time + 2*context.next_interval:
        return POW_LIMIT_BITS
    delta_ticks=context.parent_ticks-ANCHOR_HEIGHT*LEGACY_INTERVAL
    if delta_ticks < 0:raise ValueError('Padre anterior al ancla ASERT')
    numerator=(parent_time-ANCHOR_PARENT_TIME-(delta_ticks+LEGACY_INTERVAL))*65536
    # C++ integer division truncates toward zero, unlike Python //.
    exponent=(abs(numerator)//HALFLIFE)*(-1 if numerator < 0 else 1)
    shifts=(exponent >> 16)-16
    fraction=exponent & 65535
    factor=65536+((195766423245049*fraction+971821376*fraction**2+5127*fraction**3+(1<<47)) >> 48)
    target=bits_to_target(ANCHOR_BITS)*factor
    if shifts <= 0:target >>= -shifts
    elif shifts >= 256 or target.bit_length()+shifts > 256:target=POW_LIMIT
    else:target <<= shifts
    target *= LEGACY_INTERVAL//context.next_interval
    return target_to_bits(max(1,min(POW_LIMIT,target)))


def block_subsidy_sats(height: int, context: ChipnetContext, *, halving_interval=210000) -> int:
    if not isinstance(context,ChipnetContext) or height != context.parent_height+1:raise ValueError('Altura de subsidio ajena al trabajo')
    if halving_interval<=0:raise ValueError('Intervalo de halving inválido')
    # BCHN keys the halving to the containing historical 600-tick chunk.
    halvings=(context.next_ticks+LEGACY_INTERVAL-context.next_interval)//(halving_interval*LEGACY_INTERVAL)
    if halvings >= 64:return 0
    return ((50*100000000) >> halvings)//(LEGACY_INTERVAL//context.next_interval)


def coinbase_mature(network: str, creation_height: int, tip_height: int) -> bool:
    """Eligibility in the upcoming block, including a transition-spanning coinbase."""
    if creation_height <= 0 or tip_height < creation_height:return False
    if network != 'chipnet':return tip_height-creation_height+1 >= 100
    return (ticks_at_height(tip_height+1,PINNED_ACTIVATION_HEIGHT)
            -ticks_at_height(creation_height,PINNED_ACTIVATION_HEIGHT)) >= COINBASE_MATURITY_TICKS


def conservative_block_size(context: ChipnetContext) -> int:
    """Chipnet's ABLA floor, normalized to the candidate's interval.

    Header-only mining cannot derive the adaptive ABLA state from block sizes.
    Staying at its 2 MB/10-minute floor is valid even when ABLA permits more.
    """
    return 2000000*context.next_interval//LEGACY_INTERVAL
