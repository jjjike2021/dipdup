import demo_tezos_nft_marketplace.models as models
from demo_tezos_nft_marketplace.types.hen_minter.tezos_parameters.mint_objkt import MintOBJKTParameter
from demo_tezos_nft_marketplace.types.hen_minter.tezos_storage import HenMinterStorage
from demo_tezos_nft_marketplace.types.hen_objkts.tezos_parameters.mint import MintParameter
from demo_tezos_nft_marketplace.types.hen_objkts.tezos_storage import HenObjktsStorage
from dipdup.context import HandlerContext
from dipdup.models.tezos import TezosTransaction


async def on_mint(
    ctx: HandlerContext,
    mint_objkt: TezosTransaction[MintOBJKTParameter, HenMinterStorage],
    mint: TezosTransaction[MintParameter, HenObjktsStorage],
) -> None:
    holder, _ = await models.Holder.get_or_create(address=mint.parameter.address)
    token = models.Token(
        id=mint.parameter.token_id,
        creator=holder,
        supply=mint.parameter.amount,
        level=mint.data.level,
        timestamp=mint.data.timestamp,
    )
    await token.save()