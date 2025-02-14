from collections import deque
from datetime import datetime
from typing import Any

from dipdup.config.tezos_big_maps import TezosBigMapsHandlerConfig
from dipdup.config.tezos_big_maps import TezosBigMapsIndexConfig
from dipdup.exceptions import ConfigInitializationException
from dipdup.exceptions import ConfigurationError
from dipdup.indexes.tezos_big_maps.fetcher import BigMapFetcher
from dipdup.indexes.tezos_big_maps.fetcher import get_big_map_pairs
from dipdup.indexes.tezos_big_maps.matcher import match_big_maps
from dipdup.indexes.tezos_tzkt import TezosIndex
from dipdup.models import RollbackMessage
from dipdup.models import SkipHistory
from dipdup.models.tezos import TezosBigMapAction
from dipdup.models.tezos import TezosBigMapData
from dipdup.models.tezos import TezosBigMapDiff
from dipdup.models.tezos_tzkt import TezosTzktMessageType
from dipdup.performance import metrics

QueueItem = tuple[TezosBigMapData, ...] | RollbackMessage


class TezosBigMapsIndex(
    TezosIndex[TezosBigMapsIndexConfig, QueueItem],
    message_type=TezosTzktMessageType.big_map,
):
    async def _synchronize(self, sync_level: int) -> None:
        """Fetch operations via Fetcher and pass to message callback"""
        index_level = await self._enter_sync_state(sync_level)
        if index_level is None:
            return

        if self._config.skip_history == SkipHistory.always:
            await self._synchronize_level(sync_level)
        elif self._config.skip_history == SkipHistory.once and not self.state.level:
            await self._synchronize_level(sync_level)
        else:
            await self._synchronize_full(index_level, sync_level)

        await self._exit_sync_state(sync_level)

    async def _synchronize_full(self, index_level: int, sync_level: int) -> None:
        first_level = index_level + 1
        self._logger.info('Fetching big map diffs from level %s to %s', first_level, sync_level)

        fetcher = BigMapFetcher.create(
            self._config,
            self._datasources,
            first_level,
            sync_level,
        )

        async for _, big_maps in fetcher.fetch_by_level():
            await self._process_level_data(big_maps, sync_level)

    async def _synchronize_level(self, head_level: int) -> None:
        # NOTE: Checking late because feature flags could be modified after loading config
        if not self._ctx.config.advanced.early_realtime:
            raise ConfigurationError('`skip_history` requires `early_realtime` feature flag to be enabled')

        big_map_pairs = get_big_map_pairs(self._config.handlers)
        big_map_ids: set[tuple[int, str, str]] = set()

        for address, path in big_map_pairs:
            async for contract_big_maps in self.random_datasource.iter_contract_big_maps(address):
                for contract_big_map in contract_big_maps:
                    if contract_big_map['path'] == path:
                        big_map_ids.add((int(contract_big_map['ptr']), address, path))

        # NOTE: Do not use `_process_level_data` here; we want to maintain transaction manually.
        async with self._ctx.transactions.in_transaction(head_level, head_level, self.name):
            for big_map_id, address, path in big_map_ids:
                async for big_map_keys in self.random_datasource.iter_big_map(big_map_id, head_level):
                    big_map_data = tuple(
                        TezosBigMapData(
                            id=big_map_key['id'],
                            level=head_level,
                            operation_id=head_level,
                            timestamp=datetime.now(),
                            bigmap=big_map_id,
                            contract_address=address,
                            path=path,
                            action=TezosBigMapAction.ADD_KEY,
                            active=big_map_key['active'],
                            key=big_map_key['key'],
                            value=big_map_key['value'],
                        )
                        for big_map_key in big_map_keys
                    )
                    metrics.objects_indexed += len(big_map_data)

                    matched_handlers = match_big_maps(self._ctx.package, self._config.handlers, big_map_data)
                    for handler_config, big_map_diff in matched_handlers:
                        await self._call_matched_handler(handler_config, big_map_diff)

            await self._update_state(level=head_level)

    async def _call_matched_handler(
        self, handler_config: TezosBigMapsHandlerConfig, level_data: TezosBigMapDiff[Any, Any]
    ) -> None:
        if not handler_config.parent:
            raise ConfigInitializationException

        await self._ctx.fire_handler(
            handler_config.callback,
            handler_config.parent.name,
            # NOTE: missing `operation_id` field in API to identify operation
            None,
            level_data,
        )

    def _match_level_data(self, handlers: Any, level_data: Any) -> deque[Any]:
        return match_big_maps(self._ctx.package, handlers, level_data)
