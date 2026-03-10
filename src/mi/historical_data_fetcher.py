"""
Historical Data Fetcher for ML Training

Загружает полную историю торгуемых рынков от момента их появления
для обучения ML моделей на максимальной глубине данных.
"""

import json
import logging
import asyncio
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


class HistoricalDataFetcher:
    """
    Загрузчик исторических данных с биржи для обучения ML моделей
    """

    def __init__(self, exchange, cache_dir: str = "/var/lib/trading-bot/historical_data"):
        """
        Args:
            exchange: ExchangeAdapter instance
            cache_dir: Директория для кэширования исторических данных
        """
        self.exchange = exchange
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # Dates when each pair first appeared on Binance.
        # These are used to download the maximum possible historical depth
        # so the model can learn from every market cycle the coin has seen.
        self.symbol_launch_dates = {
            # ── Major BTC/ETH ──────────────────────────────────────────────
            'BTCUSDT':   '2017-08-17',
            'ETHUSDT':   '2017-08-17',
            'BNBUSDT':   '2017-11-06',
            # ── Layer-1 / Smart-contract platforms ──────────────────────────
            'ADAUSDT':   '2018-04-17',
            'SOLUSDT':   '2020-08-11',
            'DOTUSDT':   '2020-08-19',
            'AVAXUSDT':  '2020-09-22',
            'MATICUSDT': '2019-04-26',
            'NEARUSDT':  '2020-10-16',
            'FTMUSDT':   '2019-06-12',
            'ALGOUSDT':  '2019-06-22',
            'ATOMUSDT':  '2019-04-22',
            'LTCUSDT':   '2017-12-13',
            'TRXUSDT':   '2018-06-11',
            'XLMUSDT':   '2018-01-05',
            'VETUSDT':   '2019-07-01',
            'HBARUSDT':  '2020-09-17',
            'ICPUSDT':   '2021-05-10',
            'FILUSDT':   '2020-10-15',
            'EGLDUSDT':  '2020-09-03',
            'FLOWUSDT':  '2021-04-07',
            'THETAUSDT': '2019-01-17',
            'AXSUSDT':   '2020-11-04',
            'SANDUSDT':  '2020-08-14',
            'MANAUSDT':  '2020-08-06',
            'GALAUSDT':  '2021-09-16',
            'APEUSDT':   '2022-03-17',
            'OPUSDT':    '2022-06-01',
            'ARBUSDT':   '2023-03-23',
            'SEIUSDT':   '2023-08-15',
            'SUIUSDT':   '2023-05-03',
            # ── DeFi ────────────────────────────────────────────────────────
            'UNIUSDT':   '2020-09-17',
            'AAVEUSDT':  '2020-10-16',
            'MKRUSDT':   '2019-04-26',
            'COMPUSDT':  '2020-06-23',
            'SNXUSDT':   '2019-01-24',
            'CRVUSDT':   '2020-08-14',
            '1INCHUSDT': '2021-01-11',
            'LDOUSDT':   '2023-02-09',
            # ── Meme / high-volatility ───────────────────────────────────────
            'DOGEUSDT':  '2019-07-05',
            'SHIBUSDT':  '2021-05-11',
            'PEPEUSDT':  '2023-05-05',
            # ── Layer-2 ──────────────────────────────────────────────────────
            'IMXUSDT':   '2021-11-24',
            # ── Payments / utility ───────────────────────────────────────────
            'XRPUSDT':   '2018-05-04',
            'LINKUSDT':  '2017-11-22',
        }

        # Стандартная дата для неизвестных символов (начало Binance)
        self.default_start_date = '2017-08-17'

    def get_symbol_start_date(self, symbol: str) -> datetime:
        """
        Получить дату начала торговли символа

        Args:
            symbol: Торговый символ (например, 'BTCUSDT')

        Returns:
            datetime объект с датой начала
        """
        date_str = self.symbol_launch_dates.get(symbol, self.default_start_date)
        return datetime.strptime(date_str, '%Y-%m-%d')

    def _get_cache_path(self, symbol: str, timeframe: str) -> Path:
        """Путь к кэшированному файлу"""
        return self.cache_dir / f"{symbol}_{timeframe}.parquet"

    def _get_metadata_path(self, symbol: str, timeframe: str) -> Path:
        """Путь к метаданным кэша"""
        return self.cache_dir / f"{symbol}_{timeframe}_meta.json"

    async def fetch_full_history(
        self,
        symbol: str,
        timeframe: str = '1h',
        force_reload: bool = False
    ) -> Optional[pd.DataFrame]:
        """
        Загрузить полную историю символа от момента его появления

        Args:
            symbol: Торговый символ
            timeframe: Таймфрейм (1m, 5m, 15m, 1h, 4h, 1d)
            force_reload: Принудительная перезагрузка (игнорировать кэш)

        Returns:
            DataFrame с историческими данными или None при ошибке
        """
        cache_path = self._get_cache_path(symbol, timeframe)
        metadata_path = self._get_metadata_path(symbol, timeframe)

        # Проверить кэш
        if not force_reload and cache_path.exists():
            try:
                # Проверить актуальность кэша
                if metadata_path.exists():
                    with open(metadata_path, 'r') as f:
                        metadata = json.load(f)

                    last_update = datetime.fromisoformat(metadata['last_update'])
                    # Если кэш свежий (< 24 часов), использовать его
                    if datetime.now() - last_update < timedelta(hours=24):
                        logger.info(f"📂 Loading {symbol} {timeframe} from cache")
                        df = pd.read_parquet(cache_path)
                        logger.info(
                            f"✅ Loaded {len(df)} candles from cache (from {df.index[0]} to {df.index[-1]})")
                        return df
            except Exception as e:
                logger.warning(f"Failed to load cache for {symbol}: {e}")

        # Загрузить с биржи
        logger.info(f"🔄 Fetching full history for {symbol} {timeframe}...")

        start_date = self.get_symbol_start_date(symbol)
        end_date = datetime.now()

        # Расчет количества свечей
        timeframe_minutes = self._timeframe_to_minutes(timeframe)
        total_minutes = int((end_date - start_date).total_seconds() / 60)
        expected_candles = total_minutes // timeframe_minutes

        logger.info(
            f"📊 Expected ~{expected_candles:,} candles from "
            f"{start_date.date()} to {end_date.date()}")

        # Загрузка пакетами (макс 1000 свечей за раз)
        all_data = []
        current_start = start_date
        limit = 1000

        while current_start < end_date:
            try:
                # Загрузить пакет
                candles = self.exchange.get_klines(
                    symbol=symbol,
                    interval=timeframe,
                    limit=limit,
                    startTime=int(current_start.timestamp() * 1000)
                )

                if not candles or len(candles) == 0:
                    logger.warning(f"No more data available from {current_start}")
                    break

                all_data.extend(candles)

                # Последняя timestamp
                last_timestamp = candles[-1][0] / 1000
                current_start = datetime.fromtimestamp(
                    last_timestamp) + timedelta(minutes=timeframe_minutes)

                logger.info(f"📥 Loaded {len(all_data):,} candles so far...")

                # Небольшая задержка чтобы не перегрузить API
                await asyncio.sleep(0.1)

                # Если получили меньше чем limit, значит достигли конца
                if len(candles) < limit:
                    break

            except Exception as e:
                logger.error(f"Error fetching data from {current_start}: {e}")
                # Попробовать продолжить с другой точки
                current_start += timedelta(days=1)
                continue

        if not all_data:
            logger.error(f"Failed to fetch any data for {symbol}")
            return None

        # Конвертировать в DataFrame
        df = self._convert_to_dataframe(all_data)

        logger.info(f"✅ Fetched {len(df):,} candles for {symbol} {timeframe}")
        logger.info(f"📅 Date range: {df.index[0]} to {df.index[-1]}")

        # Сохранить в кэш
        try:
            df.to_parquet(cache_path)

            # Сохранить метаданные
            metadata = {
                'symbol': symbol,
                'timeframe': timeframe,
                'candles': len(df),
                'start_date': df.index[0].isoformat(),
                'end_date': df.index[-1].isoformat(),
                'last_update': datetime.now().isoformat()
            }
            with open(metadata_path, 'w') as f:
                json.dump(metadata, f, indent=2)

            logger.info(f"💾 Cached data for {symbol} {timeframe}")
        except Exception as e:
            logger.warning(f"Failed to cache data: {e}")

        return df

    def _timeframe_to_minutes(self, timeframe: str) -> int:
        """Конвертировать timeframe в минуты"""
        mapping = {
            '1m': 1,
            '3m': 3,
            '5m': 5,
            '15m': 15,
            '30m': 30,
            '1h': 60,
            '2h': 120,
            '4h': 240,
            '6h': 360,
            '8h': 480,
            '12h': 720,
            '1d': 1440,
            '3d': 4320,
            '1w': 10080,
            '1M': 43200,
        }
        return mapping.get(timeframe, 60)

    def _convert_to_dataframe(self, candles: List) -> pd.DataFrame:
        """
        Конвертировать raw candles в pandas DataFrame

        Args:
            candles: List of [timestamp, open, high, low, close, volume, ...]

        Returns:
            DataFrame with OHLCV data
        """
        df = pd.DataFrame(candles, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_volume', 'trades',
            'taker_buy_base', 'taker_buy_quote', 'ignore'
        ])

        # Конвертировать timestamp в datetime
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)

        # Конвертировать в float
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = df[col].astype(float)

        # Оставить только нужные колонки
        df = df[['open', 'high', 'low', 'close', 'volume']]

        # Удалить дубликаты
        df = df[~df.index.duplicated(keep='last')]

        # Сортировка по времени
        df.sort_index(inplace=True)

        return df

    async def update_cached_data(self, symbol: str,
                                 timeframe: str = '1h') -> Optional[pd.DataFrame]:
        """
        Обновить кэшированные данные новыми свечами

        Args:
            symbol: Торговый символ
            timeframe: Таймфрейм

        Returns:
            Updated DataFrame
        """
        cache_path = self._get_cache_path(symbol, timeframe)

        if not cache_path.exists():
            # Нет кэша, загрузить полностью
            return await self.fetch_full_history(symbol, timeframe)

        # Загрузить существующий кэш
        try:
            df = pd.read_parquet(cache_path)
            last_timestamp = df.index[-1]

            # Загрузить новые данные
            logger.info(f"🔄 Updating {symbol} {timeframe} from {last_timestamp}")

            candles = self.exchange.get_klines(
                symbol=symbol,
                interval=timeframe,
                limit=1000,
                startTime=int(last_timestamp.timestamp() * 1000)
            )

            if candles and len(candles) > 0:
                new_df = self._convert_to_dataframe(candles)

                # Объединить
                df = pd.concat([df, new_df])
                df = df[~df.index.duplicated(keep='last')]
                df.sort_index(inplace=True)

                # Сохранить
                df.to_parquet(cache_path)

                logger.info(f"✅ Updated {symbol}: added {len(new_df)} new candles, total {len(df)}")

            return df

        except Exception as e:
            logger.error(f"Failed to update cached data: {e}")
            return None

    def get_cache_info(self, symbol: str, timeframe: str) -> Optional[Dict]:
        """Получить информацию о кэшированных данных"""
        metadata_path = self._get_metadata_path(symbol, timeframe)

        if not metadata_path.exists():
            return None

        try:
            with open(metadata_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to read metadata: {e}")
            return None
